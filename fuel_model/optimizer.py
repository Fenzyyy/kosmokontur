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
            # Emergency может иметь отдельный контрактный резерв даже при
            # нулевом фактическом заказе; остальные источники резерв заказа
            # можно безопасно удалить.
            if source_id == case.constraints.emergency_source_id:
                return
            plan.reserved[source_id].pop(year, None)
            if not plan.reserved[source_id]:
                plan.reserved.pop(source_id, None)
        return

    res = resolve(case, plan)
    frac = res.cal.fraction_available(year, res.avail_day[source_id])
    if frac <= 1e-12:
        return

    existing_reserved = plan.reserved.get(source_id, {}).get(year, 0.0)

    if order <= 1e-9:
        # Для Emergency сохраняем отдельно заключённый контрактный резерв.
        if source_id == case.constraints.emergency_source_id:
            return
        if source_id in plan.reserved:
            plan.reserved[source_id].pop(year, None)
            if not plan.reserved[source_id]:
                plan.reserved.pop(source_id, None)
        return

    reserved_for_order = min(source.capacity, order / frac)
    # Изменение фактического Emergency-заказа не должно уменьшать уже
    # заключённый контрактный резерв.
    reserved = max(existing_reserved, reserved_for_order)
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
    """Сформировать физически консервативный стартовый plan.

    Для нескольких сценариев seed строится относительно максимального
    сценарного спроса, но резерв 45 дней при наличии Emergency держится
    как контрактный резерв и не занимает storage. Поэтому начальный seed
    не пытается одновременно хранить запас и покрывать стрессовый спрос.
    """
    plan = copy.deepcopy(base_plan)

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

    # Для оптимизатора без заданного initial_plan контрактный Emergency reserve
    # является явным эквивалентом 45-дневного физического запаса.
    plan.initial_stock = []
    if initial_reserve and case.constraints.emergency_source_id in case.sources:
        eid = case.constraints.emergency_source_id
        emergency = case.sources[eid]
        for year in case.years:
            reserve_required = max(
                demand[year][0] * case.constraints.reserve_days / 365.0
                for demand in demand_by_scenario.values()
            )
            res = resolve(case, plan)
            frac = res.cal.fraction_available(year, res.avail_day[eid])
            reserve_limit = emergency.capacity * frac
            reserve = min(reserve_required, reserve_limit)
            if reserve > 1e-9:
                plan.reserved.setdefault(eid, {})[year] = reserve

    # Worst-case inventory is tracked against the maximum annual demand and
    # the weakest delivery share of each channel.
    inventory = 0.0

    for year in case.years:
        total_demand = max(
            demand[year][0] for demand in demand_by_scenario.values()
        )

        res = resolve(case, plan)
        # Use the storage mode active at the beginning of the year.
        mode = case.storage[res.storage_mode_at(res.cal.day(year))]
        loss_rate = mode.loss_rate

        # No target closing reserve is added here: the 45-day requirement is
        # already represented by the explicit Emergency reserve contract.
        gross_need = max(
            0.0,
            total_demand - inventory,
        )
        if loss_rate < 1.0 - 1e-12:
            gross_need /= max(1e-12, 1.0 - loss_rate)

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
            if min_share <= 1e-12:
                continue

            max_order = source.capacity * frac
            max_actual_worst = max_order * min_share
            rank = (
                (source.variable_cost + source.reservation_rate) / min_share
            )
            available.append(
                (rank, _source_rank(case, sid), sid, max_order, max_actual_worst)
            )

        available.sort(key=lambda x: (x[0], x[1]))

        need = gross_need
        actual_delivery = 0.0

        for _, _, sid, max_order, max_actual_worst in available:
            if need <= 1e-9:
                break

            source = case.sources[sid]
            min_share = min(
                scenario.delivery_share.get((sid, year), 1.0)
                for scenario in scenario_list
            )
            actual_need = min(need, max_actual_worst)
            order = min(max_order, actual_need / max(min_share, 1e-12))
            if order <= 1e-9:
                continue

            _set_order(case, plan, sid, year, order)
            actual = order * min_share
            actual_delivery += actual
            need -= actual

        inventory = max(
            0.0,
            inventory + actual_delivery * (1.0 - loss_rate) - total_demand,
        )

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
            max(0.0, row["reserve_required"] - row.get("reserve_covered", row["reserve_stock_at_check"]))
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



