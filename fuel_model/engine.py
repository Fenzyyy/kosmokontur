"""Расчётное ядро: (Case, Plan, Scenario) -> Result.

Порядок расчёта (суточный шаг, 365-дневный год):
  1. валидация ввода (ошибки ввода останавливают расчёт);
  2. даты: доступность каналов, ввод опций, режим хранилища (resolve);
  3. график поставок: годовой заказ делится поровну между моментами поставок (1-е число месяца,
     начиная с даты доступности канала); в стрессе фактическая поставка = план x заданная доля;
  4. суточный цикл: поступление -> потери на валовое поступление -> проверка ёмкости -> выдача
     (критический спрос первым) -> дефицит отдельно -> запас на конец дня;
  5. затраты: CAPEX, закупка с take-or-pay, резерв мощности, хранение по среднему запасу, постоянный OPEX;
  6. ограничения (checks) и KPI.
Одни и те же функции используются интерфейсом, выгрузкой и тестами.
"""
from __future__ import annotations

import hashlib
import json
from typing import Dict, List, Optional

from . import formulas as F
from .checks import check_plan_rules, check_results
from .errors import SEVERITY_BENCHMARK, PlanValidationError
from .model import Case, Plan, Result, Scenario
from .resolve import Resolved, resolve
from .validation import validate_plan

ENGINE_VERSION = "0.1.0"
DAYS = 365


