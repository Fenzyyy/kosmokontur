"""Эвристический оптимизатор топливного контура.

Оптимизатор не дублирует физику модели. Он генерирует кандидаты Plan и
оценивает их существующей функцией engine.evaluate().

Метод:
    1. генерирует допустимые варианты инвестиций;
    2. строит начальный greedy-план поставок;
    3. выполняет локальный coordinate-descent по годовым заказам;
    4. выбирает план с лексикографическим приоритетом:
         HARD violations -> дефицит -> дефицит критического спроса ->
         недобор 45-дневного резерва -> стоимость.

Это эвристика, а не доказанный глобальный оптимизатор.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .engine import evaluate
from .model import (
    Case,
    InitialStockLot,
    InvestmentDecision,
    Plan,
    Result,
    Scenario,
)
from .resolve import resolve


@dataclass(frozen=True)
class OptimizerConfig:
    """Параметры эвристического поиска."""

    max_investment_options_exhaustive: int = 8
    max_local_search_passes: int = 8
    step_fraction_of_capacity: float = 0.10
    min_step_tons: float = 1.0
    initial_reserve: bool = True


@dataclass
class OptimizationResult:
    """Результат поиска лучшего по данной эвристике плана."""

    plan: Plan
    scenario_results: Dict[str, Result]
    score: Tuple[float, ...]
    candidates_checked: int = 0
    iterations: int = 0
    notes: List[str] = field(default_factory=list)

    @property
    def feasible(self) -> bool:
        return all(result.feasible for result in self.scenario_results.values())

    @property
    def total_cost(self) -> float:
        return sum(r.kpis["total_cost"] for r in self.scenario_results.values())

    @property
    def total_shortage(self) -> float:
        return sum(r.kpis["shortage_total"] for r in self.scenario_results.values())


def _month_add(year: int, month: int, months: int) -> Tuple[int, int]:
    """Добавить целое число месяцев к (year, month)."""
    idx = year * 12 + (month - 1) + months
    new_year, new_month = divmod(idx, 12)
    return new_year, new_month + 1


def _investment_decision(case: Case, option_id: str) -> Optional[InvestmentDecision]:
    """Строит самый ранний формально допустимый график CAPEX для опции."""
    option = case.options[option_id]

    stage_year = option.earliest_stage_year or case.first_year
    latest_year = option.latest_capex_year or case.last_year
    if stage_year > latest_year:
        return None

    stage_year = max(stage_year, case.first_year)
    stage_dates = tuple((stage_year, 1) for _ in option.stage_amounts)
    last_stage = stage_dates[-1] if stage_dates else (stage_year, 1)

    service_year, service_month = _month_add(
        last_stage[0], last_stage[1], int(round(option.min_build_months))
    )
    if option.earliest_in_service_year is not None:
        service_year = max(service_year, option.earliest_in_service_year)

    if service_year < case.first_year:
        service_year, service_month = case.first_year, 1
    if service_year > case.last_year:
        return None

    return InvestmentDecision(
        stage_dates=stage_dates,
        in_service=(service_year, service_month),
    )


def _investment_subsets(
    case: Case,
    config: OptimizerConfig,
) -> Iterable[Tuple[str, ...]]:
    """Перебирает комбинации инвестиций."""
    ids = tuple(case.options)
    n = len(ids)

    if n == 0:
        yield ()
    elif n <= config.max_investment_options_exhaustive:
        for mask in range(1 << n):
            yield tuple(ids[i] for i in range(n) if mask & (1 << i))
    else:
        # Для большого числа опций полный power-set слишком дорог.
        yield ()
        for option_id in ids:
            yield (option_id,)
        yield ids


def _with_investments(
    base_plan: Optional[Plan],
    case: Case,
    option_ids: Sequence[str],
) -> Optional[Plan]:
    plan = copy.deepcopy(base_plan) if base_plan is not None else Plan("optimizer")
    plan.investments = {}

    for option_id in option_ids:
        decision = _investment_decision(case, option_id)
        if decision is None:
            return None
        plan.investments[option_id] = decision

    return plan


def _source_rank(case: Case, source_id: str) -> Tuple[float, float, float]:
    """Предварительный ранг источника по удельной стоимости."""
    source = case.sources[source_id]
    effective = source.variable_cost + source.reservation_rate
    return effective, source.variable_cost, source.capacity


def _set_order(
    case: Case,
    plan: Plan,
    source_id: str,
    year: int,
    order: float,
) -> None:
    """Установить заказ и при необходимости подобрать резерв мощности."""
    source = case.sources[source_id]
    order = max(0.0, float(order))

    by_year = plan.orders.setdefault(source_id, {})
    if order <= 1e-9:
        by_year.pop(year, None)
    else:
        by_year[year] = order

    if not by_year:
        plan.orders.pop(source_id, None)

    if source.reservation_rate == 0 and source.top_share == 0:
        # Plan.reserved_capacity() автоматически вернёт полную мощность.
        if source_id in plan.reserved:
            plan.reserved[source_id].pop(year, None)
            if not plan.reserved[source_id]:
                plan.reserved.pop(source_id, None)
        return

    res = resolve(case, plan)
    frac = res.cal.fraction_available(year, res.avail_day[source_id])
    if frac <= 1e-12 or order <= 1e-9:
        if source_id in plan.reserved:
            plan.reserved[source_id].pop(year, None)
            if not plan.reserved[source_id]:
                plan.reserved.pop(source_id, None)
        return

    reserved = min(source.capacity, order / frac)
    plan.reserved.setdefault(source_id, {})[year] = reserved


def _candidate_initial_stock(case: Case, plan: Plan) -> None:
    """Сформировать начальный 45-дневный резерв из доступного источника."""
    if not case.years:
        return

    first_total, _ = case.demand_series("base")[case.first_year]
    reserve = first_total * case.constraints.reserve_days / 365.0
    if reserve <= 0:
        return

    res = resolve(case, plan)
    candidates = [
        sid
        for sid in case.sources
        if res.avail_day[sid] is not None and res.avail_day[sid] <= 0
    ]
    candidates.sort(key=lambda sid: _source_rank(case, sid))

    # Начальный запас физически хранится в базовом режиме.
    # Не генерируем заведомо невозможный объём.
    base_capacity = case.storage[case.base_storage_id].capacity
    remaining = min(reserve, base_capacity)
    lots: List[InitialStockLot] = []
    for sid in candidates:
        if remaining <= 1e-9:
            break
        take = min(remaining, case.sources[sid].capacity)
        if take > 0:
            lots.append(InitialStockLot(sid, take))
            remaining -= take

    plan.initial_stock = lots


def _build_greedy_plan(
    case: Case,
    base_plan: Plan,
    scenarios: Sequence[Scenario],
    initial_reserve: bool,
) -> Plan:
    """Сформировать робастный стартовый supply plan для всех сценариев.

    Для начального кандидата берём максимум спроса по сценариям и минимальную
    долю фактической поставки по каждому каналу. Это не заменяет evaluate():
    точная физика по-прежнему считается в engine.evaluate().
    """
    plan = copy.deepcopy(base_plan)

    if initial_reserve:
        _candidate_initial_stock(case, plan)

    scenario_list = tuple(scenarios)
    if not scenario_list:
        raise ValueError("Для greedy-плана нужен хотя бы один сценарий")

    demand_by_scenario = {
        scenario.scenario_id: case.demand_series(
            scenario.demand_variant,
            scenario.demand_multiplier,
        )
        for scenario in scenario_list
    }

    inventory = sum(lot.tons for lot in plan.initial_stock)

    for year in case.years:
        total_demand = max(
            demand[year][0] for demand in demand_by_scenario.values()
        )

        if year != case.last_year:
            next_total = max(
                demand[year + 1][0] for demand in demand_by_scenario.values()
            )
            next_reserve = next_total * case.constraints.reserve_days / 365.0
        else:
            next_reserve = 0.0

        need = max(0.0, total_demand + next_reserve - inventory)
        year_actual_delivery = 0.0

        res = resolve(case, plan)
        available = []
        for sid, source in case.sources.items():
            frac = res.cal.fraction_available(year, res.avail_day[sid])
            if frac <= 1e-12:
                continue

            min_share = min(
                scenario.delivery_share.get((sid, year), 1.0)
                for scenario in scenario_list
            )
            min_share = max(0.0, float(min_share))
            max_order = source.capacity * frac
            max_actual = max_order * min_share

            rank = (
                (source.variable_cost + source.reservation_rate) / min_share
                if min_share > 1e-12
                else float("inf")
            )
            available.append((sid, frac, max_order, max_actual, rank))

        available.sort(key=lambda x: (x[4], _source_rank(case, x[0])))

        for sid, _frac, max_order, max_actual, _rank in available:
            if need <= 1e-9:
                break

            min_share = min(
                scenario.delivery_share.get((sid, year), 1.0)
                for scenario in scenario_list
            )
            min_share = max(0.0, float(min_share))

            if min_share <= 1e-12:
                continue

            actual_need = min(need, max_actual)
            order = min(max_order, actual_need / min_share)
            if order <= 1e-9:
                continue

            _set_order(case, plan, sid, year, order)
            actual_received = order * min_share
            year_actual_delivery += actual_received
            need -= actual_received

        inventory = max(0.0, inventory + year_actual_delivery - total_demand)

    return plan


def _score_results(
    results: Mapping[str, Result],
) -> Tuple[float, ...]:
    """Лексикографический score: сначала выполнимость, затем качество."""
    hard = sum(r.kpis["hard_violations"] for r in results.values())
    shortage_critical = sum(r.kpis["shortage_critical"] for r in results.values())
    shortage_total = sum(r.kpis["shortage_total"] for r in results.values())

    reserve_gap = 0.0
    benchmark_misses = 0
    total_cost = 0.0
    pv_cost = 0.0

    for result in results.values():
        reserve_gap += sum(
            max(0.0, row["reserve_required"] - row["reserve_stock_at_check"])
            for row in result.yearly
        )
        benchmark_misses += result.kpis["benchmark_misses"]
        total_cost += result.kpis["total_cost"]
        pv_cost += result.kpis["pv_cost"]

    return (
        float(hard),
        shortage_critical,
        shortage_total,
        reserve_gap,
        float(benchmark_misses),
        total_cost,
        pv_cost,
    )


def _evaluate_all(
    case: Case,
    plan: Plan,
    scenarios: Sequence[Scenario],
) -> Tuple[Dict[str, Result], Tuple[float, ...]]:
    results = {
        scenario.scenario_id: evaluate(case, plan, scenario)
        for scenario in scenarios
    }
    return results, _score_results(results)



def _storage_overflow_excess(results: Mapping[str, Result]) -> float:
    """Суммарное физическое переполнение хранения по всем сценариям."""
    return sum(
        max(0.0, float(v.excess or 0.0))
        for result in results.values()
        for v in result.violations
        if v.code in ("STORAGE_OVERFLOW", "INITIAL_STOCK_EXCEEDS_STORAGE")
    )


def _storage_is_feasible(results: Mapping[str, Result]) -> bool:
    """План не должен иметь физического переполнения storage ни в одном сценарии."""
    return _storage_overflow_excess(results) <= 1e-8


def _clip_initial_stock_to_storage(case: Case, plan: Plan) -> None:
    """Обрезать только физически невозможную часть начального запаса."""
    capacity = case.storage[case.base_storage_id].capacity
    total = sum(lot.tons for lot in plan.initial_stock)
    if total <= capacity + 1e-9 or total <= 0:
        return
    factor = capacity / total
    plan.initial_stock = [
        InitialStockLot(lot.source_id, lot.tons * factor)
        for lot in plan.initial_stock
    ]


def _repair_storage_overflow(
    case: Case,
    seed: Plan,
    scenarios: Sequence[Scenario],
    config: OptimizerConfig,
) -> Tuple[Plan, Dict[str, Result], Tuple[float, ...], int]:
    """Устранить физическое переполнение storage с минимальным снижением заказов."""
    current = copy.deepcopy(seed)
    _clip_initial_stock_to_storage(case, current)
    repair_iterations = 0
    max_repairs = max(1, len(case.years) * len(case.sources) * 4)

    for _ in range(max_repairs):
        results, score = _evaluate_all(case, current, scenarios)
        if _storage_is_feasible(results):
            return current, results, score, repair_iterations

        overflow_by_year: Dict[int, float] = {}
        for result in results.values():
            for violation in result.violations:
                if violation.code != "STORAGE_OVERFLOW" or violation.year is None:
                    continue
                overflow_by_year[violation.year] = max(
                    overflow_by_year.get(violation.year, 0.0),
                    float(violation.excess or 0.0),
                )

        if not overflow_by_year:
            break

        year = max(overflow_by_year, key=overflow_by_year.get)

        # Источник с наибольшей фактической поставкой в проблемном году
        # даёт максимальный эффект от небольшого уменьшения заказа.
        candidates = []
        for sid in case.sources:
            order = current.order(sid, year)
            if order <= 1e-9:
                continue

            actual_delivery = 0.0
            for result in results.values():
                for row in result.yearly:
                    if row["year"] == year:
                        actual_delivery = max(
                            actual_delivery,
                            float(row["sources"][sid]["actual_delivery"]),
                        )

            if actual_delivery > 1e-9:
                candidates.append((actual_delivery, order, sid))

        if not candidates:
            break

        _, order, sid = max(candidates, key=lambda item: (item[0], item[1]))

        # Для фиксированных остальных заказов storage monotonic по заказу
        # конкретного источника: меньше заказ -> не больше запаса.
        zero_plan = copy.deepcopy(current)
        _set_order(case, zero_plan, sid, year, 0.0)
        zero_results, _ = _evaluate_all(case, zero_plan, scenarios)

        if not _storage_is_feasible(zero_results):
            # Даже полное снятие этого заказа не устраняет overflow:
            # переходим к следующему наиболее влияющему источнику.
            current = zero_plan
            repair_iterations += 1
            continue

        low = 0.0
        high = order

        # Ищем максимальный storage-safe заказ, чтобы не терять лишний
        # физически допустимый запас и не ломать резерв 45 дней.
        for _ in range(20):
            mid = (low + high) / 2.0
            trial = copy.deepcopy(current)
            _set_order(case, trial, sid, year, mid)
            trial_results, _ = _evaluate_all(case, trial, scenarios)

            if _storage_is_feasible(trial_results):
                low = mid
            else:
                high = mid

        repaired = copy.deepcopy(current)
        _set_order(case, repaired, sid, year, low)

        if abs(repaired.order(sid, year) - order) <= 1e-10:
            break

        current = repaired
        repair_iterations += 1

    results, score = _evaluate_all(case, current, scenarios)
    return current, results, score, repair_iterations

def _order_variables(case: Case, plan: Plan) -> List[Tuple[str, int]]:
    variables = []
    for sid in case.sources:
        years = set(plan.orders.get(sid, {}))
        years.update(case.years)
        variables.extend((sid, year) for year in sorted(years))
    return variables


def _local_search(
    case: Case,
    seed: Plan,
    scenarios: Sequence[Scenario],
    config: OptimizerConfig,
) -> Tuple[Plan, Dict[str, Result], Tuple[float, ...], int]:
    """Coordinate descent по годовым заказам."""
    current, results, current_score, repair_iterations = _repair_storage_overflow(
        case, seed, scenarios, config
    )
    iterations = repair_iterations

    for _ in range(config.max_local_search_passes):
        improved = False
        iterations += 1

        for sid, year in _order_variables(case, current):
            source = case.sources[sid]
            res = resolve(case, current)
            frac = res.cal.fraction_available(year, res.avail_day[sid])
            if frac <= 1e-12:
                continue

            max_order = source.capacity * frac
            current_order = current.order(sid, year)
            step = max(
                config.min_step_tons,
                config.step_fraction_of_capacity * max_order,
            )

            trial_orders = {
                max(0.0, min(max_order, current_order - step)),
                max(0.0, min(max_order, current_order + step)),
            }
            trial_orders.discard(current_order)

            best_local_plan = current
            best_local_results = results
            best_local_score = current_score

            for trial_order in sorted(trial_orders):
                trial = copy.deepcopy(current)
                _set_order(case, trial, sid, year, trial_order)
                trial_results, trial_score = _evaluate_all(
                    case, trial, scenarios
                )

                # После достижения физически безопасного состояния
                # нельзя снова принять кандидат с переполнением storage.
                if _storage_is_feasible(results) and not _storage_is_feasible(trial_results):
                    continue

                if trial_score < best_local_score:
                    best_local_plan = trial
                    best_local_results = trial_results
                    best_local_score = trial_score

            if best_local_score < current_score:
                current = best_local_plan
                results = best_local_results
                current_score = best_local_score
                improved = True

        if not improved:
            break

    return current, results, current_score, iterations


def optimize(
    case: Case,
    scenarios: Iterable[Scenario],
    initial_plan: Optional[Plan] = None,
    config: Optional[OptimizerConfig] = None,
) -> OptimizationResult:
    """Найти хороший Plan для заданного набора сценариев.

    Это эвристика: глобальный оптимум математически не гарантируется.
    """
    config = config or OptimizerConfig()
    scenario_list = tuple(scenarios)
    if not scenario_list:
        raise ValueError("Нужно передать хотя бы один сценарий")

    base_plan = copy.deepcopy(initial_plan) if initial_plan is not None else Plan(
        "optimized", name="Heuristic optimizer"
    )

    best_plan: Optional[Plan] = None
    best_results: Optional[Dict[str, Result]] = None
    best_score: Optional[Tuple[float, ...]] = None
    candidates_checked = 0
    total_iterations = 0
    notes: List[str] = []

    for option_ids in _investment_subsets(case, config):
        seed = _with_investments(base_plan, case, option_ids)
        if seed is None:
            continue

        if initial_plan is None:
            seed = _build_greedy_plan(
                case,
                seed,
                scenario_list,
                config.initial_reserve,
            )

        candidate, results, score, iterations = _local_search(
            case, seed, scenario_list, config
        )
        candidates_checked += 1
        total_iterations += iterations

        # Физически некорректный storage-кандидат не попадает в итоговый набор.
        if not _storage_is_feasible(results):
            notes.append(
                f"Кандидат с инвестициями {option_ids} отклонён: "
                "осталось переполнение storage."
            )
            continue

        if best_score is None or score < best_score:
            best_plan = candidate
            best_results = results
            best_score = score

    if best_plan is None or best_results is None or best_score is None:
        raise RuntimeError("Оптимизатор не смог построить ни одного кандидата")

    if all(r.feasible for r in best_results.values()):
        notes.append("Найден план без HARD-нарушений.")
    else:
        notes.append("Лучший найденный план всё ещё содержит HARD-нарушения.")

    notes.append("Метод эвристический; глобальный оптимум не гарантируется.")

    return OptimizationResult(
        plan=best_plan,
        scenario_results=best_results,
        score=best_score,
        candidates_checked=candidates_checked,
        iterations=total_iterations,
        notes=notes,
    )


def optimize_one(
    case: Case,
    scenario: Scenario,
    initial_plan: Optional[Plan] = None,
    config: Optional[OptimizerConfig] = None,
) -> OptimizationResult:
    """Удобная обёртка для одного сценария."""
    return optimize(
        case,
        [scenario],
        initial_plan=initial_plan,
        config=config,
    )


__all__ = [
    "OptimizerConfig",
    "OptimizationResult",
    "optimize",
    "optimize_one",
]
