"""Чистые формулы контрольных правил кейса.

Каждая функция реализует ровно одно правило из постановки / CALCULATION_RULES.md.
Движок вызывает эти же функции, а тесты V01–V10 проверяют именно их.
Единицы: тонны (т), млн условных денежных единиц (млн у.е.) в ценах 2035 года.
"""
from __future__ import annotations

from typing import Tuple

EPS = 1e-9


# --- Материальный баланс -----------------------------------------------------
def closing_inventory(opening: float, delivered: float, losses: float, served: float) -> float:
    """I_end = I_start + Q_delivered - Losses - Q_served."""
    return opening + delivered - losses - served


def serve_demand(available: float, demand_critical: float, demand_total: float) -> Tuple[float, float]:
    """Выдача из физического запаса. Критический спрос обслуживается первым.

    Возвращает (served_critical, served_total). Критический спрос ВХОДИТ в общий,
    поэтому served_total включает served_critical и не суммируется с ним повторно.
    """
    if demand_critical > demand_total + EPS:
        raise ValueError("Критический спрос не может превышать общий (он входит в общий)")
    available = max(0.0, available)
    served_c = min(available, demand_critical)
    served_nc = min(available - served_c, demand_total - demand_critical)
    return served_c, served_c + served_nc


def shortage(demand: float, served: float) -> float:
    """Shortage = max(0, Demand - Q_served). Дефицит — отдельная величина, не отрицательный запас."""
    return max(0.0, demand - served)


def combined_total_demand(total: float, critical: float) -> float:
    """Критический спрос — подмножество общего: общий спрос не равен total + critical."""
    if critical > total + EPS:
        raise ValueError("Критический спрос не может превышать общий")
    return total


# --- Потери ------------------------------------------------------------------
def losses(throughput: float, loss_rate: float) -> float:
    """Losses = Throughput * loss_rate. Throughput — валовое поступление за период.
    Потери начисляются один раз на поступление, но не на остаток запаса."""
    return throughput * loss_rate


# --- Резерв 45 дней ------------------------------------------------------------
def reserve_requirement(annual_total_demand: float, days: float = 45, year_days: float = 365) -> float:
    """R = годовой общий спрос × 45 / 365."""
    return annual_total_demand * days / year_days


# --- Контракты ---------------------------------------------------------------
def payable_volume(order: float, top_share: float, reserved_period_volume: float) -> float:
    """Q_pay = max(Q_order, take_or_pay_share × Q_reserved_period)."""
    return max(order, top_share * reserved_period_volume)


def variable_payment(price: float, order: float, top_share: float, reserved_period_volume: float) -> float:
    """VariablePayment = price × Q_pay. Take-or-pay уже внутри max(): второй раз не добавляется."""
    return price * payable_volume(order, top_share, reserved_period_volume)


def reservation_payment(rate: float, annual_reserved_capacity: float, period_fraction: float) -> float:
    """ReservationPayment = rate × annual_reserved_capacity × period_fraction.
    Тариф — млн у.е. за 1 т/год мощности; за неполный год — пропорционально длительности."""
    return rate * annual_reserved_capacity * period_fraction


# --- Ограничения мощности ------------------------------------------------------
def capacity_excess(reserved: float, capacity: float) -> float:
    """Превышение резерва над мощностью канала, т/год (0, если превышения нет)."""
    return max(0.0, reserved - capacity)


# --- Поставки в стрессе ----------------------------------------------------------
def stress_delivery(planned: float, actual_share: float) -> float:
    """Фактическая поставка в стрессе = план × заданная доля.
    Коэффициент надёжности НЕ умножается повторно (это отдельный риск-блок)."""
    return planned * actual_share


# --- Дисконтирование ---------------------------------------------------------------
def discount_factor(rate: float, year: int, base_year: int) -> float:
    """PV = CF / (1 + r)^(t - t0). Ставка — реальная; поток года y приводится к моменту t0 = base_year."""
    return 1.0 / (1.0 + rate) ** (year - base_year)


# --- Уровень обслуживания ----------------------------------------------------------
def service_level(served: float, demand: float) -> float:
    """SL = served / demand; при нулевом спросе определён явно как 1.0 (нет спроса — нет недопоставки)."""
    if demand <= 0:
        return 1.0
    return served / demand
