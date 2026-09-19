"""Проверка реальных входных таблиц кейса 2035-2040."""
import unittest
import os

from .loader import load_case
from .optimizer import OptimizerConfig, optimize
from .scenarios import base, mandatory_stress


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(ROOT, "data", "case_input")
CONFIG = os.path.join(ROOT, "configs")


class RealCaseInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = load_case(DATA, CONFIG)

    def test_input_tables_are_loaded(self):
        self.assertEqual(cls_years := self.case.years, [2035, 2036, 2037, 2038, 2039, 2040])
        self.assertEqual(set(self.case.sources), {"A", "B", "C", "D", "E"})
        self.assertEqual(self.case.sources["A"].capacity, 190.0)
        self.assertEqual(self.case.sources["D"].lead_time_max, 2.0)

        self.assertEqual(self.case.storage["BASE"].capacity, 70.0)
        self.assertEqual(self.case.storage["ZBO"].capacity, 120.0)

        self.assertEqual(self.case.options["EARTH_NEW"].total_capex, 360.0)
        self.assertEqual(self.case.options["LUNAR_ISRU"].total_capex, 1250.0)
        self.assertEqual(self.case.options["ZBO"].total_capex, 180.0)

        self.assertEqual(self.case.constraints.sl_total_min, 0.97)
        self.assertEqual(self.case.constraints.sl_critical_min, 0.99)
        self.assertEqual(self.case.constraints.capex_cumulative_limit, 1800.0)
        self.assertEqual(self.case.constraints.capex_total_limit, 2800.0)
        self.assertEqual(self.case.constraints.reserve_days, 45.0)

    def test_source_roles_are_loaded(self):
        self.assertEqual(self.case.role("C").requires_option, "EARTH_NEW")
        self.assertEqual(self.case.role("C").lead_time_semantics, "build")
        self.assertEqual(self.case.role("D").requires_option, "LUNAR_ISRU")
        self.assertEqual(
            self.case.role("D").lead_time_semantics,
            "post_commissioning",
        )

    def test_optimizer_runs_on_real_base_case(self):
        result = optimize(
            self.case,
            [base()],
            config=OptimizerConfig(
                max_investment_options_exhaustive=8,
                max_local_search_passes=1,
                step_fraction_of_capacity=0.10,
                min_step_tons=5.0,
            ),
        )

        base_result = result.scenario_results["BASE"]
        self.assertTrue(result.candidates_checked > 0)
        self.assertEqual(base_result.kpis["hard_violations"], 0)
        self.assertAlmostEqual(base_result.kpis["shortage_total"], 0.0, places=6)
        self.assertAlmostEqual(base_result.kpis["shortage_critical"], 0.0, places=6)

    def test_optimizer_runs_on_base_and_mandatory_stress(self):
        result = optimize(
            self.case,
            [base(), mandatory_stress()],
            config=OptimizerConfig(
                max_investment_options_exhaustive=8,
                max_local_search_passes=1,
                step_fraction_of_capacity=0.10,
                min_step_tons=5.0,
            ),
        )

        self.assertGreater(result.candidates_checked, 0)
        self.assertEqual(set(result.scenario_results), {"BASE", "MANDATORY_STRESS"})

        print("\nOPTIMIZER PLAN:", result.plan.to_dict())
        for _sid, _result in result.scenario_results.items():
            print(
                _sid,
                "score=", result.score,
                "shortage=", _result.kpis["shortage_total"],
                "critical_shortage=", _result.kpis["shortage_critical"],
            )
            for _row in _result.yearly:
                print(
                    _row["year"],
                    "demand=", _row["demand_total"],
                    "served=", _row["served_total"],
                    "reserve=", _row.get("reserve_covered", _row["reserve_stock_at_check"]),
                )

        base_result = result.scenario_results["BASE"]
        self.assertEqual(
            base_result.kpis["hard_violations"],
            0,
            msg=(
                "BASE: HARD violations found; "
                f"violations={[v.to_dict() for v in base_result.violations]}"
            ),
        )
        self.assertAlmostEqual(
            base_result.kpis["shortage_total"],
            0.0,
            places=6,
            msg="BASE: total shortage",
        )
        self.assertAlmostEqual(
            base_result.kpis["shortage_critical"],
            0.0,
            places=6,
            msg="BASE: critical shortage",
        )

        stress_result = result.scenario_results["MANDATORY_STRESS"]
        self.assertEqual(
            stress_result.kpis["hard_violations"],
            0,
            msg=(
                "MANDATORY_STRESS: HARD violations found; "
                f"violations={[v.to_dict() for v in stress_result.violations]}"
            ),
        )
        self.assertFalse(
            any(
                v.code in ("STORAGE_OVERFLOW", "INITIAL_STOCK_EXCEEDS_STORAGE")
                for v in stress_result.violations
            ),
            msg="MANDATORY_STRESS: storage overflow detected",
        )

        print("\nMULTI-SCENARIO OPTIMIZATION")
        print("investments:", sorted(result.plan.investments))
        print("score:", result.score)
        for scenario_id, scenario_result in result.scenario_results.items():
            print(
                f"{scenario_id}: "
                f"cost={scenario_result.kpis['total_cost']:.3f}, "
                f"service={scenario_result.kpis['service_level_total']:.6f}, "
                f"critical_service={scenario_result.kpis['service_level_critical']:.6f}"
            )


if __name__ == "__main__":
    unittest.main()
