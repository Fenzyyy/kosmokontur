"""Тесты расчётного ядра на данных кейса и на минимальном синтетическом наборе."""
import copy
import dataclasses
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from kosmo import evaluate, load_case, scenarios as S  # noqa: E402
from kosmo.errors import PlanValidationError, ScenarioConflict  # noqa: E402
from kosmo.model import (Assumptions, Case, Constraints, DemandRow, InitialStockLot,  # noqa: E402
                         InvestmentDecision, Plan, Source, StorageMode)

DATA = os.path.join(ROOT, "data", "case_input")
CFG = os.path.join(ROOT, "configs")


def codes(result, severity=None):
    return sorted({v.code for v in result.violations if severity is None or v.severity == severity})


def full_year(source, volume, years=range(2035, 2041)):
    return {source: {y: float(volume) for y in years}}


class RealCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = load_case(DATA, CFG)

    def test_case_loaded_and_earth_new_total_is_360(self):
        opt = self.case.options["EARTH_NEW"]
        self.assertEqual(opt.total_capex, 360.0)          # 90 + 270, не 450
        self.assertEqual(self.case.options["ISRU_PILOT"].total_capex, 1250.0)
        self.assertEqual(self.case.options["ZBO"].total_capex, 180.0)

    def test_case_is_not_mutated_by_scenarios(self):
        before = copy.deepcopy(self.case.to_dict())
        plan = Plan("p", orders=full_year("A", 100), reserved=full_year("A", 100),
                    initial_stock=[InitialStockLot("A", 15)])
        for sc in (S.base(), S.mandatory_stress(), S.high_demand(), S.low_demand()):
            evaluate(self.case, plan, sc)
        self.assertEqual(before, self.case.to_dict())

    def test_invariants_material_balance_and_nonnegative_stock(self):
        plan = Plan("p", orders=full_year("A", 120), reserved=full_year("A", 120),
                    initial_stock=[InitialStockLot("A", 20)])
        for sc in (S.base(), S.mandatory_stress()):
            r = evaluate(self.case, plan, sc)
            self.assertLess(r.kpis["max_abs_balance_residual"], 1e-9)
            self.assertTrue(all(t["inventory_t"] >= 0 for t in r.inventory_trace))
            for y in r.yearly:
                self.assertLessEqual(y["served_critical"], y["served_total"] + 1e-9)
                self.assertLessEqual(y["served_total"], y["demand_total"] + 1e-9)
                self.assertGreaterEqual(y["shortage_total"], 0.0)

    def test_deterministic_repeat(self):
        plan = Plan("p", orders=full_year("A", 150), reserved=full_year("A", 150),
                    initial_stock=[InitialStockLot("A", 15)])
        a = evaluate(self.case, plan, S.mandatory_stress()).to_dict()
        b = evaluate(self.case, plan, S.mandatory_stress()).to_dict()
        self.assertEqual(a, b)

    def test_mandatory_stress_overlay_values(self):
        plan = Plan("p", orders=full_year("A", 150), reserved=full_year("A", 150),
                    initial_stock=[InitialStockLot("A", 15)])
        r = evaluate(self.case, plan, S.mandatory_stress())
        y = {row["year"]: row for row in r.yearly}
        self.assertAlmostEqual(y[2037]["demand_total"], 190.0)              # до 2038 без изменений
        self.assertAlmostEqual(y[2038]["demand_total"], 250 * 1.15)
        self.assertAlmostEqual(y[2038]["demand_critical"], 170 * 1.15)       # критический тоже x1.15
        self.assertAlmostEqual(y[2040]["demand_total"], 390 * 1.15)
        price = {row["year"]: row["sources"]["A"]["price"] for row in r.costs}
        self.assertAlmostEqual(price[2037], 6.2)
        self.assertAlmostEqual(price[2038], 6.2 * 1.25)
        self.assertAlmostEqual(price[2039], 6.2 * 1.25)
        self.assertAlmostEqual(price[2040], 6.2)                             # в 2040 цена исходная

    def test_high_low_demand_keep_critical_share(self):
        d = self.case.demand_series("high")
        self.assertAlmostEqual(d[2038][0], 312.5)
        self.assertAlmostEqual(d[2038][1] / d[2038][0], 170 / 250)
        d = self.case.demand_series("low")
        self.assertAlmostEqual(d[2036][1] / d[2036][0], 105 / 140)

    def test_take_or_pay_and_reservation_costs(self):
        # A: резерв 100, заказ 50 -> оплачивается max(50, 0.7*100) = 70 т; резерв 0.45 * 100
        plan = Plan("p", orders={"A": {2036: 50.0}}, reserved={"A": {2036: 100.0}})
        r = evaluate(self.case, plan, S.base())
        a = {row["year"]: row["sources"]["A"] for row in r.costs}[2036]
        self.assertAlmostEqual(a["payable_volume"], 70.0)
        self.assertAlmostEqual(a["variable_payment"], 6.2 * 70.0)            # take-or-pay один раз
        self.assertAlmostEqual(a["reservation_payment"], 0.45 * 100.0)
        self.assertAlmostEqual(a["take_or_pay_unused_t"], 20.0)

    def test_total_cost_is_sum_of_components_no_double_count(self):
        plan = Plan("p", orders=full_year("A", 120), reserved=full_year("A", 120),
                    initial_stock=[InitialStockLot("A", 20)])
        r = evaluate(self.case, plan, S.base())
        for c in r.costs:
            parts = c["procurement"] + c["reservation"] + c["holding"] + c["fixed_opex"] + c["capex"]
            self.assertAlmostEqual(c["total"], parts)
        self.assertAlmostEqual(sum(c["initial_stock_cost"] for c in r.costs), 20 * 6.2)

    def test_earth_new_capex_lead_time_and_partial_year_reservation(self):
        inv = {"EARTH_NEW": InvestmentDecision(((2035, 7), (2035, 7)), (2037, 7))}
        plan = Plan("p", investments=inv, reserved={"C": {2037: 130.0}}, orders={"C": {2037: 50.0}})
        r = evaluate(self.case, plan, S.base())
        self.assertAlmostEqual(sum(c["capex"] for c in r.costs), 360.0)
        c2037 = {c["year"]: c for c in r.costs}[2037]["sources"]["C"]
        frac = (365 - 181) / 365                                              # с 1 июля
        self.assertAlmostEqual(c2037["reservation_payment"], 0.30 * 130.0 * frac)
        self.assertNotIn("LEAD_TIME_VIOLATION", codes(r))
        # слишком быстрый ввод: 12 мес. < минимума 18 мес.
        bad = Plan("p2", investments={"EARTH_NEW": InvestmentDecision(((2035, 1), (2035, 1)), (2036, 1))})
        self.assertIn("LEAD_TIME_VIOLATION", codes(evaluate(self.case, bad, S.base()), "HARD"))
        # 18..24 мес. - допустимо, но с предупреждением
        opt = Plan("p3", investments={"EARTH_NEW": InvestmentDecision(((2035, 1), (2035, 1)), (2036, 9))})
        self.assertIn("LEAD_TIME_OPTIMISTIC", codes(evaluate(self.case, opt, S.base()), "WARNING"))

    def test_capacity_exceeded_v08_and_order_limits(self):
        plan = Plan("p", orders={"A": {2035: 200.0}}, reserved={"A": {2035: 200.0}})
        r = evaluate(self.case, plan, S.base())
        v = [x for x in r.violations if x.code == "CAPACITY_EXCEEDED"][0]
        self.assertEqual((v.year, v.subject), (2035, "A"))
        self.assertAlmostEqual(v.excess, 10.0)
        plan2 = Plan("p2", orders={"A": {2035: 100.0}}, reserved={"A": {2035: 60.0}})
        self.assertIn("ORDER_EXCEEDS_RESERVED", codes(evaluate(self.case, plan2, S.base()), "HARD"))

    def test_source_not_available_without_investment(self):
        plan = Plan("p", orders={"C": {2036: 10.0}, "D": {2038: 10.0}}, reserved={"C": {2036: 10.0}})
        r = evaluate(self.case, plan, S.base())
        subjects = {(v.subject, v.year) for v in r.violations if v.code == "SOURCE_NOT_AVAILABLE"}
        self.assertEqual(subjects, {("C", 2036), ("D", 2038)})

    def test_isru_financing_deadline_and_stress_delivery_share(self):
        late = Plan("late", investments={"ISRU_PILOT": InvestmentDecision(((2038, 1),), (2038, 1))})
        self.assertIn("INVESTMENT_TIMING", codes(evaluate(self.case, late, S.base()), "HARD"))
        ok = Plan("ok", investments={"ISRU_PILOT": InvestmentDecision(((2037, 1),), (2038, 1))},
                  orders={"D": {2038: 100.0, 2039: 100.0, 2040: 100.0}})
        r = evaluate(self.case, ok, S.mandatory_stress())
        got = {row["year"]: row["sources"]["D"]["actual_delivery"] for row in r.yearly}
        self.assertAlmostEqual(got[2038], 100 * 0.55)        # заданная доля, без умножения на надёжность 0.78
        self.assertAlmostEqual(got[2039], 100 * 0.75)
        self.assertAlmostEqual(got[2040], 100.0)
        # платёж за ISRU идёт за заказанный объём: автоматического возврата за недопоставку нет
        pay = {c["year"]: c["sources"]["D"]["variable_payment"] for c in r.costs}
        self.assertAlmostEqual(pay[2038], 3.0 * 100.0)
        # первая поставка через lead time (2 мес.) после ввода 1 января 2038
        first = [row for row in r.supply_schedule if row["source"] == "D"][0]
        self.assertEqual(first["date"], "2038-03-01")

    def test_emergency_streak(self):
        plan = Plan("p", orders={"E": {2036: 10.0, 2037: 10.0, 2038: 10.0}}, reserved={"E": {2036: 10.0, 2037: 10.0, 2038: 10.0}})
        r = evaluate(self.case, plan, S.base())
        v = [x for x in r.violations if x.code == "EMERGENCY_BASE_STREAK"]
        self.assertEqual([x.year for x in v], [2038])
        two = Plan("p2", orders={"E": {2036: 10.0, 2037: 10.0}}, reserved={"E": {2036: 10.0, 2037: 10.0}})
        self.assertNotIn("EMERGENCY_BASE_STREAK", codes(evaluate(self.case, two, S.base())))

    def test_loss_ceiling_in_stress_needs_zbo(self):
        orders = {"A": {y: 150.0 for y in range(2035, 2041)}}
        plain = Plan("plain", orders=orders, reserved=orders, initial_stock=[InitialStockLot("A", 15)])
        self.assertIn("LOSS_CEILING_EXCEEDED", codes(evaluate(self.case, plain, S.mandatory_stress()), "HARD"))
        self.assertNotIn("LOSS_CEILING_EXCEEDED", codes(evaluate(self.case, plain, S.base())))
        zbo = Plan("zbo", orders=orders, reserved=orders, initial_stock=[InitialStockLot("A", 15)],
                   investments={"ZBO": InvestmentDecision(((2036, 1),), (2036, 1))})
        self.assertNotIn("LOSS_CEILING_EXCEEDED", codes(evaluate(self.case, zbo, S.mandatory_stress())))
        r = evaluate(self.case, zbo, S.base())
        self.assertAlmostEqual({y["year"]: y["loss_share"] for y in r.yearly}[2036], 0.012)
        self.assertAlmostEqual({y["year"]: y["loss_share"] for y in r.yearly}[2035], 0.045)

    def test_stress_service_is_benchmark_base_is_hard(self):
        plan = Plan("p", orders=full_year("A", 100), reserved=full_year("A", 100), initial_stock=[InitialStockLot("A", 15)])
        rb = evaluate(self.case, plan, S.base())
        rs = evaluate(self.case, plan, S.mandatory_stress())
        self.assertTrue(any(v.code == "SL_TOTAL_LOW" and v.severity == "HARD" for v in rb.violations))
        self.assertTrue(all(v.severity == "BENCHMARK" for v in rs.violations if v.code.startswith("SL_")))

    def test_storage_overflow_and_initial_stock(self):
        plan = Plan("p", orders={"A": {2035: 190.0}}, reserved={"A": {2035: 190.0}}, initial_stock=[InitialStockLot("A", 80)])
        r = evaluate(self.case, plan, S.base())
        self.assertIn("INITIAL_STOCK_EXCEEDS_STORAGE", codes(r))
        self.assertIn("STORAGE_OVERFLOW", codes(r))

    def test_capex_limits(self):
        inv = {"ISRU_PILOT": InvestmentDecision(((2037, 1),), (2038, 1)),
               "EARTH_NEW": InvestmentDecision(((2035, 1), (2035, 1)), (2037, 1)),
               "ZBO": InvestmentDecision(((2036, 1),), (2036, 1))}
        r = evaluate(self.case, Plan("p", investments=inv), S.base())
        self.assertAlmostEqual(r.kpis["capex_through_deadline"], 1250 + 360 + 180)
        self.assertNotIn("CAPEX_LIMIT_CUMULATIVE", codes(r))                # 1790 <= 1800
        case2 = copy.deepcopy(self.case)
        case2.options["ZBO"] = dataclasses.replace(case2.options["ZBO"], stage_amounts=(191.0,))
        self.assertIn("CAPEX_LIMIT_CUMULATIVE", codes(evaluate(case2, Plan("p", investments=inv), S.base())))

    def test_input_errors_are_clear(self):
        with self.assertRaises(PlanValidationError) as cm:
            evaluate(self.case, Plan("bad", orders={"A": {2036: -5.0}}), S.base())
        self.assertEqual(cm.exception.issues[0].code, "NEGATIVE_VALUE")
        self.assertEqual(cm.exception.issues[0].field, "orders.A.2036")
        with self.assertRaises(PlanValidationError) as cm:
            evaluate(self.case, Plan("bad", orders={"Z": {2036: 5.0}}), S.base())
        self.assertEqual(cm.exception.issues[0].code, "UNKNOWN_SOURCE")
        with self.assertRaises(PlanValidationError) as cm:
            evaluate(self.case, Plan("bad", orders={"A": {2050: 5.0}}), S.base())
        self.assertEqual(cm.exception.issues[0].code, "YEAR_OUT_OF_HORIZON")
        with self.assertRaises(PlanValidationError):
            evaluate(self.case, Plan("bad", investments={"EARTH_NEW": InvestmentDecision(((2035, 1),), (2037, 1))}), S.base())

    def test_scenario_combination_requires_explicit_rule(self):
        with self.assertRaises(ScenarioConflict):
            S.combine("X", "x", S.mandatory_stress(), S.demand_shock("D", "d", [2038], 1.1))
        ok = S.combine("X", "x", S.mandatory_stress(), S.price_shock("P", "p", ["E"], [2038], 1.3))
        self.assertEqual(ok.price_multiplier[("E", 2038)], 1.3)
        self.assertEqual(ok.price_multiplier[("A", 2038)], 1.25)

    def test_plan_save_and_reopen(self):
        plan = Plan("p", name="t", orders=full_year("A", 100), reserved=full_year("A", 100),
                    initial_stock=[InitialStockLot("A", 15)],
                    investments={"ZBO": InvestmentDecision(((2036, 1),), (2036, 1))})
        path = os.path.join(ROOT, "results", "_tmp_plan.json")
        try:
            plan.save(path)
            again = Plan.load(path)
        finally:
            if os.path.exists(path):
                os.remove(path)
        a = evaluate(self.case, plan, S.base()).kpis
        b = evaluate(self.case, again, S.base()).kpis
        self.assertEqual(a, b)