def _reserve_is_feasible_for_year(
    results: Mapping[str, Result],
    year: int,
) -> bool:
    """Проверить резерв только в одном году."""
    for result in results.values():
        for row in result.yearly:
            if row["year"] != year:
                continue
            if row.get("reserve_covered", row["reserve_stock_at_check"]) + 1e-8 < row["reserve_required"]:
                return False
    return True


def _reserve_is_feasible(results: Mapping[str, Result]) -> bool:
    """Проверить физический 45-дневный резерв во всех сценариях."""
    return not any(
        v.code == "RESERVE_45D_SHORT" and v.severity == "HARD"
        for result in results.values()
        for v in result.violations
    )


def _free_storage_before_year(
    case: Case,
    plan: Plan,
    scenarios: Sequence[Scenario],
    year: int,
) -> Tuple[Plan, bool]:
    """Уменьшить избыточные поставки прошлого года, если это не ухудшает
    уже достигнутую обеспеченность и резерв.
    """
    if year <= case.first_year:
        return plan, False

    prev_year = year - 1
    base_results, _ = _evaluate_all(case, plan, scenarios)
    base_shortage = sum(
        result.kpis["shortage_total"] for result in base_results.values()
    )

    candidates = []
    for sid, source in case.sources.items():
        current_order = plan.order(sid, prev_year)
        if current_order <= 1e-9:
            continue

        trial = copy.deepcopy(plan)
        _set_order(case, trial, sid, prev_year, 0.0)
        trial_results, _ = _evaluate_all(case, trial, scenarios)

        trial_shortage = sum(
            result.kpis["shortage_total"]
            for result in trial_results.values()
        )
        if (
            trial_shortage <= base_shortage + 1e-8
            and _reserve_is_feasible(trial_results)
            and _storage_is_feasible(trial_results)
        ):
            candidates.append((
                current_order,
                sid,
                trial,
                trial_results,
            ))
            continue

        # Ищем минимально необходимый остаточный заказ прошлого года.
        lo = 0.0
        hi = current_order
        best_trial = None
        best_results = None

        for _ in range(10):
            mid = (lo + hi) / 2.0
            candidate = copy.deepcopy(plan)
            _set_order(case, candidate, sid, prev_year, mid)
            candidate_results, _ = _evaluate_all(
                case, candidate, scenarios
            )

            candidate_shortage = sum(
                result.kpis["shortage_total"]
                for result in candidate_results.values()
            )
            if (
                candidate_shortage <= base_shortage + 1e-8
                and _reserve_is_feasible(candidate_results)
                and _storage_is_feasible(candidate_results)
            ):
                hi = mid
                best_trial = candidate
                best_results = candidate_results
            else:
                lo = mid

        if best_trial is not None:
            freed = current_order - hi
            if freed > 1e-6:
                candidates.append((
                    freed,
                    sid,
                    best_trial,
                    best_results,
                ))

    if not candidates:
        return plan, False

    _, _, best_plan, _ = max(
        candidates,
        key=lambda x: (x[0], x[1]),
    )
    return best_plan, True


