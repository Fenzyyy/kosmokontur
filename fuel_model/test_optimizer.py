"""Интеграционные тесты эвристического optimizer на синтетическом кейсе."""
import unittest

from .model import Case, Constraints, DemandRow, Plan, Source, StorageMode
from .optimizer import OptimizerConfig, optimize
from .scenarios import base


class OptimizerSmoke(unittest.TestCase):
    def setUp(self):
        self.case = Case(
            demand={
                2035: DemandRow(
                    year=2035,
                    base_total=10.0,
                    base_critical=6.0,
                    low_total=8.0,
                    high_total=12.0,
                )
            },
            sources={
                "X": Source(
                    source_id="X",
                    name="Synthetic source",
                    capacity=100.0,
                    variable_cost=1.0,
                    reservation_rate=0.0,
                    top_share=0.0,
                    lead_time_min=0.0,
                    lead_time_max=0.0,
                    lead_time_unit="day",
                    available_from_year=2035,
                )
            },
            storage={
                "BASE_STORAGE": StorageMode(
                    mode_id="BASE_STORAGE",
                    name="Synthetic storage",
                    capacity=100.0,
                    loss_rate=0.0,
                    holding_cost=0.0,
                )
            },
            options={},
            constraints=Constraints(reserve_days=0.0),
        )

    def test_optimizer_finds_feasible_plan(self):
        result = optimize(
            self.case,
            [base()],
            config=OptimizerConfig(max_local_search_passes=3),
        )

        self.assertTrue(result.feasible)
        self.assertEqual(result.scenario_results["BASE"].kpis["hard_violations"], 0)
        self.assertAlmostEqual(
            result.scenario_results["BASE"].kpis["shortage_total"], 0.0, places=8
        )
        self.assertAlmostEqual(
            result.scenario_results["BASE"].kpis["shortage_critical"], 0.0, places=8
        )
        self.assertGreater(result.candidates_checked, 0)

    def test_optimizer_never_returns_storage_overflow(self):
        seed = Plan(
            "overflow-seed",
            orders={"X": {2035: 100.0}},
        )

        result = optimize(
            self.case,
            [base()],
            initial_plan=seed,
            config=OptimizerConfig(
                max_local_search_passes=3,
                step_fraction_of_capacity=0.10,
                min_step_tons=10.0,
            ),
        )

        storage_violations = [
            v
            for v in result.scenario_results["BASE"].violations
            if v.code in ("STORAGE_OVERFLOW", "INITIAL_STOCK_EXCEEDS_STORAGE")
        ]

        self.assertEqual(storage_violations, [])
        self.assertEqual(result.scenario_results["BASE"].kpis["hard_violations"], 0)

    def test_optimizer_is_deterministic(self):
        config = OptimizerConfig(max_local_search_passes=2)
        a = optimize(self.case, [base()], config=config)
        b = optimize(self.case, [base()], config=config)

        self.assertEqual(a.score, b.score)
        self.assertEqual(a.plan.to_dict(), b.plan.to_dict())


if __name__ == "__main__":
    unittest.main()
