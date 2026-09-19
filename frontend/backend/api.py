from __future__ import annotations

import copy
import importlib
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ВАЖНО:
# Этот файл — только адаптер. Каталог fuel_model не изменяется.
from fuel_model.loader import load_case
from fuel_model.engine import evaluate
from fuel_model.model import Plan, Scenario


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = os.getenv("FUEL_DATA_DIR", str(ROOT / "data" / "case_input"))
CONFIG_DIR = os.getenv("FUEL_CONFIG_DIR", str(ROOT / "configs"))

app = FastAPI(title="Kosmokontur Fuel Model API", version="1.0")

# Для GitHub Pages. В production лучше указать конкретный origin:
# ALLOW_ORIGINS=https://fenzyyy.github.io
allow_origins = os.getenv("ALLOW_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CalculateRequest(BaseModel):
    scenario_kind: str = "base"
    demand_variant: str = "base"
    isru_stress_share: float | None = None
    plan: dict[str, Any]


def _case():
    return load_case(DATA_DIR, CONFIG_DIR)


def _jsonable(value: Any) -> Any:
    """Превращает результат движка в обычный JSON без изменения самого движка."""
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _jsonable(value.to_dict())
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict
        return _jsonable(asdict(value))
    return value


def _scenario_from_payload(case, payload: CalculateRequest) -> Scenario:
    """
    Сначала пытаемся использовать штатные сценарии fuel_model.scenarios.
    Это важно: правила сценариев остаются в engine.
    """
    scenarios = importlib.import_module("fuel_model.scenarios")
    kind = payload.scenario_kind.lower()

    if kind == "base":
        factory = getattr(scenarios, "base", None)
        if callable(factory):
            sc = factory()
        else:
            raise RuntimeError("В fuel_model.scenarios не найден штатный сценарий base().")
    else:
        factory = None
        for name in (
            "mandatory_stress",
            "stress",
            "stress_scenario",
            "mandatory_stress_scenario",
        ):
            candidate = getattr(scenarios, name, None)
            if callable(candidate):
                factory = candidate
                break
        if factory is None:
            raise RuntimeError(
                "Не найден штатный stress-сценарий в fuel_model.scenarios. "
                "Передайте сценарий непосредственно из engine."
            )
        sc = factory()

    # Меняем только пользовательский вариант спроса.
    if hasattr(sc, "demand_variant"):
        sc.demand_variant = payload.demand_variant

    # Если UI передал долю ISRU, меняем только соответствующие ключи
    # штатной карты delivery_share. Формулы движка не дублируются.
    share = payload.isru_stress_share
    if share is not None and hasattr(sc, "delivery_share"):
        ds = dict(sc.delivery_share)
        for key in list(ds):
            source = key[0] if isinstance(key, tuple) and key else str(key)
            if "ISRU" in str(source).upper():
                ds[key] = share
        sc.delivery_share = ds

    return sc


def _plan_template(case) -> dict[str, Any]:
    years = list(case.years)
    orders = {
        sid: {str(y): 0.0 for y in years}
        for sid in case.sources
    }

    # Plan.from_dict() принимает нативную структуру модели.
    # reserved можно оставить пустым: Plan.reserved_capacity() использует
    # штатную логику движка для отсутствующего значения.
    return {
        "plan_id": "web_plan",
        "name": "План из веб-интерфейса",
        "orders": orders,
        "reserved": {},
        "initial_stock": [],
        "investments": {},
    }


def _scenario_preview(kind: str) -> dict[str, Any] | None:
    try:
        module = importlib.import_module("fuel_model.scenarios")
        if kind == "base":
            fn = getattr(module, "base", None)
        else:
            fn = next(
                (
                    getattr(module, n, None)
                    for n in (
                        "mandatory_stress",
                        "stress",
                        "stress_scenario",
                        "mandatory_stress_scenario",
                    )
                    if callable(getattr(module, n, None))
                ),
                None,
            )
        if callable(fn):
            return _jsonable(fn())
    except Exception:
        return None
    return None


@app.get("/api/health")
def health():
    try:
        case = _case()
        return {
            "ok": True,
            "engine": "fuel_model",
            "years": [case.first_year, case.last_year],
            "sources": list(case.sources),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/defaults")
def defaults():
    try:
        case = _case()
        return {
            "engine": "fuel_model",
            "engine_contract": "Case + Plan + Scenario -> Result",
            "years": list(case.years),
            "case": _jsonable(case.to_dict()),
            "plan_template": _plan_template(case),
            "scenario_templates": {
                "base": _scenario_preview("base"),
                "stress": _scenario_preview("stress"),
            },
            "ui": {
                "isru_stress_share": 0.5,
            },
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/calculate")
def calculate(payload: CalculateRequest):
    try:
        case = _case()

        # Нативная десериализация Plan — никаких формул/моделей в JS.
        plan = Plan.from_dict(copy.deepcopy(payload.plan))
        scenario = _scenario_from_payload(case, payload)

        result = evaluate(case, plan, scenario)
        return _jsonable(result)

    except Exception as exc:
        # PlanValidationError и обычные ValueError остаются видимыми
        # пользователю, чтобы ошибка не скрывалась адаптером.
        raise HTTPException(status_code=400, detail=str(exc))
