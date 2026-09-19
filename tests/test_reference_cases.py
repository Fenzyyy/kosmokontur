"""Independent reference-vector tests derived from SpaceEconomyPolicy/test_oil."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from fuel_model import formulas as F
from fuel_model.errors import VIOLATION_CATALOG
from fuel_model.model import DemandRow, Source, StorageMode, Constraints, Case

from tools.reference_adapter import organizer_plan_to_plan


ROOT = Path(__file__).resolve().parent
REF_DIR = ROOT / "reference_cases"


def load_case(case_id: str) -> dict:
    for path in REF_DIR.glob(f"{case_id}_*.json"):
        return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(case_id)


class ReferenceCases(unittest.TestCase):
    def test_v01_material_balance(self):
        c = load_case("V01")
        i, e = c["inputs"], c["expected"]
        self.assertAlmostEqual(F.closing_inventory(i["opening_inventory_t"], i["delivered_t"], i["losses_t"], i["served_t"]), e["closing_inventory_t"])

    def test_v02_shortage_not_negative_inventory(self):
        c = load_case("V02")
        i, e = c["inputs"], c["expected"]
        _, served = F.serve_demand(i["delivered_t"], i["demand_critical_t"], i["demand_total_t"])
        self.assertAlmostEqual(served, e["served_t"])
        self.assertAlmostEqual(F.shortage(i["demand_total_t"], served), e["shortage_t"])
        self.assertAlmostEqual(F.closing_inventory(i["opening_inventory_t"], i["delivered_t"], i["losses_t"], served), e["closing_inventory_t"])

    def test_v03_take_or_pay(self):
        c = load_case("V03")
        i, e = c["inputs"], c["expected"]
        self.assertAlmostEqual(F.payable_volume(i["order_t"], i["take_or_pay_share"], i["reserved_capacity_period_t"]), e["payable_volume_t"])
        self.assertAlmostEqual(F.variable_payment(i["price_mln_per_t"], i["order_t"], i["take_or_pay_share"], i["reserved_capacity_period_t"]), e["variable_payment_mln"])

    def test_v04_no_double_take_or_pay(self):
        c = load_case("V04")
        i, e = c["inputs"], c["expected"]
        payment = F.variable_payment(i["price_mln_per_t"], i["order_t"], i["take_or_pay_share"], i["reserved_capacity_period_t"])
        self.assertAlmostEqual(payment, e["variable_payment_mln"])
        self.assertNotAlmostEqual(payment, e["double_counted_payment_mln"])

    def test_v05_reservation_proration(self):
        c = load_case("V05")
        i, e = c["inputs"], c["expected"]
        self.assertAlmostEqual(F.reservation_payment(i["reservation_rate_mln_per_t_year"], i["annual_reserved_capacity_t_per_year"], i["period_fraction"]), e["reservation_payment_mln"])

    def test_v06_losses_once_on_throughput(self):
        c = load_case("V06")
        i, e = c["inputs"], c["expected"]
        self.assertAlmostEqual(F.losses(i["gross_inflow_t"], i["loss_rate"]), e["losses_t"])

    def test_v07_45_day_reserve(self):
        c = load_case("V07")
        i, e = c["inputs"], c["expected"]
        self.assertAlmostEqual(F.reserve_requirement(i["annual_total_demand_t"], i["reserve_days"], i["year_days"]), e["reserve_t"])

    def test_v08_capacity_exceeded(self):
        c = load_case("V08")
        i, e = c["inputs"], c["expected"]
        self.assertAlmostEqual(F.capacity_excess(i["reserved_capacity_t_per_year"], i["capacity_t_per_year"]), e["excess_t_per_year"])
        self.assertIn(e["violation"], VIOLATION_CATALOG)

    def test_v09_critical_nested_in_total(self):
        c = load_case("V09")
        i, e = c["inputs"], c["expected"]
        self.assertAlmostEqual(F.combined_total_demand(i["total_demand_t"], i["critical_demand_t"]), e["total_demand_t"])

    def test_v10_stress_delivery(self):
        c = load_case("V10")
        i, e = c["inputs"], c["expected"]
        actual = F.stress_delivery(i["planned_delivery_t"], i["actual_delivery_share"])
        self.assertAlmostEqual(actual, e["actual_delivery_t"])
        self.assertNotAlmostEqual(actual, e["incorrect_double_reliability_t"])

    def test_organizer_empty_plan_adapts_to_native_plan(self):
        payload = json.loads((REF_DIR / "organizer" / "empty_plan.json").read_text(encoding="utf-8"))
        plan = organizer_plan_to_plan(payload)
        self.assertEqual(plan.plan_id, "example-empty-plan")
        self.assertEqual(plan.orders, {})
        self.assertEqual(plan.reserved, {})
        self.assertEqual(plan.initial_stock, [])
        self.assertEqual(plan.investments, {})

    def test_organizer_invalid_reservation_is_preserved_for_validation(self):
        payload = json.loads((REF_DIR / "organizer" / "negative_reservation.json").read_text(encoding="utf-8"))
        plan = organizer_plan_to_plan(payload)
        self.assertEqual(plan.reserved["Source-X"][2035], -1.0)

    def test_organizer_over_capacity_is_preserved_for_engine_checks(self):
        payload = json.loads((REF_DIR / "organizer" / "over_capacity.json").read_text(encoding="utf-8"))
        plan = organizer_plan_to_plan(payload)
        self.assertEqual(plan.reserved["Source-X"][2035], 12.0)

    def test_malformed_scenario_is_rejected_by_reference_format(self):
        payload = json.loads((REF_DIR / "organizer" / "malformed_scenario.json").read_text(encoding="utf-8"))
        self.assertNotIn("scenario_id", payload)

    def test_reference_vectors_are_synthetic_not_real_case(self):
        case = Case(
            demand={2035: DemandRow(2035, 10.0, 6.0, 8.0, 12.0)},
            sources={"Source-X": Source("Source-X", "Synthetic source", 10.0, 1.0, 0.4, 0.7, 0, 0, "day", available_from_year=2035)},
            storage={"BASE_STORAGE": StorageMode("BASE_STORAGE", "Synthetic storage", 100.0, 0, 0)},
            options={},
            constraints=Constraints(),
        )
        self.assertEqual(case.first_year, 2035)
        self.assertEqual(case.sources["Source-X"].capacity, 10.0)


if __name__ == "__main__":
    unittest.main()
