"""Загрузка Case из CSV (data/case_input) и конфигов (configs/).

Загрузчик принимает как нормализованный формат текущей модели, так и исходные
таблицы организаторов: supply_sources.csv, storage_options.csv и
investment_options.csv. Это позволяет хранить исходные данные без ручной
перепаковки перед запуском модели.
"""
from __future__ import annotations

import csv
import json
import os
from dataclasses import fields
from typing import Dict, List, Optional

from .model import (
    Assumptions,
    Case,
    Constraints,
    DemandRow,
    InvestmentOption,
    Source,
    SourceRole,
    StorageMode,
)

_SRC_ALIASES = {
    "capacity": ("capacity_t_per_year", "capacity"),
    "variable_cost": ("variable_cost_mln_per_t", "variable_cost"),
    "reservation_rate": (
        "reservation_rate_mln_per_t_year_capacity",
        "reservation_rate",
    ),
    "top_share": ("take_or_pay_share", "top_share"),
    "lead_time_min": ("lead_time_min_value", "lead_time_min"),
    "lead_time_max": ("lead_time_max_value", "lead_time_max"),
}


def _rows(path: str) -> List[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _pick_file(data_dir: str, *names: str) -> str:
    for name in names:
        path = os.path.join(data_dir, name)
        if os.path.exists(path):
            return path
    raise FileNotFoundError(
        f"Не найден файл в {data_dir!r}; ожидается один из: {', '.join(names)}"
    )


def _f(row: dict, *keys: str, default: Optional[float] = None) -> Optional[float]:
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            return float(v)
    return default


def _i(row: dict, key: str) -> Optional[int]:
    v = row.get(key)
    return None if v in (None, "") else int(float(v))


def _need(row: dict, *keys: str) -> float:
    v = _f(row, *keys)
    if v is None:
        raise ValueError(
            f"В строке {row!r} нет обязательного поля {keys[0]!r}"
        )
    return v


def _share(name: str, value: float) -> float:
    if not 0.0 <= value <= 1.0:
        raise ValueError(
            f"{name}: доля должна быть в диапазоне 0..1, получено {value}"
        )
    return value


def _load_demand(data_dir: str) -> Dict[int, DemandRow]:
    rows = _rows(_pick_file(data_dir, "demand.csv"))
    demand: Dict[int, DemandRow] = {}

    for r in rows:
        d = DemandRow(
            int(r["year"]),
            _need(r, "base_total", "base_total_t"),
            _need(r, "base_critical", "base_critical_t"),
            _need(r, "low_total", "low_total_t"),
            _need(r, "high_total", "high_total_t"),
        )
        if d.base_critical > d.base_total:
            raise ValueError(
                f"{d.year}: критический спрос больше общего "
                f"(он входит в общий)"
            )
        demand[d.year] = d

    if not demand:
        raise ValueError("demand.csv не содержит строк")
    return demand


def _load_sources(data_dir: str) -> Dict[str, Source]:
    rows = _rows(_pick_file(data_dir, "sources.csv", "supply_sources.csv"))
    sources: Dict[str, Source] = {}

    for r in rows:
        sid = r["source_id"].strip()
        g = {k: _f(r, *names) for k, names in _SRC_ALIASES.items()}

        sources[sid] = Source(
            source_id=sid,
            name=r.get("name", sid),
            capacity=_need(r, *_SRC_ALIASES["capacity"]),
            variable_cost=_need(r, *_SRC_ALIASES["variable_cost"]),
            reservation_rate=g["reservation_rate"] or 0.0,
            top_share=_share(
                f"{sid}.take_or_pay_share",
                g["top_share"] or 0.0,
            ),
            lead_time_min=g["lead_time_min"] or 0.0,
            lead_time_max=(
                g["lead_time_max"]
                if g["lead_time_max"] is not None
                else g["lead_time_min"] or 0.0
            ),
            lead_time_unit=(r.get("lead_time_unit") or "month").strip(),
            reliability_profile=r.get("reliability_profile", "") or "",
            available_from_year=_i(r, "available_from_year"),
            status=r.get("status", "") or "",
            notes=r.get("notes", "") or "",
        )

    if not sources:
        raise ValueError("sources/supply_sources.csv не содержит каналов")
    return sources


def _load_storage(data_dir: str) -> Dict[str, StorageMode]:
    rows = _rows(_pick_file(data_dir, "storage.csv", "storage_options.csv"))
    storage: Dict[str, StorageMode] = {}

    for r in rows:
        mode_id = (r.get("mode_id") or r.get("storage_id") or "").strip()
        if not mode_id:
            raise ValueError(f"У строки storage нет mode_id/storage_id: {r!r}")

        storage[mode_id] = StorageMode(
            mode_id=mode_id,
            name=r.get("name", mode_id),
            capacity=_need(r, "capacity", "capacity_t"),
            loss_rate=_share(
                f"{mode_id}.loss_rate",
                _need(r, "loss_rate", "loss_rate_on_throughput"),
            ),
            holding_cost=_need(
                r,
                "holding_cost",
                "holding_cost_mln_per_t_year",
            ),
            capex=_f(r, "capex", "capex_mln", default=0.0),
            fixed_opex=_f(
                r,
                "fixed_opex",
                "fixed_opex_mln_per_year",
                default=0.0,
            ),
        )

    if not storage:
        raise ValueError("storage/storage_options.csv не содержит режимов")
    return storage


def _organizer_investment_row(r: dict) -> tuple:
    """Перевести investment_options.csv в этапы модели."""
    iid = r["investment_id"].strip()

    fee = _f(r, "option_fee_mln", default=0.0) or 0.0
    exercise = _f(r, "exercise_cost_mln", default=0.0) or 0.0

    if fee > 0 and exercise > 0:
        labels = ("option", "exercise")
        amounts = (fee, exercise)
    elif exercise > 0:
        labels = ("exercise",)
        amounts = (exercise,)
    elif fee > 0:
        labels = ("option",)
        amounts = (fee,)
    else:
        raise ValueError(f"{iid}: в инвестиционной опции нет CAPEX")

    # Ограничения, явно заданные постановкой через commissioning_rule/notes.
    if iid == "EARTH_NEW":
        kind = "source"
        target_id = "EARTH_NEW"
        earliest_stage_year = 2035
        latest_capex_year = None
        earliest_in_service_year = None
        min_build_months = 18.0
        max_build_months = 24.0
    elif iid == "LUNAR_ISRU":
        kind = "source"
        target_id = "LUNAR_ISRU"
        earliest_stage_year = 2035
        latest_capex_year = 2037
        earliest_in_service_year = 2038
        min_build_months = 0.0
        max_build_months = 0.0
    elif iid == "ZBO":
        kind = "storage"
        target_id = "ZBO"
        earliest_stage_year = 2036
        latest_capex_year = None
        earliest_in_service_year = 2036
        min_build_months = 0.0
        max_build_months = 0.0
    else:
        kind = "storage" if str(r.get("name", "")).lower().find("storage") >= 0 else "source"
        target_id = iid
        earliest_stage_year = None
        latest_capex_year = None
        earliest_in_service_year = None
        min_build_months = 0.0
        max_build_months = 0.0

    return (
        iid,
        kind,
        target_id,
        labels,
        amounts,
        _f(
            r,
            "fixed_opex_mln_per_year",
            "fixed_opex",
            default=0.0,
        ) or 0.0,
        earliest_stage_year,
        latest_capex_year,
        earliest_in_service_year,
        min_build_months,
        max_build_months,
    )


def _load_options(data_dir: str) -> Dict[str, InvestmentOption]:
    rows = _rows(
        _pick_file(data_dir, "investments.csv", "investment_options.csv")
    )
    options: Dict[str, InvestmentOption] = {}

    for r in rows:
        if "stage_labels" in r and "stage_amounts" in r:
            oid = r["option_id"].strip()
            labels = tuple(
                x.strip()
                for x in r["stage_labels"].split(";")
                if x.strip()
            )
            amounts = tuple(
                float(x)
                for x in r["stage_amounts"].split(";")
                if x.strip()
            )
            fixed_opex = _f(r, "fixed_opex", default=0.0) or 0.0
            kind = r["kind"]
            target_id = r["target_id"]
            earliest_stage_year = _i(r, "earliest_stage_year")
            latest_capex_year = _i(r, "latest_capex_year")
            earliest_service = _i(r, "earliest_in_service_year")
            min_build_months = _f(r, "min_build_months", default=0.0) or 0.0
            max_build_months = _f(r, "max_build_months", default=0.0) or 0.0
            notes = r.get("notes", "") or ""
        else:
            (
                oid,
                kind,
                target_id,
                labels,
                amounts,
                fixed_opex,
                earliest_stage_year,
                latest_capex_year,
                earliest_service,
                min_build_months,
                max_build_months,
            ) = _organizer_investment_row(r)
            notes = r.get("notes", "") or ""

        if len(labels) != len(amounts):
            raise ValueError(
                f"{oid}: число этапов и сумм CAPEX должно совпадать"
            )

        options[oid] = InvestmentOption(
            option_id=oid,
            kind=kind,
            target_id=target_id,
            stage_labels=labels,
            stage_amounts=amounts,
            fixed_opex=fixed_opex,
            earliest_stage_year=earliest_stage_year,
            latest_capex_year=latest_capex_year,
            earliest_in_service_year=earliest_service,
            min_build_months=min_build_months,
            max_build_months=max_build_months,
            notes=notes,
        )

    if not options:
        raise ValueError("investments/investment_options.csv не содержит опций")
    return options


def _load_constraints(data_dir: str) -> Constraints:
    rows = _rows(_pick_file(data_dir, "constraints.csv"))

    # Нормализованный key/value формат.
    if rows and "key" in rows[0] and "value" in rows[0]:
        c_kwargs = {}
        ctypes = {f.name: f.type for f in fields(Constraints)}
        for r in rows:
            k, v = r["key"], r["value"]
            if k not in ctypes:
                raise ValueError(f"constraints.csv: неизвестный ключ {k!r}")
            t = str(ctypes[k])
            c_kwargs[k] = (
                v
                if "str" in t
                else int(float(v))
                if "int" in t
                else float(v)
            )
        return Constraints(**c_kwargs)

    # Исходный формат организатора.
    c_kwargs: Dict[str, object] = {}
    for r in rows:
        cid = (r.get("constraint_id") or "").strip()
        metric = (r.get("metric") or "").strip()
        value = float(r["value"])

        if cid == "BASE_CRITICAL_SERVICE" or metric == "critical_service_level":
            c_kwargs["sl_critical_min"] = value
        elif cid == "BASE_TOTAL_SERVICE" or metric == "total_service_level":
            c_kwargs["sl_total_min"] = value
        elif cid == "CAPEX_2037":
            c_kwargs["capex_cumulative_year"] = 2037
            c_kwargs["capex_cumulative_limit"] = value
        elif cid == "CAPEX_2040":
            c_kwargs["capex_total_limit"] = value
        elif cid == "RESERVE_45D" or metric == "reserve_equivalent_days":
            c_kwargs["reserve_days"] = value
        elif cid == "EMERGENCY_BASE_STREAK":
            c_kwargs["emergency_max_consecutive_years"] = int(value)
        elif cid == "STRESS_LOSS_LIMIT":
            # Stress-сценарий уже является частью постановки и использует 2%.
            # Проверяем согласованность внешних данных с реализованным сценарием.
            if abs(value - 0.02) > 1e-12:
                raise ValueError(
                    "STRESS_LOSS_LIMIT из constraints.csv отличается от "
                    "реализованного MANDATORY_STRESS (ожидается 0.02)"
                )

    return Constraints(**c_kwargs)


def load_case(data_dir: str = "data/case_input", config_dir: str = "configs") -> Case:
    demand = _load_demand(data_dir)
    sources = _load_sources(data_dir)
    storage = _load_storage(data_dir)
    options = _load_options(data_dir)
    constraints = _load_constraints(data_dir)

    roles: Dict[str, SourceRole] = {}
    p = os.path.join(config_dir, "source_roles.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as fh:
            for sid, v in json.load(fh).items():
                if not sid.startswith("_"):
                    roles[sid] = SourceRole(
                        v.get("requires_option", ""),
                        v.get("lead_time_semantics", "order"),
                    )

    assumptions = load_assumptions(os.path.join(config_dir, "assumptions.json"))

    for sid, role in roles.items():
        if sid not in sources:
            raise ValueError(
                f"source_roles.json: канал {sid!r} отсутствует в sources.csv"
            )
        if role.requires_option and role.requires_option not in options:
            raise ValueError(
                f"source_roles.json: опция {role.requires_option!r} "
                f"не найдена в investments.csv"
            )

    base_storage = (
        "BASE_STORAGE"
        if "BASE_STORAGE" in storage
        else "BASE"
        if "BASE" in storage
        else next(iter(storage))
    )

    return Case(
        demand=demand,
        sources=sources,
        storage=storage,
        options=options,
        constraints=constraints,
        source_roles=roles,
        assumptions=assumptions,
        base_storage_id=base_storage,
    )


def load_assumptions(path: str) -> Assumptions:
    if not os.path.exists(path):
        return Assumptions()

    with open(path, encoding="utf-8") as fh:
        raw = {
            k: v for k, v in json.load(fh).items()
            if not k.startswith("_")
        }

    known = {f.name for f in fields(Assumptions)}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(
            f"assumptions.json: неизвестные параметры {sorted(unknown)}"
        )
    return Assumptions(**raw)
