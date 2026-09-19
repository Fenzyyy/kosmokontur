from __future__ import annotations

from typing import Any


def build_frontier(optimization_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only useful candidate points for the investment frontier."""
    points = []
    for p in optimization_payload.get("frontier", []):
        if p.get("status") != "evaluated":
            continue
        if p.get("capex_total") is None:
            continue
        points.append(p)

    # Stable, deterministic order for the frontend.
    points.sort(key=lambda p: (float(p["capex_total"]), str(p["investments"])))
    return points
