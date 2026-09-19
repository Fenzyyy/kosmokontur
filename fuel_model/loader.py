"""Загрузка Case из CSV (data/case_input) и конфигов (configs/).

Новый источник снабжения добавляется строкой в sources.csv (+ записью в source_roles.json,
если у канала есть инвестиционный шаг): расчётная логика при этом не меняется.
Заголовки sources.csv совпадают со стартовым репозиторием организаторов; принимаются и короткие имена.
"""
from __future__ import annotations

import csv
import json
import os
from dataclasses import fields
from typing import Dict, List, Optional

from .model import (Assumptions, Case, Constraints, DemandRow, InvestmentOption, Source,
                    SourceRole, StorageMode)

_SRC_ALIASES = {
    "capacity": ("capacity_t_per_year", "capacity"),
    "variable_cost": ("variable_cost_mln_per_t", "variable_cost"),
    "reservation_rate": ("reservation_rate_mln_per_t_year_capacity", "reservation_rate"),
    "top_share": ("take_or_pay_share", "top_share"),
    "lead_time_min": ("lead_time_min_value", "lead_time_min"),
    "lead_time_max": ("lead_time_max_value", "lead_time_max"),
}


def _rows(path: str) -> List[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


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
        raise ValueError(f"В строке {row!r} нет обязательного поля {keys[0]!r}")
    return v


def _share(name: str, value: float) -> float:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name}: доля должна быть в диапазоне 0..1, получено {value} (проценты вводить как 0.7, а не 70)")
    return value


def load_case(data_dir: str = "data/case_input", config_dir: str = "configs") -> Case:
    demand = {}
    for r in _rows(os.path.join(data_dir, "demand.csv")):
        d = DemandRow(int(r["year"]), _need(r, "base_total"), _need(r, "base_critical"),
                      _need(r, "low_total"), _need(r, "high_total"))
        if d.base_critical > d.base_total:
            raise ValueError(f"{d.year}: критический спрос больше общего (он входит в общий)")
        demand[d.year] = d

    sources: Dict[str, Source] = {}
    for r in _rows(os.path.join(data_dir, "sources.csv")):
        sid = r["source_id"].strip()
        g = {k: _f(r, *names) for k, names in _SRC_ALIASES.items()}
        sources[sid] = Source(
            source_id=sid, name=r.get("name", sid), capacity=g["capacity"], variable_cost=g["variable_cost"],
            reservation_rate=g["reservation_rate"] or 0.0,
            top_share=_share(f"{sid}.take_or_pay_share", g["top_share"] or 0.0),
            lead_time_min=g["lead_time_min"] or 0.0, lead_time_max=g["lead_time_max"] or g["lead_time_min"] or 0.0,
            lead_time_unit=(r.get("lead_time_unit") or "month").strip(),
            reliability_profile=r.get("reliability_profile", "") or "",
            available_from_year=_i(r, "available_from_year"),
            status=r.get("status", "") or "", notes=r.get("notes", "") or "")

    storage: Dict[str, StorageMode] = {}
    for r in _rows(os.path.join(data_dir, "storage.csv")):
        storage[r["mode_id"]] = StorageMode(
            r["mode_id"], r.get("name", r["mode_id"]), _need(r, "capacity"),
            _share(f"{r['mode_id']}.loss_rate", _need(r, "loss_rate")), _need(r, "holding_cost"),
            _f(r, "capex", default=0.0), _f(r, "fixed_opex", default=0.0))

    options: Dict[str, InvestmentOption] = {}
    for r in _rows(os.path.join(data_dir, "investments.csv")):
        labels = tuple(x.strip() for x in r["stage_labels"].split(";") if x.strip())
        amounts = tuple(float(x) for x in r["stage_amounts"].split(";") if x.strip())
        if len(labels) != len(amounts):
            raise ValueError(f"{r['option_id']}: число stage_labels и stage_amounts должно совпадать")
        options[r["option_id"]] = InvestmentOption(
            option_id=r["option_id"], kind=r["kind"], target_id=r["target_id"],
            stage_labels=labels, stage_amounts=amounts, fixed_opex=_f(r, "fixed_opex", default=0.0),
            earliest_stage_year=_i(r, "earliest_stage_year"), latest_capex_year=_i(r, "latest_capex_year"),
            earliest_in_service_year=_i(r, "earliest_in_service_year"),
            min_build_months=_f(r, "min_build_months", default=0.0), max_build_months=_f(r, "max_build_months", default=0.0),
            notes=r.get("notes", "") or "")

    c_kwargs = {}
    ctypes = {f.name: f.type for f in fields(Constraints)}
    for r in _rows(os.path.join(data_dir, "constraints.csv")):
        k, v = r["key"], r["value"]
        if k not in ctypes:
            raise ValueError(f"constraints.csv: неизвестный ключ {k!r}")
        t = str(ctypes[k])
        c_kwargs[k] = v if "str" in t else (int(float(v)) if "int" in t else float(v))
    constraints = Constraints(**c_kwargs)

    roles: Dict[str, SourceRole] = {}
    p = os.path.join(config_dir, "source_roles.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as fh:
            for sid, v in json.load(fh).items():
                if not sid.startswith("_"):
                    roles[sid] = SourceRole(v.get("requires_option", ""), v.get("lead_time_semantics", "order"))

    assumptions = load_assumptions(os.path.join(config_dir, "assumptions.json"))
    for sid, role in roles.items():
        if sid not in sources:
            raise ValueError(f"source_roles.json: канал {sid!r} отсутствует в sources.csv")
        if role.requires_option and role.requires_option not in options:
            raise ValueError(f"source_roles.json: опция {role.requires_option!r} канала {sid!r} не найдена в investments.csv")
    base_storage = "BASE_STORAGE" if "BASE_STORAGE" in storage else next(iter(storage))
    return Case(demand, sources, storage, options, constraints, roles, assumptions, base_storage)


def load_assumptions(path: str) -> Assumptions:
    if not os.path.exists(path):
        return Assumptions()
    with open(path, encoding="utf-8") as fh:
        raw = {k: v for k, v in json.load(fh).items() if not k.startswith("_")}
    known = {f.name for f in fields(Assumptions)}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"assumptions.json: неизвестные параметры {sorted(unknown)}")
    return Assumptions(**raw)
