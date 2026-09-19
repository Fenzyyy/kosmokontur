"""Структуры данных: Case (данные организатора), Plan (решения команды), Scenario, Result.

Статусы параметров (см. README репозитория организатора):
  CASE_INPUT      — то, что задал организатор: Case, BASE и MANDATORY_STRESS;
  TEAM_DECISION   — решения оператора: Plan;
  TEAM_ASSUMPTION — наши допущения: Assumptions и configs/source_roles.json.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Mapping, Optional, Tuple

from .calendar import fmt_ym, parse_ym
from .errors import Violation

# ---------------------------------------------------------------------------------
# CASE_INPUT
# ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class DemandRow:
    year: int
    base_total: float
    base_critical: float
    low_total: float
    high_total: float


@dataclass(frozen=True)
class Source:
    source_id: str
    name: str
    capacity: float                 # т/год, максимальная мощность канала
    variable_cost: float            # млн у.е./т (включает доставку в узел)
    reservation_rate: float         # млн у.е. за 1 т/год зарезервированной мощности
    top_share: float                # take-or-pay: доля зарезервированного объёма периода
    lead_time_min: float
    lead_time_max: float
    lead_time_unit: str             # day | week | month | year
    reliability_profile: str = ""   # метаданные: в BASE как множитель НЕ используются
    available_from_year: Optional[int] = None
    status: str = ""
    notes: str = ""


@dataclass(frozen=True)
class SourceRole:
    """Как именно трактуется lead time источника (наше моделирующее соглашение).

    order              — срок от заказа до поставки: решения принимаются в момент t0 (начало подготовительного периода);
    build              — срок подготовки/ввода: источник доступен с даты ввода инвестиции (Earth-New);
    post_commissioning — задержка после ввода: поставки начинаются через lead time после ввода (Lunar-ISRU).
    """
    requires_option: str = ""
    lead_time_semantics: str = "order"


@dataclass(frozen=True)
class StorageMode:
    mode_id: str
    name: str
    capacity: float                 # т
    loss_rate: float                # доля от валового поступления (throughput)
    holding_cost: float             # млн у.е./т-год
    capex: float = 0.0
    fixed_opex: float = 0.0         # млн у.е./год


@dataclass(frozen=True)
class InvestmentOption:
    option_id: str
    kind: str                       # storage | source
    target_id: str                  # mode_id хранилища или source_id
    stage_labels: Tuple[str, ...]
    stage_amounts: Tuple[float, ...]        # CAPEX по этапам, млн у.е.
    fixed_opex: float = 0.0                 # млн у.е./год после ввода
    earliest_stage_year: Optional[int] = None
    latest_capex_year: Optional[int] = None         # последний год вложений
    earliest_in_service_year: Optional[int] = None
    min_build_months: float = 0.0           # мин. срок от последнего вложения до ввода
    max_build_months: float = 0.0
    notes: str = ""

    @property
    def total_capex(self) -> float:
        return float(sum(self.stage_amounts))


@dataclass(frozen=True)
class Constraints:
    sl_total_min: float = 0.97
    sl_critical_min: float = 0.99
    capex_cumulative_year: int = 2037
    capex_cumulative_limit: float = 1800.0
    capex_total_limit: float = 2800.0
    reserve_days: float = 45.0
    emergency_source_id: str = "E"
    emergency_max_consecutive_years: int = 2


@dataclass(frozen=True)
class Assumptions:
    """TEAM_ASSUMPTION: допущения, которых нет в исходнике. Значения по умолчанию — заглушки, их нужно обосновать."""
    discount_rate: float = 0.05             # реальная ставка (ПЛЕЙСХОЛДЕР: аналитик обосновывает)
    discount_base_year: Optional[int] = None    # None -> первый год горизонта; поток года y приводится как (1+r)^-(y-t0)
    prep_months: float = 12.0               # длительность подготовительного периода до горизонта
    lead_time_choice: str = "max"           # min | max: какую границу диапазона lead time принимать
    reserve_check_after_first_delivery: bool = False   # False: запас на начало года берётся до поставок 1 января
    emergency_used_threshold_t: float = 0.0  # заказ Emergency выше порога = «плановое использование» в этом году


@dataclass
class Case:
    demand: Dict[int, DemandRow]
    sources: Dict[str, Source]
    storage: Dict[str, StorageMode]
    options: Dict[str, InvestmentOption]
    constraints: Constraints = field(default_factory=Constraints)
    source_roles: Dict[str, SourceRole] = field(default_factory=dict)
    assumptions: Assumptions = field(default_factory=Assumptions)
    base_storage_id: str = "BASE_STORAGE"

    @property
    def years(self) -> List[int]:
        return sorted(self.demand)

    @property
    def first_year(self) -> int:
        return self.years[0]

    @property
    def last_year(self) -> int:
        return self.years[-1]

    def role(self, source_id: str) -> SourceRole:
        return self.source_roles.get(source_id, SourceRole())

    def demand_series(self, variant: str = "base",
                      multiplier: Optional[Mapping[int, float]] = None) -> Dict[int, Tuple[float, float]]:
        """(общий, критический) спрос по годам.

        Для low/high критический спрос пропорционален изменению общего (доля критического сохраняется).
        multiplier — множители сценария (в обязательном стрессе 1.15 с 2038 года).
        """
        if variant not in ("base", "low", "high"):
            raise ValueError(f"demand_variant должен быть base/low/high, получено {variant!r}")
        out: Dict[int, Tuple[float, float]] = {}
        for y in self.years:
            r = self.demand[y]
            total = {"base": r.base_total, "low": r.low_total, "high": r.high_total}[variant]
            crit = r.base_critical * (total / r.base_total) if r.base_total else 0.0
            m = 1.0 if not multiplier else multiplier.get(y, 1.0)
            out[y] = (total * m, crit * m)
        return out

    def to_dict(self) -> dict:
        return {
            "demand": [asdict(self.demand[y]) for y in self.years],
            "sources": [asdict(s) for s in self.sources.values()],
            "storage": [asdict(s) for s in self.storage.values()],
            "options": [asdict(o) for o in self.options.values()],
            "constraints": asdict(self.constraints),
            "source_roles": {k: asdict(v) for k, v in self.source_roles.items()},
            "assumptions": asdict(self.assumptions),
            "base_storage_id": self.base_storage_id,
        }


# ---------------------------------------------------------------------------------
# TEAM_DECISION
# ---------------------------------------------------------------------------------

YM = Tuple[int, int]


@dataclass(frozen=True)
class InitialStockLot:
    source_id: str
    tons: float


@dataclass(frozen=True)
class InvestmentDecision:
    stage_dates: Tuple[YM, ...]     # (год, месяц) платежа по каждому этапу CAPEX
    in_service: YM                  # (год, месяц) ввода в эксплуатацию


@dataclass
class Plan:
    plan_id: str
    name: str = ""
    orders: Dict[str, Dict[int, float]] = field(default_factory=dict)      # канал -> год -> заказанный объём, т
    reserved: Dict[str, Dict[int, float]] = field(default_factory=dict)    # канал -> год -> резерв мощности, т/год
    initial_stock: List[InitialStockLot] = field(default_factory=list)
    investments: Dict[str, InvestmentDecision] = field(default_factory=dict)
    notes: str = ""

    def order(self, source_id: str, year: int) -> float:
        return float(self.orders.get(source_id, {}).get(year, 0.0))

    def reserved_capacity(self, source: Source, year: int) -> float:
        """Вернуть контрактный резерв с учётом семантики источника."""
        if source.reservation_rate == 0 and source.top_share == 0:
            # Для каналов без reservation / take-or-pay резерв не является
            # отдельным решением и всегда равен полной доступной мощности.
            return float(source.capacity)

        given = self.reserved.get(source.source_id, {})
        if year in given:
            return float(given[year])
        return 0.0

    # --- сериализация (JSON: сохранение и повторное открытие плана)
    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id, "name": self.name, "notes": self.notes,
            "initial_stock": [{"source": l.source_id, "tons": l.tons} for l in self.initial_stock],
            "orders": {s: {str(y): v for y, v in sorted(d.items())} for s, d in self.orders.items()},
            "reserved": {s: {str(y): v for y, v in sorted(d.items())} for s, d in self.reserved.items()},
            "investments": {
                k: {"stage_dates": [fmt_ym(d) for d in v.stage_dates], "in_service": fmt_ym(v.in_service)}
                for k, v in self.investments.items()
            },
        }

    @staticmethod
    def from_dict(d: dict) -> "Plan":
        return Plan(
            plan_id=str(d.get("plan_id", "plan")),
            name=str(d.get("name", "")),
            notes=str(d.get("notes", "")),
            initial_stock=[InitialStockLot(str(l["source"]), float(l["tons"])) for l in d.get("initial_stock", [])],
            orders={s: {int(y): float(v) for y, v in yv.items()} for s, yv in d.get("orders", {}).items()},
            reserved={s: {int(y): float(v) for y, v in yv.items()} for s, yv in d.get("reserved", {}).items()},
            investments={
                k: InvestmentDecision(tuple(parse_ym(x) for x in v["stage_dates"]), parse_ym(v["in_service"]))
                for k, v in d.get("investments", {}).items()
            },
        )

    @staticmethod
    def load(path: str) -> "Plan":
        with open(path, encoding="utf-8") as fh:
            return Plan.from_dict(json.load(fh))

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------------
# Scenario
# ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    """Сценарий = набор наложений на копию кейса. Исходные данные не изменяются."""
    scenario_id: str
    name: str
    description: str = ""
    kind: str = "control"                       # control | overlay | research
    demand_variant: str = "base"                # base | low | high
    demand_multiplier: Mapping[int, float] = field(default_factory=dict)
    price_multiplier: Mapping[Tuple[str, int], float] = field(default_factory=dict)
    delivery_share: Mapping[Tuple[str, int], float] = field(default_factory=dict)
    loss_ceiling: Mapping[int, float] = field(default_factory=dict)
    sl_is_benchmark: bool = False               # BASE: требования 97/99% обязательны; стресс: ориентиры
    changes: Tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id, "name": self.name, "description": self.description, "kind": self.kind,
            "demand_variant": self.demand_variant,
            "demand_multiplier": {str(k): v for k, v in sorted(self.demand_multiplier.items())},
            "price_multiplier": {f"{s}:{y}": v for (s, y), v in sorted(self.price_multiplier.items())},
            "delivery_share": {f"{s}:{y}": v for (s, y), v in sorted(self.delivery_share.items())},
            "loss_ceiling": {str(k): v for k, v in sorted(self.loss_ceiling.items())},
            "sl_is_benchmark": self.sl_is_benchmark, "changes": list(self.changes),
        }

    @staticmethod
    def from_dict(d: dict) -> "Scenario":
        def sy(dd):
            out = {}
            for k, v in dd.items():
                s, y = k.split(":")
                out[(s, int(y))] = float(v)
            return out
        return Scenario(
            scenario_id=d["scenario_id"], name=d.get("name", d["scenario_id"]), description=d.get("description", ""),
            kind=d.get("kind", "research"), demand_variant=d.get("demand_variant", "base"),
            demand_multiplier={int(k): float(v) for k, v in d.get("demand_multiplier", {}).items()},
            price_multiplier=sy(d.get("price_multiplier", {})), delivery_share=sy(d.get("delivery_share", {})),
            loss_ceiling={int(k): float(v) for k, v in d.get("loss_ceiling", {}).items()},
            sl_is_benchmark=bool(d.get("sl_is_benchmark", False)), changes=tuple(d.get("changes", [])),
        )


# ---------------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------------


@dataclass
class Result:
    meta: dict
    yearly: List[dict]                  # физика по годам
    costs: List[dict]                   # затраты по годам (млн у.е.)
    kpis: dict
    violations: List[Violation]
    inventory_trace: List[dict] = field(default_factory=list)   # суточная траектория запаса
    supply_schedule: List[dict] = field(default_factory=list)   # поставки по каналам и датам

    @property
    def hard_violations(self) -> List[Violation]:
        return [v for v in self.violations if v.severity == "HARD"]

    @property
    def feasible(self) -> bool:
        return not self.hard_violations

    def to_dict(self, include_trace: bool = False) -> dict:
        d = {
            "meta": self.meta, "feasible": self.feasible, "yearly": self.yearly, "costs": self.costs,
            "kpis": self.kpis, "violations": [v.to_dict() for v in self.violations],
            "supply_schedule": self.supply_schedule,
        }
        if include_trace:
            d["inventory_trace"] = self.inventory_trace
        return d
