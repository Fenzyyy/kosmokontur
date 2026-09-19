"""Аналитика поверх ядра: сравнение сценариев и одномерная чувствительность.

Аналитика только вызывает evaluate(): своих формул здесь нет.
"""
from __future__ import annotations

from typing import Callable, Dict, Iterable, List

from .engine import evaluate
from .model import Case, Plan, Scenario


def compare_scenarios(case: Case, plan: Plan, scenarios: Iterable[Scenario]) -> List[dict]:
    """Один и тот же план, разные сценарии: единая база для сравнения затрат, обслуживания, запаса и дефицита."""
    rows = []
    for sc in scenarios:
        r = evaluate(case, plan, sc)
        k = r.kpis
        rows.append({"plan_id": plan.plan_id, "scenario_id": sc.scenario_id, "feasible": r.feasible,
                     "total_cost": k["total_cost"], "pv_cost": k["pv_cost"], "capex_total": k["capex_total"],
                     "served_total": k["served_total"], "shortage_total": k["shortage_total"],
                     "shortage_critical": k["shortage_critical"], "min_sl_total": k["min_sl_total"],
                     "min_sl_critical": k["min_sl_critical"], "losses_total": k["losses_total"],
                     "cost_per_served_ton": k["cost_per_served_ton"], "hard_violations": k["hard_violations"],
                     "benchmark_misses": k["benchmark_misses"],
                     "violation_codes": ";".join(sorted({v.code for v in r.violations if v.severity != "WARNING"}))})
    return rows


def sweep(case: Case, plan: Plan, make_scenario: Callable[[float], Scenario], values: Iterable[float]) -> List[dict]:
    """Одномерная чувствительность: сценарий строится из значения параметра, KPI и нарушения выводятся по каждому значению."""
    out = []
    for v in values:
        r = evaluate(case, plan, make_scenario(v))
        out.append({"value": v, "feasible": r.feasible, "total_cost": r.kpis["total_cost"],
                    "shortage_total": r.kpis["shortage_total"], "min_sl_critical": r.kpis["min_sl_critical"],
                    "hard_violations": r.kpis["hard_violations"]})
    return out
