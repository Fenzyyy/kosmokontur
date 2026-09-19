"""Перевод решений плана в даты: когда доступен канал, когда введена опция, какой режим хранения действует."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .calendar import ModelCalendar
from .model import Case, Plan


@dataclass
class Resolved:
    cal: ModelCalendar
    prep_start_day: int                          # начало подготовительного периода (отрицательный индекс дня)
    avail_day: Dict[str, Optional[int]]          # канал -> первый день возможных поставок (None - недоступен)
    in_service_day: Dict[str, int]               # опция -> день ввода
    stage_days: Dict[str, List[int]]             # опция -> дни платежей CAPEX
    storage_schedule: List[Tuple[int, str]]      # [(день, mode_id)], по возрастанию дня

    def storage_mode_at(self, day: int) -> str:
        mode = self.storage_schedule[0][1]
        for d, m in self.storage_schedule:
            if d <= day:
                mode = m
            else:
                break
        return mode


def chosen_lead(case: Case, source_id: str) -> float:
    s = case.sources[source_id]
    return s.lead_time_max if case.assumptions.lead_time_choice == "max" else s.lead_time_min


def resolve(case: Case, plan: Plan) -> Resolved:
    a = case.assumptions
    cal = ModelCalendar(case.first_year, case.last_year)
    prep_start = (cal.add_months(0, -int(a.prep_months)) if float(a.prep_months).is_integer()
                  else -int(round(a.prep_months * 365 / 12)))

    in_service: Dict[str, int] = {}
    stage_days: Dict[str, List[int]] = {}
    for oid, dec in plan.investments.items():
        if oid in case.options:
            in_service[oid] = cal.day(*dec.in_service)
            stage_days[oid] = [cal.day(y, m) for (y, m) in dec.stage_dates]

    avail: Dict[str, Optional[int]] = {}
    for sid, src in case.sources.items():
        role = case.role(sid)
        lead = chosen_lead(case, sid)
        if role.requires_option:
            if role.requires_option not in in_service:
                avail[sid] = None
                continue
            base = in_service[role.requires_option]
            day = cal.add_lead(base, lead, src.lead_time_unit) if role.lead_time_semantics == "post_commissioning" else base
        else:
            # заказ размещён в начале подготовительного периода; поставки не раньше 1 января первого года
            day = max(0, cal.add_lead(prep_start, lead, src.lead_time_unit))
        if src.available_from_year:
            day = max(day, cal.day(src.available_from_year))
        avail[sid] = day

    events = sorted((in_service[oid], opt.target_id) for oid, opt in case.options.items()
                    if opt.kind == "storage" and oid in in_service)
    schedule = [(-10 ** 9, case.base_storage_id)] + events
    return Resolved(cal, prep_start, avail, in_service, stage_days, schedule)
