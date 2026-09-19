"""Контрольный запуск минимального двигателя v0.

Запускать из директории, где лежит пакет fuel_model:
    python -m fuel_model.main

Файл создаёт маленький синтетический однолетний кейс, запускает simulate()
и печатает результат в удобном для первичной проверки виде.
"""
from __future__ import annotations

from typing import Iterable

from .engine import simulate
from .model import (
    Case,
    DemandRow,
    InitialStockLot,
    Plan,
    Scenario,
    Source,
    StorageMode,
)


def build_demo_case() -> Case:
    """Минимальный однолетний CASE для проверки физики v0.

    Сценарий:
    - 2035 год;
    - общий спрос: 390 т/год;
    - критический спрос: 100 т/год;
    - начальный запас: 50 т;
    - три канала A/B/C по 120 т/год;
    - потери хранения: 1% от валового поступления.
    """
    demand = {
        2035: DemandRow(
            year=2035,
            base_total=390.0,
            base_critical=100.0,
            low_total=350.0,
            high_total=430.0,
        )
    }

    sources = {
        source_id: Source(
            source_id=source_id,
            name=f"Канал {source_id}",
            capacity=120.0,
            variable_cost=1.0,
            reservation_rate=0.0,
            top_share=0.0,
            lead_time_min=0.0,
            lead_time_max=0.0,
            lead_time_unit="day",
            available_from_year=2035,
        )
        for source_id in ("A", "B", "C")
    }

    storage = {
        "BASE_STORAGE": StorageMode(
            mode_id="BASE_STORAGE",
            name="Базовое хранилище",
            capacity=100.0,
            loss_rate=0.01,
            holding_cost=0.0,
        )
    }

    return Case(
        demand=demand,
        sources=sources,
        storage=storage,
        options={},
        base_storage_id="BASE_STORAGE",
    )


def build_demo_plan() -> Plan:
    """План, который должен покрыть 390 т базового спроса."""
    return Plan(
        plan_id="demo_base",
        name="Контрольный план v0",
        orders={
            "A": {2035: 120.0},
            "B": {2035: 120.0},
            "C": {2035: 120.0},
        },
        # Для каналов с reservation_rate=0 и top_share=0
        # Plan автоматически считает резерв равным мощности канала.
        initial_stock=[
            InitialStockLot(source_id="A", tons=50.0),
        ],
    )


def print_mapping(title: str, values: dict[str, object]) -> None:
    print(f"\n{title}")
    print("-" * len(title))
    for key, value in values.items():
        if isinstance(value, float):
            print(f"{key:24s}: {value:.6f}")
        else:
            print(f"{key:24s}: {value}")


def print_yearly(result) -> None:
    print("\nYEARLY")
    print("------")
    for row in result.yearly:
        print(
            f"{row['year']}: "
            f"opening={row['opening_inventory']:.3f} t, "
            f"delivered={row['delivered']:.3f} t, "
            f"losses={row['losses']:.3f} t, "
            f"served={row['served_total']:.3f} t, "
            f"shortage={row['shortage_total']:.3f} t, "
            f"closing={row['closing_inventory']:.3f} t, "
            f"SL={row['service_level_total']:.3%}"
        )


def print_violations(violations: Iterable) -> None:
    print("\nVIOLATIONS")
    print("----------")
    violations = list(violations)
    if not violations:
        print("Нет нарушений.")
        return

    for violation in violations:
        print(
            f"[{violation.severity}] {violation.code} | "
            f"year={violation.year} | subject={violation.subject} | "
            f"value={violation.value} | limit={violation.limit}"
        )
        print(f"  {violation.message}")


def print_trace_head(result, n: int = 5) -> None:
    print(f"\nINVENTORY TRACE — первые {n} дней")
    print("--------------------------------")
    for row in result.inventory_trace[:n]:
        print(
            f"{row['date']}: "
            f"I_open={row['opening_inventory']:.3f}, "
            f"delivery={row['delivered']:.3f}, "
            f"loss={row['losses']:.3f}, "
            f"demand={row['demand_total']:.3f}, "
            f"served={row['served_total']:.3f}, "
            f"I_close={row['closing_inventory']:.3f}"
        )


def main() -> None:
    case = build_demo_case()
    plan = build_demo_plan()
    scenario = Scenario(
        scenario_id="BASE",
        name="BASE",
        kind="control",
    )

    result = simulate(case, plan, scenario)

    print("=" * 60)
    print("FUEL MODEL — CONTROL RUN v0")
    print("=" * 60)
    print(f"Scenario : {result.meta['scenario_name']}")
    print(f"Engine   : {result.meta['engine_version']}")
    print(f"Feasible : {result.feasible}")

    print_mapping("KPI", result.kpis)
    print_yearly(result)
    print_violations(result.violations)
    print_trace_head(result)

    print("\nSUPPLY SCHEDULE — первые 6 поставок")
    print("-----------------------------------")
    for row in result.supply_schedule[:6]:
        print(
            f"{row['date']} | {row['source']} | "
            f"planned={row['planned']:.3f} t | "
            f"delivered={row['delivered']:.3f} t"
        )


if __name__ == "__main__":
    main()
