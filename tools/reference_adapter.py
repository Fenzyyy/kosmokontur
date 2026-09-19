"""Adapter from the organizer's portable ParticipantPlan envelope to fuel_model.Plan.

The organizer reference format intentionally leaves decision objects open. This
adapter accepts the common fields used by the reference examples and maps them
to our native Plan contract. Unknown/unsupported optional fields are ignored.
"""

from __future__ import annotations

from typing import Any, Mapping

from fuel_model.model import InitialStockLot, InvestmentDecision, Plan
from fuel_model.calendar import parse_ym


def _first(row: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in row:
            return row[name]
    return default


def _parse_initial_stock(policy: Any) -> list[InitialStockLot]:
    if not policy:
        return []

    raw = policy.get("initial_stock", policy.get("initial_inventory", [])) if isinstance(policy, dict) else policy
    if isinstance(raw, dict):
        return [
            InitialStockLot(str(source_id), float(tons))
            for source_id, tons in raw.items()
        ]

    lots: list[InitialStockLot] = []
    for row in raw or []:
        source_id = _first(row, "source_id", "source")
        tons = _first(row, "tons", "initial_stock_t", "inventory_t")
        if source_id is None or tons is None:
            continue
        lots.append(InitialStockLot(str(source_id), float(tons)))
    return lots


def _parse_investments(raw: Any) -> dict[str, InvestmentDecision]:
    if not raw:
        return {}

    items = raw.items() if isinstance(raw, dict) else (
        (str(_first(row, "investment_id", "option_id", "id")), row) for row in raw
    )
    result: dict[str, InvestmentDecision] = {}

    for option_id, row in items:
        if not option_id or not isinstance(row, Mapping):
            continue

        stage_dates_raw = _first(row, "stage_dates", "capex_dates")
        in_service_raw = _first(row, "in_service", "in_service_date")
        if stage_dates_raw is None or in_service_raw is None:
            continue

        stage_dates = tuple(parse_ym(str(value)) for value in stage_dates_raw)
        result[str(option_id)] = InvestmentDecision(
            stage_dates=stage_dates,
            in_service=parse_ym(str(in_service_raw)),
        )
    return result


def organizer_plan_to_plan(payload: Mapping[str, Any]) -> Plan:
    """Convert a reference ParticipantPlan JSON object to native fuel_model.Plan."""

    if not isinstance(payload, Mapping):
        raise TypeError("ParticipantPlan payload must be an object")

    decisions = payload.get("decisions")
    if not isinstance(decisions, Mapping):
        raise ValueError("ParticipantPlan requires an object field: decisions")

    plan_id = str(payload.get("plan_id") or "reference-plan")
    orders: dict[str, dict[int, float]] = {}
    for row in decisions.get("supply_orders", []) or []:
        source_id = _first(row, "source_id", "source")
        year = _first(row, "year")
        volume = _first(row, "ordered_volume_t", "order_t", "volume_t", "ordered_volume")
        if source_id is None or year is None or volume is None:
            continue
        orders.setdefault(str(source_id), {})[int(year)] = float(volume)

    reserved: dict[str, dict[int, float]] = {}
    for row in decisions.get("capacity_reservations", []) or []:
        source_id = _first(row, "source_id", "source")
        year = _first(row, "year")
        volume = _first(row, "reserved_capacity_t", "reserved_t", "capacity_t")
        if source_id is None or year is None or volume is None:
            continue
        reserved.setdefault(str(source_id), {})[int(year)] = float(volume)

    return Plan(
        plan_id=plan_id,
        name=str(payload.get("name", "")),
        notes=str(payload.get("notes", "")),
        orders=orders,
        reserved=reserved,
        initial_stock=_parse_initial_stock(decisions.get("inventory_policy", {})),
        investments=_parse_investments(decisions.get("investments", [])),
    )
