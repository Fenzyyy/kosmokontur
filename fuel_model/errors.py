"""Каталог кодов нарушений и ошибок ввода.

Два разных класса проблем:
  * ValidationIssue — план или ввод некорректны как данные (неизвестный канал, отрицательный объём).
    Расчёт не запускается, пользователь получает понятное сообщение с полем.
  * Violation — расчёт выполнен, но ограничение кейса нарушено. Есть год, величина и причина.
    Неисполнимый план показывается как неисполнимый, а не «чинится».
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

# Коды нарушений ограничений (Violation.code) -> краткое описание правила
VIOLATION_CATALOG = {
    "CAPACITY_EXCEEDED": "Зарезервированная мощность превышает максимальную мощность канала",
    "ORDER_EXCEEDS_RESERVED": "Заказанный объём превышает зарезервированный (договорно доступный) объём периода",
    "SOURCE_NOT_AVAILABLE": "Канал недоступен в этом году (нет ввода, срока или моментов поставки), но заказан объём",
    "LEAD_TIME_VIOLATION": "Нарушен срок поставки или ввода (lead time)",
    "LEAD_TIME_OPTIMISTIC": "Срок ввода короче верхней границы диапазона lead time (предупреждение)",
    "INVESTMENT_TIMING": "Нарушено ограничение по срокам инвестиционного решения",
    "STORAGE_OVERFLOW": "Физический запас превышает ёмкость действующего хранилища",
    "INITIAL_STOCK_EXCEEDS_STORAGE": "Начальный запас превышает ёмкость базового хранилища",
    "RESERVE_45D_SHORT": "Физический запас на начало года меньше 45-дневного резерва",
    "SL_TOTAL_LOW": "Уровень обслуживания общего спроса ниже требования",
    "SL_CRITICAL_LOW": "Уровень обслуживания критического спроса ниже требования",
    "CAPEX_LIMIT_CUMULATIVE": "Накопленный CAPEX превышает лимит на дату",
    "CAPEX_LIMIT_TOTAL": "Суммарный CAPEX превышает общий лимит",
    "EMERGENCY_BASE_STREAK": "Emergency используется как базовый канал слишком много лет подряд",
    "LOSS_CEILING_EXCEEDED": "Потери превышают предел от годового оборота (обязательный стресс)",
}

SEVERITY_HARD = "HARD"            # ограничение обязательно в этом сценарии -> план неисполним
SEVERITY_BENCHMARK = "BENCHMARK"  # ориентир устойчивости: отклонение показывается числом
SEVERITY_WARNING = "WARNING"      # предупреждение, не делает план неисполнимым


@dataclass(frozen=True)
class Violation:
    code: str
    severity: str
    message: str
    year: Optional[int] = None
    subject: str = ""          # канал / опция / показатель
    value: Optional[float] = None
    limit: Optional[float] = None
    excess: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "code": self.code, "severity": self.severity, "year": self.year, "subject": self.subject,
            "value": self.value, "limit": self.limit, "excess": self.excess, "message": self.message,
        }


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    field: str
    message: str

    def to_dict(self) -> dict:
        return {"code": self.code, "field": self.field, "message": self.message}


class PlanValidationError(Exception):
    """Ввод плана/сценария некорректен: расчёт не выполняется."""

    def __init__(self, issues: List[ValidationIssue]):
        self.issues = list(issues)
        text = "; ".join(f"[{i.code}] {i.field}: {i.message}" for i in self.issues)
        super().__init__(text)


class ScenarioConflict(Exception):
    """Два наложения сценария меняют один и тот же параметр без явного правила сочетания."""