def _repair_service_shortage(
    case: Case,
    seed: Plan,
    scenarios: Sequence[Scenario],
    config: OptimizerConfig,
) -> Tuple[Plan, Dict[str, Result], Tuple[float, ...], int]:
    """Добрать поставки до нулевого дефицита во всех заданных сценариях.

    Это отдельный feasibility-repair: каждый кандидат проверяется полным
    суточным engine, поэтому увеличение заказа допускается только если
    одновременно сохраняется физическая ёмкость storage.
    """
    current = copy.deepcopy(seed)
    iterations = 0
    diagnostics: List[str] = []
    max_repairs = max(1, len(case.years) * len(case.sources) * 3)

    def year_shortage(results: Mapping[str, Result], year: int) -> float:
        return sum(
            row["shortage_total"]
            for result in results.values()
            for row in result.yearly
            if row["year"] == year
        )

    for _ in range(max_repairs):
        results, score = _evaluate_all(case, current, scenarios)
        total_shortage = sum(
            result.kpis["shortage_total"] for result in results.values()
        )
        if total_shortage <= 1e-8:
            return current, results, score, iterations

        base_result = results.get("BASE")
        if base_result is not None:
            base_shortages = {
                row["year"]: row["shortage_total"]
                for row in base_result.yearly
            }
            worst_base_year = max(
                base_shortages,
                key=base_shortages.get,
            )
            if base_shortages[worst_base_year] > 1e-8:
                worst_year = worst_base_year
            else:
                worst_year = max(
                    case.years,
                    key=lambda y: year_shortage(results, y),
                )
        else:
            worst_year = max(
                case.years,
                key=lambda y: year_shortage(results, y),
            )

        current_year_shortage = year_shortage(results, worst_year)

        candidates = []
        resolved = resolve(case, current)

        for sid, source in case.sources.items():
            frac = resolved.cal.fraction_available(
                worst_year, resolved.avail_day[sid]
            )
            if frac <= 1e-12:
                continue

            current_order = current.order(sid, worst_year)
            max_order = source.capacity * frac
            room = max(0.0, max_order - current_order)
            if room <= 1e-9:
                continue

            # Ищем максимальную storage-safe добавку.
            safe_hi = room
            safe_trial = None
            safe_results = None
            for _ in range(8):
                trial = copy.deepcopy(current)
                _set_order(
                    case,
                    trial,
                    sid,
                    worst_year,
                    current_order + safe_hi,
                )
                trial_results, trial_score = _evaluate_all(
                    case, trial, scenarios
                )
                if _storage_is_feasible(trial_results):
                    safe_trial = trial
                    safe_results = trial_results
                    break
                safe_hi *= 0.5

            if safe_trial is None or safe_results is None or safe_hi <= 1e-9:
                continue

            gain = current_year_shortage - year_shortage(
                safe_results, worst_year
            )
            if gain <= 1e-8:
                continue

            cost = source.variable_cost + source.reservation_rate
            candidates.append((
                gain / safe_hi,
                gain,
                -cost,
                sid,
                safe_trial,
                safe_results,
                trial_score,
            ))

        if not candidates:
            freed_plan, freed = _free_storage_before_year(
                case, current, scenarios, worst_year
            )
            if freed:
                current = freed_plan
                iterations += 1
                continue

            diagnostics.append(
                f"service repair stalled at {worst_year}; "
                f"shortage={current_year_shortage:.2f}t"
            )
            break

        _, _, _, _, current, results, score = max(
            candidates,
            key=lambda item: (item[0], item[1], item[2], item[3]),
        )
        iterations += 1

    if diagnostics:
        current.notes = (current.notes + " " + " ".join(diagnostics)).strip()

    results, score = _evaluate_all(case, current, scenarios)
    return current, results, score, iterations


def _set_emergency_reserve(
    case: Case,
    plan: Plan,
    year: int,
    additional_tons: float,
) -> float:
    """Добавить контрактный Emergency reserve без физического поступления."""
    if additional_tons <= 1e-9:
        return 0.0

    eid = case.constraints.emergency_source_id
    if eid not in case.sources:
        return 0.0

    source = case.sources[eid]
    res = resolve(case, plan)
    frac = res.cal.fraction_available(year, res.avail_day[eid])
    if frac <= 1e-12:
        return 0.0

    limit = source.capacity * frac
    current_reserved = plan.reserved_capacity(source, year)
    add = min(
        float(additional_tons),
        max(0.0, limit - current_reserved),
    )
    if add <= 1e-9:
        return 0.0

    plan.reserved.setdefault(eid, {})[year] = current_reserved + add
    return add


