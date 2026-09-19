from __future__ import annotations

from typing import Any, Iterable

from fuel_model.engine import evaluate
from fuel_model.loader import load_case
from fuel_model.model import Plan, Result, Scenario
from fuel_model.optimizer import OptimizationResult, optimize
from fuel_model.scenarios import get


def result_to_dict(result: Result) -> dict[str, Any]:
    return result.to_dict(include_trace=False)


def load_plan(raw: dict[str, Any]) -> Plan:
    return Plan.from_dict(raw)


def scenario_list(ids: Iterable[str]) -> list[Scenario]:
    return [get(str(s).upper()) for s in ids]


def calculate(case, plan: Plan, scenario: Scenario) -> Result:
    return evaluate(case, plan, scenario)


def run_optimizer(case, plan: Plan, scenarios: list[Scenario]) -> OptimizationResult:
    return optimize(case, scenarios, initial_plan=plan)


def optimization_to_dict(result: OptimizationResult) -> dict[str, Any]:
    scenarios = {
        sid: result_to_dict(value)
        for sid, value in result.scenario_results.items()
    }

    frontier = []
    for candidate in result.candidate_summaries:
        metrics = candidate.scenario_metrics
        base = metrics.get("BASE", {})
        stress = metrics.get("MANDATORY_STRESS", {})
        frontier.append({
            "investments": list(candidate.investments),
            "status": candidate.status,
            "reason": candidate.reason,
            "selected": candidate.selected,
            "capex_total": candidate.capex_total,
            "capex_through_deadline": candidate.capex_through_deadline,
            "service_level_base": base.get("min_sl_total"),
            "service_level_stress": stress.get("min_sl_total"),
            "shortage_base": base.get("shortage_total"),
            "shortage_stress": stress.get("shortage_total"),
            "pv_cost_base": base.get("pv_cost"),
        })

    return {
        "plan": result.plan.to_dict(),
        "feasible": result.feasible,
        "score": list(result.score),
        "candidates_checked": result.candidates_checked,
        "iterations": result.iterations,
        "notes": result.notes,
        "scenarios": scenarios,
        "frontier": frontier,
    }
