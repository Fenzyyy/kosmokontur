from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api import app, case
from fuel_model.investments import build_investment_decision, decision_to_dict
from fuel_model.optimizer import optimize
from fuel_model.model import Plan
from fuel_model.scenarios import get


client = TestClient(app)


def test_health_and_defaults_load_real_case():
    health = client.get("/api/health")
    assert health.status_code == 200
    body = health.json()
    assert body["ok"] is True
    assert body["years"] == [2035, 2040]
    assert {s["id"] for s in body["sources"]} == {"A", "B", "C", "D", "E"}

    defaults = client.get("/api/defaults")
    assert defaults.status_code == 200
    data = defaults.json()
    assert data["years"] == [2035, 2036, 2037, 2038, 2039, 2040]
    assert set(data["plan_template"]["orders"]) == {"A", "B", "C", "D", "E"}
    assert {x["id"] for x in data["investments"]} == {"EARTH_NEW", "LUNAR_ISRU", "ZBO"}
    assert {x["scenario_id"] for x in data["scenarios"]} == {"BASE", "MANDATORY_STRESS"}


def test_calculate_round_trip_with_real_case():
    defaults = client.get("/api/defaults").json()
    response = client.post(
        "/api/calculate",
        json={"plan": defaults["plan_template"], "scenario_id": "BASE"},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["meta"]["scenario_id"] == "BASE"
    assert len(result["yearly"]) == 6
    assert len(result["costs"]) == 6
    assert "shortage_total" in result["kpis"]
    assert "violations" in result


def test_optimize_round_trip_base_and_stress():
    defaults = client.get("/api/defaults").json()
    response = client.post(
        "/api/optimize",
        json={
            "plan": defaults["plan_template"],
            "scenario_ids": ["BASE", "MANDATORY_STRESS"],
            "run_frontier": True,
        },
    )
    assert response.status_code == 200, response.text

    data = response.json()
    assert set(data["scenarios"]) == {"BASE", "MANDATORY_STRESS"}
    assert isinstance(data["plan"], dict)
    assert "orders" in data["plan"]
    assert "investments" in data["plan"]
    assert isinstance(data["frontier"], list)
    assert data["candidates_checked"] > 0

    for scenario_id in ("BASE", "MANDATORY_STRESS"):
        result = data["scenarios"][scenario_id]
        assert "feasible" in result
        assert len(result["yearly"]) == 6
        assert len(result["costs"]) == 6
        assert "kpis" in result
        assert "violations" in result

    selected = [p for p in data["frontier"] if p.get("selected")]
    assert len(selected) <= 1


def test_investment_schedule_is_shared_by_api_and_optimizer():
    c = case()
    defaults = client.get("/api/defaults").json()
    api_investments = {item["id"]: item for item in defaults["investments"]}

    for option_id in c.options:
        expected = build_investment_decision(c, option_id)
        expected_payload = decision_to_dict(expected) if expected is not None else None
        assert api_investments[option_id]["default_schedule"] == expected_payload

    result = optimize(
        c,
        [get("BASE")],
        initial_plan=Plan.from_dict(defaults["plan_template"]),
    )
    for option_id, decision in result.plan.investments.items():
        assert decision_to_dict(decision) == api_investments[option_id]["default_schedule"]