def _repair_reserve(
    case: Case,
    seed: Plan,
    scenarios: Sequence[Scenario],
    config: OptimizerConfig,
) -> Tuple[Plan, Dict[str, Result], Tuple[float, ...], int]:
    """Добрать 45-дневный физический резерв минимальным увеличением поставок.

    Резерв на 1 января года y формируется запасом на конец y-1.
    Поэтому для y>first_year увеличиваем поставки предыдущего года.
    Для первого года корректируем initial_stock, не допуская превышения
    базовой ёмкости.
    """
    current = copy.deepcopy(seed)
    iterations = 0
    diagnostics: List[str] = []
    max_repairs = max(1, len(case.years) * 4)

    for _ in range(max_repairs):
        results, score = _evaluate_all(case, current, scenarios)
        if _reserve_is_feasible(results):
            return current, results, score, iterations

        # Сначала используем допустимый контрактный Emergency reserve.
        # Он не занимает физическое хранилище и потому является первым
        # способом устранить недобор 45-дневного резерва.
        contract_shortages = []
        for result in results.values():
            for row in result.yearly:
                gap = max(
                    0.0,
                    row["reserve_required"]
                    - row.get("reserve_covered", row["reserve_stock_at_check"]),
                )
                if gap > 1e-8:
                    contract_shortages.append((gap, row["year"]))
        if contract_shortages:
            _, contract_year = max(
                contract_shortages,
                key=lambda x: (x[0], -x[1]),
            )
            gap = max(
                gap
                for result in results.values()
                for row in result.yearly
                if row["year"] == contract_year
                for gap in [
                    max(
                        0.0,
                        row["reserve_required"]
                        - row.get("reserve_covered", row["reserve_stock_at_check"]),
                    )
                ]
            )
            trial = copy.deepcopy(current)
            added = _set_emergency_reserve(
                case, trial, contract_year, gap
            )
            if added > 1e-9:
                trial_results, trial_score = _evaluate_all(
                    case, trial, scenarios
                )
                if _storage_is_feasible(trial_results):
                    current = trial
                    iterations += 1
                    if _reserve_is_feasible(trial_results):
                        return current, trial_results, trial_score, iterations
                    results, score = trial_results, trial_score
                    continue

        # Берём первый год с максимальным физическим недобором.
        shortages = []
        for result in results.values():
            for row in result.yearly:
                gap = max(
                    0.0,
                    row["reserve_required"]
                    - row.get("reserve_covered", row["reserve_stock_at_check"])
                )
                if gap > 1e-8:
                    shortages.append((gap, row["year"], result.meta["scenario_id"]))

        if not shortages:
            return current, results, score, iterations

        _, year, _ = max(shortages, key=lambda x: (x[0], -x[1]))

        if year == case.first_year:
            required = max(
                case.demand_series(
                    scenario.demand_variant,
                    scenario.demand_multiplier,
                )[year][0]
                * case.constraints.reserve_days
                / 365.0
                for scenario in scenarios
            )
            capacity = case.storage[case.base_storage_id].capacity
            current_total = sum(lot.tons for lot in current.initial_stock)
            target = min(required, capacity)

            if target <= current_total + 1e-9:
                break

            # Расширяем уже существующие/доступные initial-stock lots.
            res = resolve(case, current)
            candidates = []
            for sid, source in case.sources.items():
                avail = res.avail_day[sid]
                if avail is not None and avail <= 0:
                    candidates.append((source.variable_cost + source.reservation_rate, sid))

            candidates.sort()
            added = target - current_total
            for _, sid in candidates:
                room = max(0.0, case.sources[sid].capacity -
                           sum(l.tons for l in current.initial_stock if l.source_id == sid))
                take = min(added, room)
                if take <= 1e-9:
                    continue
                current.initial_stock.append(InitialStockLot(sid, take))
                added -= take
                if added <= 1e-9:
                    break

            iterations += 1
            continue

        repaired = False

        # Если в непосредственном предшествующем году нельзя добавить
        # физически безопасный объём, пробуем строить резерв ещё раньше.
        for build_year in range(year - 1, case.first_year - 1, -1):
            res = resolve(case, current)
            source_candidates = []
            for sid, source in case.sources.items():
                frac = res.cal.fraction_available(
                    build_year, res.avail_day[sid]
                )
                current_order = current.order(sid, build_year)
                max_order = source.capacity * frac
                room = max(0.0, max_order - current_order)
                if frac > 1e-12 and room > 1e-9:
                    source_candidates.append(
                        (
                            source.variable_cost + source.reservation_rate,
                            sid,
                            room,
                        )
                    )

            source_candidates.sort(key=lambda x: (x[0], x[1]))

            # Текущий максимальный недобор именно для target year.
            current_gap = max(
                max(
                    0.0,
                    row["reserve_required"]
                    - row.get("reserve_covered", row["reserve_stock_at_check"]),
                )
                for result in results.values()
                for row in result.yearly
                if row["year"] == year
            )

            for _, sid, room in source_candidates:
                current_order = current.order(sid, build_year)

                safe_hi = room
                safe_trial = None
                safe_results = None

                # Находим положительную storage-safe добавку.
                for _ in range(8):
                    trial = copy.deepcopy(current)
                    _set_order(
                        case,
                        trial,
                        sid,
                        build_year,
                        current_order + safe_hi,
                    )
                    candidate_results, _ = _evaluate_all(
                        case, trial, scenarios
                    )
                    if _storage_is_feasible(candidate_results):
                        safe_trial = trial
                        safe_results = candidate_results
                        break
                    safe_hi *= 0.5

                if (
                    safe_trial is None
                    or safe_results is None
                    or safe_hi <= 1e-9
                ):
                    continue

                after_gap = max(
                    max(
                        0.0,
                        row["reserve_required"]
                        - row.get("reserve_covered", row["reserve_stock_at_check"]),
                    )
                    for result in safe_results.values()
                    for row in result.yearly
                    if row["year"] == year
                )

                # Этот год/канал не помогает сформировать target reserve.
                if after_gap >= current_gap - 1e-8:
                    continue

                if after_gap <= 1e-8:
                    # Можно найти минимальную добавку, закрывающую резерв.
                    lo = 0.0
                    hi = safe_hi
                    for _ in range(10):
                        mid = (lo + hi) / 2.0
                        trial = copy.deepcopy(current)
                        _set_order(
                            case,
                            trial,
                            sid,
                            build_year,
                            current_order + mid,
                        )
                        trial_results, _ = _evaluate_all(
                            case, trial, scenarios
                        )
                        if (
                            _reserve_is_feasible_for_year(
                                trial_results, year
                            )
                            and _storage_is_feasible(trial_results)
                        ):
                            hi = mid
                        else:
                            lo = mid

                    trial = copy.deepcopy(current)
                    _set_order(
                        case,
                        trial,
                        sid,
                        build_year,
                        current_order + hi,
                    )
                    trial_results, _ = _evaluate_all(
                        case, trial, scenarios
                    )
                    if (
                        _reserve_is_feasible_for_year(trial_results, year)
                        and _storage_is_feasible(trial_results)
                    ):
                        current = trial
                        iterations += 1
                        repaired = True
                        break
                else:
                    # Один канал/год не закрывает весь недобор, но даёт
                    # максимально допустимый физический вклад. Остаток
                    # будет добран следующей итерацией.
                    current = safe_trial
                    iterations += 1
                    repaired = True
                    break

            if repaired:
                break

        if not repaired:
            remaining = []
            for result in results.values():
                for row in result.yearly:
                    gap = max(
                        0.0,
                        row["reserve_required"]
                    - row.get("reserve_covered", row["reserve_stock_at_check"]),
                    )
                    if gap > 1e-8:
                        remaining.append(
                            f"{result.meta['scenario_id']}:{row['year']}={gap:.2f}t"
                        )
            order_state = "; ".join(
                f"{sid}:{build_year}={current.order(sid, build_year):.1f}"
                for sid in case.sources
                for build_year in case.years
                if build_year <= year
            )
            diagnostics.append(
                f"reserve repair stalled at year {year}; "
                f"remaining={', '.join(remaining[:10])}; "
                f"orders={order_state}"
            )
            break

    if diagnostics:
        suffix = " ".join(diagnostics)
        current.notes = (current.notes + " " + suffix).strip()

    results, score = _evaluate_all(case, current, scenarios)
    return current, results, score, iterations


