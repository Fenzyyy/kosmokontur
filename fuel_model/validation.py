"""Проверка ввода: план и сценарий как ДАННЫЕ. Ошибки ввода останавливают расчёт и называют поле."""
from __future__ import annotations

import math
from typing import List, Optional

from .errors import ValidationIssue
from .model import Case, Plan, Scenario


def _bad_number(x) -> bool:
    return not isinstance(x, (int, float)) or math.isnan(x) or math.isinf(x)


def validate_plan(case: Case, plan: Plan, scenario: Optional[Scenario] = None) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    years = set(case.years)

    for table, label in ((plan.orders, "orders"), (plan.reserved, "reserved")):
        for sid, by_year in table.items():
            if sid not in case.sources:
                issues.append(ValidationIssue("UNKNOWN_SOURCE", f"{label}.{sid}",
                                              f"Канал {sid!r} не найден; доступны: {sorted(case.sources)}"))
                continue
            for y, v in by_year.items():
                if y not in years:
                    issues.append(ValidationIssue("YEAR_OUT_OF_HORIZON", f"{label}.{sid}.{y}",
                                                  f"Год {y} вне горизонта {case.first_year}-{case.last_year}"))
                if _bad_number(v):
                    issues.append(ValidationIssue("NOT_A_NUMBER", f"{label}.{sid}.{y}", f"Значение {v!r} не является числом"))
                elif v < 0:
                    issues.append(ValidationIssue("NEGATIVE_VALUE", f"{label}.{sid}.{y}",
                                                  f"Объём не может быть отрицательным: {v}"))

    for i, lot in enumerate(plan.initial_stock):
        if lot.source_id not in case.sources:
            issues.append(ValidationIssue("UNKNOWN_SOURCE", f"initial_stock[{i}].source",
                                          f"Канал {lot.source_id!r} не найден"))
        if _bad_number(lot.tons) or lot.tons < 0:
            issues.append(ValidationIssue("NEGATIVE_VALUE", f"initial_stock[{i}].tons",
                                          f"Начальный запас должен быть числом >= 0, получено {lot.tons!r}"))

    for oid, dec in plan.investments.items():
        opt = case.options.get(oid)
        if opt is None:
            issues.append(ValidationIssue("UNKNOWN_OPTION", f"investments.{oid}",
                                          f"Инвестиционная опция {oid!r} не найдена; доступны: {sorted(case.options)}"))
            continue
        if len(dec.stage_dates) != len(opt.stage_amounts):
            issues.append(ValidationIssue(
                "STAGE_COUNT_MISMATCH", f"investments.{oid}.stage_dates",
                f"Нужно {len(opt.stage_amounts)} дат платежей ({', '.join(opt.stage_labels)}), задано {len(dec.stage_dates)}"))
            continue
        for k, (y, m) in enumerate(list(dec.stage_dates) + [dec.in_service]):
            name = f"stage_dates[{k}]" if k < len(dec.stage_dates) else "in_service"
            if y < case.first_year or y > case.last_year:
                issues.append(ValidationIssue("DATE_OUT_OF_HORIZON", f"investments.{oid}.{name}",
                                              f"Дата {y}-{m:02d} вне горизонта {case.first_year}-{case.last_year}"))
        if dec.stage_dates and dec.in_service < max(dec.stage_dates):
            issues.append(ValidationIssue("DATE_ORDER", f"investments.{oid}.in_service",
                                          "Ввод в эксплуатацию не может быть раньше последнего платежа CAPEX"))
        if list(dec.stage_dates) != sorted(dec.stage_dates):
            issues.append(ValidationIssue("DATE_ORDER", f"investments.{oid}.stage_dates",
                                          "Даты платежей должны идти в порядке этапов (по возрастанию)"))

    if scenario is not None:
        for (sid, y) in list(scenario.price_multiplier) + list(scenario.delivery_share):
            if sid not in case.sources:
                issues.append(ValidationIssue("UNKNOWN_SOURCE", f"scenario.{scenario.scenario_id}",
                                              f"Сценарий ссылается на неизвестный канал {sid!r}"))
        for tbl, nm in ((scenario.demand_multiplier, "demand_multiplier"),):
            for y, v in tbl.items():
                if _bad_number(v) or v < 0:
                    issues.append(ValidationIssue("BAD_MULTIPLIER", f"scenario.{nm}.{y}", f"Недопустимый множитель {v!r}"))
        for (sid, y), v in scenario.delivery_share.items():
            if _bad_number(v) or not 0 <= v <= 1:
                issues.append(ValidationIssue("BAD_SHARE", f"scenario.delivery_share.{sid}.{y}",
                                              f"Доля поставки должна быть 0..1, получено {v!r}"))
    return issues
