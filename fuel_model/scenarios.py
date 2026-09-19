"""Сценарии как наложения на копию кейса. Исходные данные не изменяются.

BASE и MANDATORY_STRESS одинаковы для всех команд. Низкий/высокий спрос - контрольные точки
чувствительности. Любая комбинация (стресс + высокий спрос, геополитика) - отдельный
исследовательский сценарий с явным правилом сочетания (combine): молчаливого сложения нет.
"""
from __future__ import annotations

from typing import Dict, Iterable, Tuple

from .errors import ScenarioConflict
from .model import Scenario

STRESS_YEARS = (2038, 2039, 2040)


def base() -> Scenario:
    return Scenario("BASE", "Стандартный сценарий", "Базовый спрос, исходные цены и параметры.",
                    kind="control", sl_is_benchmark=False, changes=())


def mandatory_stress() -> Scenario:
    return Scenario(
        "MANDATORY_STRESS", "Обязательный стресс", "Заданный организатором совместный стресс 2038-2040.",
        kind="control",
        demand_multiplier={y: 1.15 for y in STRESS_YEARS},
        price_multiplier={(s, y): 1.25 for s in ("A", "B") for y in (2038, 2039)},
        delivery_share={("D", 2038): 0.55, ("D", 2039): 0.75},
        loss_ceiling={y: 0.02 for y in STRESS_YEARS},
        sl_is_benchmark=True,
        changes=("Общий и критический спрос x1.15 в 2038-2040",
                 "Переменная цена Earth-Core/Earth-Flex x1.25 в 2038-2039",
                 "Фактическая поставка Lunar-ISRU: 55% плана в 2038, 75% в 2039 (без повторного умножения на надёжность)",
                 "Предел потерь <=2% валового поступления с 2038 г."))


def low_demand() -> Scenario:
    return Scenario("LOW_DEMAND", "Низкий спрос", "Проверка чувствительности: низкий общий спрос.",
                    kind="overlay", demand_variant="low", sl_is_benchmark=True,
                    changes=("Общий спрос - вариант low; доля критического сохраняется",))


def high_demand() -> Scenario:
    return Scenario("HIGH_DEMAND", "Высокий спрос", "Проверка чувствительности: высокий общий спрос.",
                    kind="overlay", demand_variant="high", sl_is_benchmark=True,
                    changes=("Общий спрос - вариант high; доля критического сохраняется",))


def price_shock(scenario_id: str, name: str, sources: Iterable[str], years: Iterable[int],
                factor: float, description: str = "") -> Scenario:
    """Исследовательское наложение: множитель на переменную цену каналов (риск-сценарий, геополитика)."""
    srcs, yrs = list(sources), list(years)
    return Scenario(scenario_id, name, description, kind="research",
                    price_multiplier={(s, y): factor for s in srcs for y in yrs}, sl_is_benchmark=True,
                    changes=(f"Цена {','.join(srcs)} x{factor} в годы {yrs}",))


def demand_shock(scenario_id: str, name: str, years: Iterable[int], factor: float) -> Scenario:
    yrs = list(years)
    return Scenario(scenario_id, name, "", kind="research", demand_multiplier={y: factor for y in yrs},
                    sl_is_benchmark=True, changes=(f"Спрос x{factor} в годы {yrs}",))


def delivery_shock(scenario_id: str, name: str, source: str, years: Iterable[int], share: float) -> Scenario:
    yrs = list(years)
    return Scenario(scenario_id, name, "", kind="research", delivery_share={(source, y): share for y in yrs},
                    sl_is_benchmark=True, changes=(f"Фактическая поставка {source}: {share:.0%} плана в годы {yrs}",))


def _merge(name: str, a: Dict, b: Dict) -> Dict:
    clash = sorted(set(a) & set(b))
    if clash:
        raise ScenarioConflict(f"{name}: оба наложения меняют {clash}; задайте явное правило сочетания")
    return {**a, **b}


def combine(scenario_id: str, name: str, a: Scenario, b: Scenario) -> Scenario:
    """Явное сочетание двух наложений. Пересечение по одному параметру - ошибка, а не молчаливое умножение."""
    if a.demand_variant != "base" and b.demand_variant != "base" and a.demand_variant != b.demand_variant:
        raise ScenarioConflict("Разные варианты спроса нельзя объединить")
    variant = a.demand_variant if a.demand_variant != "base" else b.demand_variant
    return Scenario(
        scenario_id, name, f"Сочетание {a.scenario_id} + {b.scenario_id}", kind="research", demand_variant=variant,
        demand_multiplier=_merge("demand_multiplier", dict(a.demand_multiplier), dict(b.demand_multiplier)),
        price_multiplier=_merge("price_multiplier", dict(a.price_multiplier), dict(b.price_multiplier)),
        delivery_share=_merge("delivery_share", dict(a.delivery_share), dict(b.delivery_share)),
        loss_ceiling=_merge("loss_ceiling", dict(a.loss_ceiling), dict(b.loss_ceiling)),
        sl_is_benchmark=a.sl_is_benchmark or b.sl_is_benchmark, changes=tuple(a.changes) + tuple(b.changes))


BUILTIN = {"BASE": base, "MANDATORY_STRESS": mandatory_stress, "LOW_DEMAND": low_demand, "HIGH_DEMAND": high_demand}


def get(scenario_id: str) -> Scenario:
    if scenario_id not in BUILTIN:
        raise KeyError(f"Неизвестный сценарий {scenario_id!r}; доступны: {sorted(BUILTIN)}")
    return BUILTIN[scenario_id]()