def _investment_subset_can_meet_loss_ceilings(
    case: Case,
    option_ids: Sequence[str],
    scenarios: Sequence[Scenario],
) -> bool:
    """Дешёвый precheck: storage loss ceiling не должен быть заведомо недостижим."""
    selected_storage_modes = {case.base_storage_id}
    for oid in option_ids:
        option = case.options[oid]
        if option.kind == "storage" and option.target_id in case.storage:
            selected_storage_modes.add(option.target_id)

    best_loss_rate = min(case.storage[mid].loss_rate for mid in selected_storage_modes)

    for scenario in scenarios:
        for ceiling in scenario.loss_ceiling.values():
            if best_loss_rate > ceiling + 1e-12:
                return False
    return True


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
    max_repairs = max(1, len(case.years) * 3)

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
    current, results, current_score, reserve_iterations = _repair_reserve(
        case, seed, scenarios, config
    )
    current, results, current_score, storage_iterations = _repair_storage_overflow(
        case, current, scenarios, config
    )
    # После storage-repair повторно восстанавливаем только тот резерв,
    # который был потерян из-за физического ограничения ёмкости.
    current, results, current_score, reserve_repair_iterations = _repair_reserve(
        case, current, scenarios, config
    )
    current, results, current_score, service_iterations = _repair_service_shortage(
        case, current, scenarios, config
    )
    iterations = (
        reserve_iterations
        + storage_iterations
        + reserve_repair_iterations
        + service_iterations
    )

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

    current, results, current_score, final_service_iterations = _repair_service_shortage(
        case, current, scenarios, config
    )
    iterations += final_service_iterations

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
        if not _investment_subset_can_meet_loss_ceilings(
            case, option_ids, scenario_list
        ):
            notes.append(
                f"Кандидат с инвестициями {option_ids} отклонён: "
                "storage loss ceiling заведомо недостижим."
            )
            continue

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

        if not _reserve_is_feasible(results):
            reserve_gaps = []
            for scenario_id, scenario_result in results.items():
                for row in scenario_result.yearly:
                    gap = max(
                        0.0,
                        row["reserve_required"] - row["reserve_stock_at_check"],
                    )
                    if gap > 1e-8:
                        reserve_gaps.append(
                            f"{scenario_id}:{row['year']} gap={gap:.2f}t"
                        )
            notes.append(
                f"Кандидат с инвестициями {option_ids} отклонён: "
                "не выполнен 45-дневный физический резерв "
                f"({', '.join(reserve_gaps[:8])}). "
                f"{candidate.notes or ''}"
            )
            continue

        if best_score is None or score < best_score:
            best_plan = candidate
            best_results = results
            best_score = score

    if best_plan is None or best_results is None or best_score is None:
        diagnostic = " | ".join(notes[-12:]) if notes else "нет диагностических сообщений"
        raise RuntimeError(
            "Оптимизатор не смог построить ни одного кандидата. "
            f"Диагностика: {diagnostic}"
        )

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
