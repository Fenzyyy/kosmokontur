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

        print("\nMULTI-SCENARIO OPTIMIZATION")
        print("investments:", sorted(result.plan.investments))
        print("score:", result.score)
        for scenario_id, scenario_result in result.scenario_results.items():
            print(
                f"{scenario_id}: "
                f"cost={scenario_result.kpis['total_cost']:.3f}, "
                f"min_sl_total={scenario_result.kpis['min_sl_total']:.6f}, "
                f"min_sl_critical={scenario_result.kpis['min_sl_critical']:.6f}"
            )


if __name__ == "__main__":
    unittest.main()
