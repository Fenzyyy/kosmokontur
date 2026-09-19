"""Командная строка: расчёт плана, сравнение сценариев, выгрузка CSV.

  python -m kosmo.run --plan results/plans/demo_earth_base.json --scenario BASE
  python -m kosmo.run --plan results/plans/demo_earth_base.json --compare BASE,MANDATORY_STRESS,LOW_DEMAND,HIGH_DEMAND
  python -m kosmo.run --plan ... --scenario MANDATORY_STRESS --export results/exports
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from typing import Iterable, List

from . import scenarios as S
from .analysis import compare_scenarios
from .engine import evaluate
from .errors import PlanValidationError
from .loader import load_case
from .model import Plan, Result


def write_csv(path: str, rows: List[dict], columns: Iterable[str] = None) -> None:
    rows = list(rows)
    cols = list(columns) if columns else (list(rows[0].keys()) if rows else [])
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def export_result(result: Result, out_dir: str) -> List[str]:
    """CSV с идентификатором сценария, единицами и допущениями: yearly, costs, sources, violations, trace."""
    os.makedirs(out_dir, exist_ok=True)
    tag = f"{result.meta['plan_id']}__{result.meta['scenario_id']}"
    common = {"scenario_id": result.meta["scenario_id"], "plan_id": result.meta["plan_id"],
              "input_version": result.meta["input_version"], "units": "т; млн у.е. (цены 2035)"}
    paths = []

    def dump(name, rows):
        p = os.path.join(out_dir, f"{tag}__{name}.csv")
        write_csv(p, [{**common, **r} for r in rows])
        paths.append(p)

    dump("yearly", [{k: v for k, v in r.items() if k != "sources"} for r in result.yearly])
    dump("costs", [{k: v for k, v in r.items() if k != "sources"} for r in result.costs])
    src_rows = []
    for y_row, c_row in zip(result.yearly, result.costs):
        for sid, d in y_row["sources"].items():
            src_rows.append({"year": y_row["year"], "source": sid, **d, **c_row["sources"][sid]})
    dump("sources", src_rows)
    dump("violations", [v.to_dict() for v in result.violations])
    dump("supply_schedule", result.supply_schedule)
    dump("inventory_trace", result.inventory_trace)
    dump("kpis", [result.kpis])
    return paths


def print_result(r: Result) -> None:
    m = r.meta
    print(f"\n=== план {m['plan_id']} | сценарий {m['scenario_id']} | {'ИСПОЛНИМ' if r.feasible else 'НЕИСПОЛНИМ'} ===")
    for ch in m["scenario_changes"]:
        print(f"  * {ch}")
    print(f"{'год':>5} {'спрос':>7} {'крит.':>6} {'обсл.':>7} {'SLобщ':>6} {'SLкр':>6} {'дефиц':>6} {'запас0':>7} "
          f"{'запас1':>7} {'пик':>6} {'потери':>6} {'резерв':>6}")
    for y in r.yearly:
        print(f"{y['year']:>5} {y['demand_total']:7.1f} {y['demand_critical']:6.1f} {y['served_total']:7.1f} "
              f"{y['sl_total']:6.1%} {y['sl_critical']:6.1%} {y['shortage_total']:6.1f} {y['inventory_open']:7.1f} "
              f"{y['inventory_close']:7.1f} {y['inventory_peak']:6.1f} {y['loss_share']:6.1%} {y['reserve_required']:6.1f}")
    print(f"{'год':>5} {'CAPEX':>7} {'закупка':>8} {'резерв':>7} {'хранен.':>7} {'OPEX':>6} {'итого':>8} {'PV':>8}")
    for c in r.costs:
        print(f"{c['year']:>5} {c['capex']:7.1f} {c['procurement']:8.1f} {c['reservation']:7.1f} {c['holding']:7.1f} "
              f"{c['fixed_opex']:6.1f} {c['total']:8.1f} {c['pv_total']:8.1f}")
    k = r.kpis
    print(f"ИТОГО: затраты {k['total_cost']:.1f}, PV {k['pv_cost']:.1f} млн у.е.; обслужено {k['served_total']:.1f} т; "
          f"дефицит {k['shortage_total']:.2f} т; стоимость обслуженной т {k['cost_per_served_ton']:.3f}")
    if r.violations:
        print("Нарушения и предупреждения:")
        for v in r.violations:
            print(f"  [{v.severity}] {v.code}: {v.message}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Топливный космоконтур 2035: расчёт плана")
    ap.add_argument("--plan", required=True)
    ap.add_argument("--scenario", default="BASE")
    ap.add_argument("--compare", help="список сценариев через запятую")
    ap.add_argument("--data", default="data/case_input")
    ap.add_argument("--config", default="configs")
    ap.add_argument("--export", help="каталог для выгрузки CSV")
    args = ap.parse_args(argv)
    case = load_case(args.data, args.config)
    plan = Plan.load(args.plan)
    try:
        if args.compare:
            rows = compare_scenarios(case, plan, [S.get(x.strip()) for x in args.compare.split(",")])
            print(f"{'сценарий':18s} {'исп.':5s} {'затраты':>9s} {'PV':>9s} {'дефицит':>8s} {'min SLкр':>9s} {'HARD':>5s} {'ориент.':>8s}")
            for r in rows:
                print(f"{r['scenario_id']:18s} {'да' if r['feasible'] else 'НЕТ':5s} {r['total_cost']:9.1f} {r['pv_cost']:9.1f} "
                      f"{r['shortage_total']:8.2f} {r['min_sl_critical']:9.1%} {r['hard_violations']:5d} {r['benchmark_misses']:8d}")
            if args.export:
                os.makedirs(args.export, exist_ok=True)
                write_csv(os.path.join(args.export, f"{plan.plan_id}__comparison.csv"), rows)
            return 0
        result = evaluate(case, plan, S.get(args.scenario))
    except PlanValidationError as exc:
        print("ОШИБКА ВВОДА (расчёт не запущен):")
        for i in exc.issues:
            print(f"  [{i.code}] {i.field}: {i.message}")
        return 2
    print_result(result)
    if args.export:
        for p in export_result(result, args.export):
            print("выгружено:", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
