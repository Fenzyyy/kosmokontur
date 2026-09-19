"""Проверка ограничений. Каждое нарушение содержит код, год, величину, предел и причину.

Неисполнимый план не «чинится» и не скрывается усреднением: нарушения показываются по каждому году.
"""
from __future__ import annotations

from typing import Dict, List

from . import formulas as F
from .errors import SEVERITY_BENCHMARK, SEVERITY_HARD, SEVERITY_WARNING, Violation
from .model import Case, Plan, Scenario
from .resolve import Resolved

EPS = 1e-6


def months_between(a: tuple, b: tuple) -> int:
    return (b[0] - a[0]) * 12 + (b[1] - a[1])


def check_plan_rules(case: Case, plan: Plan, scenario: Scenario, res: Resolved) -> List[Violation]:
    """Правила, вытекающие из самого плана: мощность, резерв, доступность, сроки, инвестиции, Emergency."""
    out: List[Violation] = []
    cal, a, c = res.cal, case.assumptions, case.constraints

    for y in case.years:
        starts = cal.month_starts(y)
        for sid, src in case.sources.items():
            reserved = plan.reserved_capacity(src, y)
            excess = F.capacity_excess(reserved, src.capacity)
            if excess > EPS:
                out.append(Violation("CAPACITY_EXCEEDED", SEVERITY_HARD,
                                     f"{src.name}, {y}: резерв {reserved:.2f} т/год > мощность {src.capacity:.2f} т/год "
                                     f"(превышение {excess:.2f})", y, sid, reserved, src.capacity, excess))
            order = plan.order(sid, y)
            if order <= EPS:
                continue
            avail = res.avail_day[sid]
            frac = cal.fraction_available(y, avail)
            has_moment = avail is not None and any(d >= avail for d in starts)
            if frac <= EPS or not has_moment:
                since = "не будет доступен" if avail is None else f"доступен с {cal.fmt(avail)}"
                out.append(Violation("SOURCE_NOT_AVAILABLE", SEVERITY_HARD,
                                     f"{src.name}, {y}: заказано {order:.2f} т, но канал {since}", y, sid, order, 0.0, order))
                continue
            limit = reserved * frac
            if order > limit + EPS:
                out.append(Violation("ORDER_EXCEEDS_RESERVED", SEVERITY_HARD,
                                     f"{src.name}, {y}: заказ {order:.2f} т > зарезервированного объёма периода {limit:.2f} т "
                                     f"(резерв {reserved:.2f} т/год x доля года {frac:.3f})", y, sid, order, limit, order - limit))

    # начальный запас: канал должен быть доступен в подготовительном периоде, объём - помещаться в хранилище
    total_lots = sum(l.tons for l in plan.initial_stock)
    for lot in plan.initial_stock:
        avail = res.avail_day.get(lot.source_id)
        if lot.tons > EPS and (avail is None or avail > 0):
            out.append(Violation("SOURCE_NOT_AVAILABLE", SEVERITY_HARD,
                                 f"Начальный запас {lot.tons:.2f} т от канала {lot.source_id}: канал недоступен "
                                 f"до начала горизонта", case.first_year, lot.source_id, lot.tons, 0.0, lot.tons))
    base_cap = case.storage[res.storage_mode_at(0)].capacity
    if total_lots > base_cap + EPS:
        out.append(Violation("INITIAL_STOCK_EXCEEDS_STORAGE", SEVERITY_HARD,
                             f"Начальный запас {total_lots:.2f} т > ёмкость хранилища {base_cap:.2f} т",
                             case.first_year, "initial_stock", total_lots, base_cap, total_lots - base_cap))

    for oid, dec in plan.investments.items():
        opt = case.options[oid]
        s_years = [y for y, _ in dec.stage_dates]
        if opt.earliest_stage_year and min(s_years) < opt.earliest_stage_year:
            out.append(Violation("INVESTMENT_TIMING", SEVERITY_HARD,
                                 f"{oid}: платёж в {min(s_years)} г. раньше допустимого {opt.earliest_stage_year} г.",
                                 min(s_years), oid, float(min(s_years)), float(opt.earliest_stage_year)))
        if opt.latest_capex_year and max(s_years) > opt.latest_capex_year:
            out.append(Violation("INVESTMENT_TIMING", SEVERITY_HARD,
                                 f"{oid}: CAPEX должен быть профинансирован до конца {opt.latest_capex_year} г., "
                                 f"последний платёж в {max(s_years)} г.", max(s_years), oid,
                                 float(max(s_years)), float(opt.latest_capex_year)))
        if opt.earliest_in_service_year and dec.in_service[0] < opt.earliest_in_service_year:
            out.append(Violation("INVESTMENT_TIMING", SEVERITY_HARD,
                                 f"{oid}: ввод в {dec.in_service[0]} г. раньше допустимого {opt.earliest_in_service_year} г.",
                                 dec.in_service[0], oid, float(dec.in_service[0]), float(opt.earliest_in_service_year)))
        gap = months_between(max(dec.stage_dates), dec.in_service)
        if gap < opt.min_build_months - EPS:
            out.append(Violation("LEAD_TIME_VIOLATION", SEVERITY_HARD,
                                 f"{oid}: от последнего платежа до ввода {gap} мес. < минимального срока {opt.min_build_months:g} мес.",
                                 dec.in_service[0], oid, float(gap), opt.min_build_months, opt.min_build_months - gap))
        elif a.lead_time_choice == "max" and gap < opt.max_build_months - EPS:
            out.append(Violation("LEAD_TIME_OPTIMISTIC", SEVERITY_WARNING,
                                 f"{oid}: срок {gap} мес. короче верхней границы {opt.max_build_months:g} мес. (диапазон "
                                 f"{opt.min_build_months:g}-{opt.max_build_months:g})", dec.in_service[0], oid,
                                 float(gap), opt.max_build_months, opt.max_build_months - gap))

    eid = c.emergency_source_id
    if eid in case.sources:
        streak = 0
        for y in case.years:
            streak = streak + 1 if plan.order(eid, y) > a.emergency_used_threshold_t + EPS else 0
            if streak > c.emergency_max_consecutive_years:
                out.append(Violation("EMERGENCY_BASE_STREAK", SEVERITY_HARD,
                                     f"Emergency ({eid}) используется как плановый канал {streak} лет подряд к {y} г. "
                                     f"(допустимо не более {c.emergency_max_consecutive_years})", y, eid,
                                     float(streak), float(c.emergency_max_consecutive_years),
                                     float(streak - c.emergency_max_consecutive_years)))
    return out