class TinySyntheticCase(unittest.TestCase):
    """V02 на уровне движка: недопоставка даёт дефицит, а не отрицательный запас."""

    def setUp(self):
        self.case = Case(
            demand={2035: DemandRow(2035, 10, 6, 8, 12)},
            sources={"X": Source("X", "X", 100.0, 1.0, 0.0, 0.0, 1, 1, "month")},
            storage={"BASE_STORAGE": StorageMode("BASE_STORAGE", "b", 100.0, 0.0, 0.0)},
            options={}, constraints=Constraints(), source_roles={}, assumptions=Assumptions())

    def test_v02_engine_level(self):
        r = evaluate(self.case, Plan("t", orders={"X": {2035: 8.0}}), S.base())
        y = r.yearly[0]
        self.assertAlmostEqual(y["served_total"], 8.0)
        self.assertAlmostEqual(y["shortage_total"], 2.0)
        self.assertAlmostEqual(y["inventory_close"], 0.0)
        self.assertTrue(all(t["inventory_t"] >= 0 for t in r.inventory_trace))

    def test_v01_engine_level_balance(self):
        plan = Plan("t", orders={"X": {2035: 30.0}}, initial_stock=[InitialStockLot("X", 10)])
        y = evaluate(self.case, plan, S.base()).yearly[0]
        self.assertAlmostEqual(y["inventory_close"], 10 + 30 - 10)         # спрос 10 обслужен полностью
        self.assertAlmostEqual(y["balance_residual"], 0.0)


if __name__ == "__main__":
    unittest.main()
