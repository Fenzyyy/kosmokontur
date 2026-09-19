from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api import app


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
