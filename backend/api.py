from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from fuel_model.engine import ENGINE_VERSION
from fuel_model.investments import build_investment_decision, decision_to_dict
from fuel_model.loader import load_case
from fuel_model.model import Plan
from fuel_model.scenarios import get

from .schemas import CalculateRequest, FrontierRequest, OptimizeRequest
from .services.frontier import build_frontier
from .services.optimize import (
    calculate,
    load_plan,
    optimization_to_dict,
    result_to_dict,
    run_optimizer,
    scenario_list,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = os.getenv("FUEL_DATA_DIR", str(ROOT / "data" / "case_input"))
CONFIG_DIR = os.getenv("FUEL_CONFIG_DIR", str(ROOT / "configs"))
FRONTEND_DIR = ROOT / "frontend"

app = FastAPI(
    title="Kosmokontur Fuel Model API",
    version="1.1.0",
    description="Web adapter for the fuel_model calculation engine.",
)

origins = [x.strip() for x in os.getenv("ALLOW_ORIGINS", "*").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def case():
    return load_case(DATA_DIR, CONFIG_DIR)


def plan_template(c) -> dict[str, Any]:
    years = list(c.years)
    return Plan(
        plan_id="web_plan",
        name="План веб-интерфейса",
        orders={sid: {y: 0.0 for y in years} for sid in c.sources},
        reserved={},
        initial_stock=[],
        investments={},
    ).to_dict()


@app.get("/api/health")
def health():
    try:
        c = case()
        return {
            "ok": True,
            "engine": "fuel_model",
            "engine_version": ENGINE_VERSION,
            "years": [c.first_year, c.last_year],
            "sources": [
                {
                    "id": s.source_id,
                    "name": s.name,
                    "capacity": s.capacity,
                    "variable_cost": s.variable_cost,
                }
                for s in c.sources.values()
            ],
            "storage": [
                {
                    "id": s.mode_id,
                    "name": s.name,
                    "capacity": s.capacity,
                    "loss_rate": s.loss_rate,
                }
                for s in c.storage.values()
            ],
            "investments": [
                {
                    "id": o.option_id,
                    "kind": o.kind,
                    "target_id": o.target_id,
                    "capex": o.total_capex,
                }
                for o in c.options.values()
            ],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/defaults")
def defaults():
    try:
        c = case()
        return {
            "years": list(c.years),
            "plan_template": plan_template(c),
            "sources": [
                {
                    "id": s.source_id,
                    "name": s.name,
                    "capacity": s.capacity,
                    "variable_cost": s.variable_cost,
                }
                for s in c.sources.values()
            ],
            "investments": [
                {
                    "id": o.option_id,
                    "kind": o.kind,
                    "target_id": o.target_id,
                    "stage_labels": list(o.stage_labels),
                    "stage_amounts": list(o.stage_amounts),
                    "capex": o.total_capex,
                    "earliest_in_service_year": o.earliest_in_service_year,
                    "default_schedule": (
                        decision_to_dict(decision)
                        if (decision := build_investment_decision(c, o.option_id)) is not None
                        else None
                    ),
                }
                for o in c.options.values()
            ],
            "scenarios": [
                get("BASE").to_dict(),
                get("MANDATORY_STRESS").to_dict(),
            ],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/calculate")
def calculate_api(payload: CalculateRequest):
    try:
        c = case()
        plan = load_plan(payload.plan)
        scenario = get(payload.scenario_id.upper())
        return result_to_dict(calculate(c, plan, scenario))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/optimize")
def optimize_api(payload: OptimizeRequest):
    try:
        c = case()
        plan = load_plan(payload.plan)
        scenarios = scenario_list(payload.scenario_ids)
        result = run_optimizer(c, plan, scenarios)
        data = optimization_to_dict(result)
        if not payload.run_frontier:
            data["frontier"] = []
        return data
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/frontier")
def frontier_api(payload: FrontierRequest):
    try:
        c = case()
        plan = load_plan(payload.plan)
        scenarios = scenario_list(payload.scenario_ids)
        optimized = optimization_to_dict(run_optimizer(c, plan, scenarios))
        return {
            "scenarios": optimized["scenarios"],
            "points": build_frontier(optimized),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