def check_results(case: Case, scenario: Scenario, yearly: List[dict], costs: List[dict],
                  overflows: List[dict]) -> List[Violation]:
    """Ограничения, проверяемые по результату физического расчёта и затрат."""
    out: List[Violation] = []
    c = case.constraints
    sl_sev = SEVERITY_BENCHMARK if scenario.sl_is_benchmark else SEVERITY_HARD
    sl_note = "ориентир устойчивости" if scenario.sl_is_benchmark else "обязательное требование"

    for r in yearly:
        y = r["year"]
        if r["sl_total"] < c.sl_total_min - 1e-9:
            out.append(Violation("SL_TOTAL_LOW", sl_sev,
                                 f"{y}: обслужено {r['sl_total']:.1%} общего спроса ({sl_note} {c.sl_total_min:.0%}); "
                                 f"дефицит {r['shortage_total']:.2f} т", y, "total", r["sl_total"], c.sl_total_min,
                                 c.sl_total_min - r["sl_total"]))
        if r["sl_critical"] < c.sl_critical_min - 1e-9:
            out.append(Violation("SL_CRITICAL_LOW", sl_sev,
                                 f"{y}: обслужено {r['sl_critical']:.1%} критического спроса ({sl_note} "
                                 f"{c.sl_critical_min:.0%}); дефицит {r['shortage_critical']:.2f} т", y, "critical",
                                 r["sl_critical"], c.sl_critical_min, c.sl_critical_min - r["sl_critical"]))
        if r["reserve_stock_at_check"] < r["reserve_required"] - EPS:
            out.append(Violation("RESERVE_45D_SHORT", SEVERITY_HARD,
                                 f"{y}: физический запас на начало года {r['reserve_stock_at_check']:.2f} т < резерва "
                                 f"{c.reserve_days:g} дней спроса {r['reserve_required']:.2f} т", y, "reserve",
                                 r["reserve_stock_at_check"], r["reserve_required"],
                                 r["reserve_required"] - r["reserve_stock_at_check"]))
        ceiling = scenario.loss_ceiling.get(y)
        if ceiling is not None and r["gross_inflow"] > 0 and r["loss_share"] > ceiling + 1e-12:
            out.append(Violation("LOSS_CEILING_EXCEEDED", SEVERITY_HARD,
                                 f"{y}: потери {r['loss_share']:.2%} валового поступления > предела {ceiling:.0%} "
                                 f"({r['losses']:.2f} т из {r['gross_inflow']:.2f} т)", y, "losses",
                                 r["loss_share"], ceiling, r["loss_share"] - ceiling))

    worst: Dict[int, dict] = {}
    for ev in overflows:
        if ev["year"] not in worst or ev["excess"] > worst[ev["year"]]["excess"]:
            worst[ev["year"]] = ev
    for y, ev in sorted(worst.items()):
        out.append(Violation("STORAGE_OVERFLOW", SEVERITY_HARD,
                             f"{y}: запас {ev['inventory']:.2f} т после поставки {ev['date']} > ёмкости {ev['capacity']:.2f} т "
                             f"(режим {ev['mode']}); дней с переполнением: "
                             f"{sum(1 for e in overflows if e['year'] == y)}", y, "storage", ev["inventory"],
                             ev["capacity"], ev["excess"]))

    cum = 0.0
    for r in costs:
        if r["year"] <= c.capex_cumulative_year:
            cum += r["capex"]
    if cum > c.capex_cumulative_limit + EPS:
        out.append(Violation("CAPEX_LIMIT_CUMULATIVE", SEVERITY_HARD,
                             f"CAPEX до конца {c.capex_cumulative_year} г.: {cum:.1f} млн > лимита {c.capex_cumulative_limit:.0f}",
                             c.capex_cumulative_year, "capex", cum, c.capex_cumulative_limit,
                             cum - c.capex_cumulative_limit))
    total = sum(r["capex"] for r in costs)
    if total > c.capex_total_limit + EPS:
        out.append(Violation("CAPEX_LIMIT_TOTAL", SEVERITY_HARD,
                             f"Суммарный CAPEX {total:.1f} млн > лимита {c.capex_total_limit:.0f}", case.last_year, "capex",
                             total, c.capex_total_limit, total - c.capex_total_limit))
    return out
