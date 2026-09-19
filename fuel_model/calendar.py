"""Модельный календарь.

Правило кейса: для перевода дней в тонны используется 365 дней в учебном году.
Поэтому весь контур работает на календаре из 365-дневных лет без високосных дней.
Индекс дня d = 0 соответствует 1 января первого года горизонта.
Отрицательные индексы описывают подготовительный период до горизонта.
"""
from __future__ import annotations

from typing import Tuple

DAYS_IN_YEAR = 365
MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
_CUM = [0]
for _n in MONTH_DAYS:
    _CUM.append(_CUM[-1] + _n)  # _CUM[m-1] = число дней до начала месяца m

_UNIT_DAYS = {"day": 1, "week": 7}


def lead_time_to_days(value: float, unit: str) -> int:
    """Перевод срока в дни. Соглашение (implementation assumption):
    месяц = 365/12 суток, год = 365 суток, неделя = 7 суток."""
    unit = unit.lower()
    if unit in _UNIT_DAYS:
        return int(round(value * _UNIT_DAYS[unit]))
    if unit == "month":
        return int(round(value * DAYS_IN_YEAR / 12))
    if unit == "year":
        return int(round(value * DAYS_IN_YEAR))
    raise ValueError(f"Неизвестная единица срока: {unit!r} (ожидается day/week/month/year)")


def parse_ym(text: str) -> Tuple[int, int]:
    """'2036-07' -> (2036, 7)."""
    try:
        y, m = str(text).split("-")[:2]
        y, m = int(y), int(m)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Дата должна быть в формате ГГГГ-ММ, получено {text!r}") from exc
    if not 1 <= m <= 12:
        raise ValueError(f"Месяц должен быть от 1 до 12, получено {m}")
    return y, m


def fmt_ym(ym: Tuple[int, int]) -> str:
    return f"{ym[0]:04d}-{ym[1]:02d}"


class ModelCalendar:
    def __init__(self, first_year: int, last_year: int):
        if last_year < first_year:
            raise ValueError("last_year < first_year")
        self.first_year = first_year
        self.last_year = last_year
        self.n_years = last_year - first_year + 1
        self.n_days = self.n_years * DAYS_IN_YEAR

    # --- перевод дат в индексы дней и обратно
    def day(self, year: int, month: int = 1, dom: int = 1) -> int:
        return (year - self.first_year) * DAYS_IN_YEAR + _CUM[month - 1] + (dom - 1)

    def ymd(self, day: int) -> Tuple[int, int, int]:
        y_off, doy = divmod(day, DAYS_IN_YEAR)
        month = 12
        for m in range(12):
            if doy < _CUM[m + 1]:
                month = m + 1
                break
        return self.first_year + y_off, month, doy - _CUM[month - 1] + 1

    def year_of(self, day: int) -> int:
        return self.first_year + day // DAYS_IN_YEAR

    def year_bounds(self, year: int) -> Tuple[int, int]:
        """[start, end) индексы дней года."""
        s = self.day(year)
        return s, s + DAYS_IN_YEAR

    def month_starts(self, year: int):
        return [self.day(year, m) for m in range(1, 13)]

    def add_months(self, day: int, n: int) -> int:
        y, m, dom = self.ymd(day)
        idx = y * 12 + (m - 1) + n
        ny, nm = divmod(idx, 12)
        nm += 1
        return self.day(ny, nm, min(dom, MONTH_DAYS[nm - 1]))

    def add_lead(self, day: int, value: float, unit: str) -> int:
        """Сдвиг даты на срок: месяцы — календарные, недели и дни — точные."""
        if unit.lower() == "month" and float(value).is_integer():
            return self.add_months(day, int(value))
        return day + lead_time_to_days(value, unit)

    def fmt(self, day: int) -> str:
        y, m, d = self.ymd(day)
        return f"{y:04d}-{m:02d}-{d:02d}"

    def fraction_available(self, year: int, avail_day) -> float:
        """Доля года, в течение которой источник доступен (по дням)."""
        if avail_day is None:
            return 0.0
        s, e = self.year_bounds(year)
        start = max(s, avail_day)
        return max(0.0, (e - start) / DAYS_IN_YEAR)