def input_fingerprint(case: Case) -> str:
    return hashlib.sha256(json.dumps(case.to_dict(), sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]


def _physics(case: Case, plan: Plan, scenario: Scenario, res: Resolved) -> dict:
    cal, a = res.cal, case.assumptions
    demand = case.demand_series(scenario.demand_variant, scenario.demand_multiplier)

    # --- график поставок ---------------------------------------------------------
    schedule: List[dict] = []
    by_day: Dict[int, List[dict]] = {}
    src_year: Dict[tuple, dict] = {}
    for y in case.years:
        starts = cal.month_starts(y)
        for sid in case.sources:
            avail = res.avail_day[sid]
            order = plan.order(sid, y)
            days = [d for d in starts if avail is not None and d >= avail]
            share = scenario.delivery_share.get((sid, y), 1.0)
            planned = actual = 0.0
            if order > 0 and days:
                each = order / len(days)
                for d in days:
                    got = F.stress_delivery(each, share)
                    row = {"date": cal.fmt(d), "year": y, "source": sid, "planned_t": each,
                           "actual_share": share, "actual_t": got}
                    schedule.append(row)
                    by_day.setdefault(d, []).append(row)
                    planned += each
                    actual += got
            src_year[(sid, y)] = {"order": order, "planned_delivery": planned, "actual_delivery": actual,
                                  "availability_fraction": cal.fraction_available(y, avail),
                                  "deliveries": len(days), "actual_share": share}

    # --- суточный цикл -------------------------------------------------------------
    inv = float(sum(l.tons for l in plan.initial_stock))
    yearly: List[dict] = []
    trace: List[dict] = []
    overflows: List[dict] = []
    holding_by_year: Dict[int, float] = {}

    for y in case.years:
        total, crit = demand[y]
        other = F.combined_total_demand(total, crit) - crit
        s, e = cal.year_bounds(y)
        crit_d, total_d = crit / DAYS, total / DAYS
        inv_open, inv_peak = inv, inv
        gross = losses = served_c = served_t = holding = 0.0
        reserve_stock = inv_open
        cap_end = case.storage[res.storage_mode_at(s)].capacity

        for d in range(s, e):
            mode_id = res.storage_mode_at(d)
            mode = case.storage[mode_id]
            cap_end = mode.capacity
            inflow = sum(r["actual_t"] for r in by_day.get(d, ()))
            if d == s and not a.reserve_check_after_first_delivery:
                reserve_stock = inv                      # до поставок 1 января (консервативно)
            if inflow > 0:
                lost = F.losses(inflow, mode.loss_rate)  # потери на валовое поступление, один раз
                inv += inflow - lost
                gross += inflow
                losses += lost
            if d == s and a.reserve_check_after_first_delivery:
                reserve_stock = inv
            if inv > mode.capacity + 1e-9:
                overflows.append({"year": y, "date": cal.fmt(d), "inventory": inv, "capacity": mode.capacity,
                                  "excess": inv - mode.capacity, "mode": mode_id})
            inv_peak = max(inv_peak, inv)
            after_receipt = inv
            sc, st = F.serve_demand(inv, crit_d, total_d)   # критический первым; served_total включает критический
            inv -= st
            if -1e-9 < inv < 0:
                inv = 0.0
            served_c += sc
            served_t += st
            holding += mode.holding_cost * (after_receipt + inv) / 2.0 / DAYS   # млн у.е. за сутки
            trace.append({"date": cal.fmt(d), "receipts_t": inflow, "inventory_t": inv, "storage_mode": mode_id})
        holding_by_year[y] = holding

        short_t = max(0.0, total - served_t)
        short_c = max(0.0, crit - served_c)
        short_t = 0.0 if short_t < 1e-9 else short_t
        short_c = 0.0 if short_c < 1e-9 else short_c
        yearly.append({
            "year": y, "demand_total": total, "demand_critical": crit, "demand_other": other,
            "served_total": served_t, "served_critical": served_c, "served_other": served_t - served_c,
            "shortage_total": short_t, "shortage_critical": short_c,
            "sl_total": F.service_level(served_t, total), "sl_critical": F.service_level(served_c, crit),
            "inventory_open": inv_open, "gross_inflow": gross, "losses": losses,
            "loss_share": (losses / gross) if gross > 0 else 0.0,
            "inventory_close": inv, "inventory_peak": inv_peak, "storage_capacity_end": cap_end,
            "reserve_required": F.reserve_requirement(total, case.constraints.reserve_days),
            "reserve_stock_at_check": reserve_stock,
            "balance_residual": F.closing_inventory(inv_open, gross, losses, served_t) - inv,
            "sources": {sid: src_year[(sid, y)] for sid in case.sources},
        })
    return {"yearly": yearly, "trace": trace, "schedule": schedule, "overflows": overflows,
            "holding": holding_by_year}


def _costs(case: Case, plan: Plan, scenario: Scenario, res: Resolved, phys: dict) -> List[dict]:
    cal, a = res.cal, case.assumptions
    base_year = a.discount_base_year or case.first_year
    rows: List[dict] = []
    served_by_year = {r["year"]: r["served_total"] for r in phys["yearly"]}

    initial_cost = 0.0
    for lot in plan.initial_stock:
        src = case.sources[lot.source_id]
        initial_cost += lot.tons * src.variable_cost * scenario.price_multiplier.get((lot.source_id, case.first_year), 1.0)

    for y in case.years:
        var_total = rsv_total = 0.0
        per_src: Dict[str, dict] = {}
        for sid, src in case.sources.items():
            frac = cal.fraction_available(y, res.avail_day[sid])
            reserved = plan.reserved_capacity(src, y)
            order = plan.order(sid, y)
            price = src.variable_cost * scenario.price_multiplier.get((sid, y), 1.0)
            if frac > 0:
                reserved_period = reserved * frac
                payable = F.payable_volume(order, src.top_share, reserved_period)
                var = F.variable_payment(price, order, src.top_share, reserved_period)
                rsv = F.reservation_payment(src.reservation_rate, reserved, frac)
            else:
                reserved_period = payable = var = rsv = 0.0
            per_src[sid] = {"price": price, "reserved_capacity": reserved, "reserved_period_volume": reserved_period,
                            "order": order if frac > 0 else 0.0, "payable_volume": payable,
                            "variable_payment": var, "reservation_payment": rsv,
                            "take_or_pay_unused_t": max(0.0, payable - (order if frac > 0 else 0.0)),
                            "take_or_pay_unused_cost": price * max(0.0, payable - (order if frac > 0 else 0.0))}
            var_total += var
            rsv_total += rsv

        capex = 0.0
        for oid, dec in plan.investments.items():
            opt = case.options[oid]
            for (sy, _sm), amount in zip(dec.stage_dates, opt.stage_amounts):
                if sy == y:
                    capex += amount
        fixed_opex = sum(case.options[oid].fixed_opex * cal.fraction_available(y, day)
                         for oid, day in res.in_service_day.items())
        initial = initial_cost if y == case.first_year else 0.0
        procurement = var_total + initial
        holding = phys["holding"][y]
        total = procurement + rsv_total + holding + fixed_opex + capex
        df = F.discount_factor(a.discount_rate, y, base_year)
        served = served_by_year[y]
        rows.append({"year": y, "capex": capex, "procurement": procurement, "variable_payments": var_total,
                     "initial_stock_cost": initial, "reservation": rsv_total, "holding": holding,
                     "fixed_opex": fixed_opex, "total": total, "discount_factor": df, "pv_total": total * df,
                     "cost_per_served_ton": (total / served) if served > 0 else None, "sources": per_src})
    return rows


def _kpis(case: Case, yearly: List[dict], costs: List[dict], violations: list) -> dict:
    c = case.constraints
    served = sum(r["served_total"] for r in yearly)
    total_cost = sum(r["total"] for r in costs)
    pv_cost = sum(r["pv_total"] for r in costs)
    return {
        "total_cost": total_cost, "pv_cost": pv_cost,
        "capex_total": sum(r["capex"] for r in costs),
        "capex_through_deadline": sum(r["capex"] for r in costs if r["year"] <= c.capex_cumulative_year),
        "procurement_total": sum(r["procurement"] for r in costs), "reservation_total": sum(r["reservation"] for r in costs),
        "holding_total": sum(r["holding"] for r in costs), "fixed_opex_total": sum(r["fixed_opex"] for r in costs),
        "take_or_pay_unused_cost": sum(s["take_or_pay_unused_cost"] for r in costs for s in r["sources"].values()),
        "served_total": served, "served_critical": sum(r["served_critical"] for r in yearly),
        "shortage_total": sum(r["shortage_total"] for r in yearly),
        "shortage_critical": sum(r["shortage_critical"] for r in yearly),
        "min_sl_total": min(r["sl_total"] for r in yearly), "min_sl_critical": min(r["sl_critical"] for r in yearly),
        "losses_total": sum(r["losses"] for r in yearly),
        "cost_per_served_ton": (total_cost / served) if served > 0 else None,
        "pv_cost_per_served_ton": (pv_cost / served) if served > 0 else None,
        "max_abs_balance_residual": max(abs(r["balance_residual"]) for r in yearly),
        "hard_violations": sum(1 for v in violations if v.severity == "HARD"),
        "benchmark_misses": sum(1 for v in violations if v.severity == SEVERITY_BENCHMARK),
    }


def evaluate(case: Case, plan: Plan, scenario: Optional[Scenario] = None) -> Result:
    """Полный расчёт плана в сценарии. При ошибке ввода поднимает PlanValidationError (расчёт не запускается)."""
    if scenario is None:
        from .scenarios import base
        scenario = base()
    issues = validate_plan(case, plan, scenario)
    if issues:
        raise PlanValidationError(issues)
    res = resolve(case, plan)
    phys = _physics(case, plan, scenario, res)
    costs = _costs(case, plan, scenario, res, phys)
    violations = check_plan_rules(case, plan, scenario, res) + check_results(case, scenario, phys["yearly"], costs,
                                                                             phys["overflows"])
    meta = {"plan_id": plan.plan_id, "plan_name": plan.name, "scenario_id": scenario.scenario_id,
            "scenario_name": scenario.name, "scenario_kind": scenario.kind, "scenario_changes": list(scenario.changes),
            "engine_version": ENGINE_VERSION, "input_version": input_fingerprint(case),
            "horizon": [case.first_year, case.last_year], "units": {"fuel": "т", "money": "млн у.е. (цены 2035 г.)"},
            "assumptions": case.to_dict()["assumptions"]}
    return Result(meta, phys["yearly"], costs, _kpis(case, phys["yearly"], costs, violations), violations,
                  phys["trace"], phys["schedule"])
