"""Единый механизм формирования графиков инвестиций.

InvestmentOption хранит ограничения и параметры этапов, а InvestmentDecision
является уже конкретным решением Plan. Этот модуль — единственная точка, где
из CASE_INPUT строится стандартный ранний инвестиционный график.

Один и тот же builder используется optimizer и web API, поэтому UI не должен
воспроизводить инвестиционную логику самостоятельно.
"""
from __future__ import annotations

from typing import Mapping, Optional, Sequence, Tuple

from .model import Case, InvestmentDecision


YM = Tuple[int, int]


def month_add(year: int, month: int, months: int) -> YM:
    """Добавить целое число месяцев к (year, month)."""
    idx = year * 12 + (month - 1) + months
    new_year, new_month = divmod(idx, 12)
    return new_year, new_month + 1


def build_investment_decision(case: Case, option_id: str) -> Optional[InvestmentDecision]:
    """Построить самый ранний формально допустимый график CAPEX для опции.

    Правила:
    - первый этап не раньше earliest_stage_year и первого года горизонта;
    - все этапы проходят в первый месяц выбранного года;
    - последний этап должен быть не позже latest_capex_year;
    - ввод происходит после последнего этапа с выбранной границей lead time;
    - earliest_in_service_year задаёт нижнюю границу года ввода;
    - ввод за пределами горизонта делает график недопустимым.
    """
    if option_id not in case.options:
        raise KeyError(f"Неизвестная инвестиционная опция: {option_id}")

    option = case.options[option_id]

    stage_year = option.earliest_stage_year or case.first_year
    latest_year = option.latest_capex_year or case.last_year
    if stage_year > latest_year:
        return None

    stage_year = max(stage_year, case.first_year)
    stage_dates = tuple((stage_year, 1) for _ in option.stage_amounts)
    last_stage = stage_dates[-1] if stage_dates else (stage_year, 1)

    build_months = (
        option.max_build_months
        if case.assumptions.lead_time_choice == "max"
        else option.min_build_months
    )
    service_year, service_month = month_add(
        last_stage[0], last_stage[1], int(round(build_months))
    )

    if option.earliest_in_service_year is not None:
        service_year = max(service_year, option.earliest_in_service_year)

    if service_year < case.first_year:
        service_year, service_month = case.first_year, 1
    if service_year > case.last_year:
        return None

    return InvestmentDecision(
        stage_dates=stage_dates,
        in_service=(service_year, service_month),
    )


def build_investment_decisions(
    case: Case,
    option_ids: Sequence[str],
) -> Optional[dict[str, InvestmentDecision]]:
    """Построить стандартные решения для набора инвестиционных опций."""
    decisions: dict[str, InvestmentDecision] = {}
    for option_id in option_ids:
        decision = build_investment_decision(case, option_id)
        if decision is None:
            return None
        decisions[option_id] = decision
    return decisions


def decision_to_dict(decision: InvestmentDecision) -> dict:
    """Сериализуем InvestmentDecision в web/JSON-формат."""
    from .calendar import fmt_ym

    return {
        "stage_dates": [fmt_ym(value) for value in decision.stage_dates],
        "in_service": fmt_ym(decision.in_service),
    }
