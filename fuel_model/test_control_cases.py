"""Контрольные примеры V01-V10 стартового репозитория организаторов (арифметика и семантика правил).

Тесты вызывают ТЕ ЖЕ функции формул, которые использует движок.
Запуск без зависимостей: python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kosmo import formulas as F  # noqa: E402


class ControlCases(unittest.TestCase):
    def test_v01_material_balance(self):
        self.assertAlmostEqual(F.closing_inventory(10, 30, 2, 25), 13)

    def test_v02_shortage_is_not_negative_inventory(self):
        served_c, served_t = F.serve_demand(available=8, demand_critical=6, demand_total=10)
        self.assertAlmostEqual(served_t, 8)
        self.assertAlmostEqual(F.shortage(10, served_t), 2)
        self.assertAlmostEqual(F.closing_inventory(0, 8, 0, served_t), 0)   # запас 0, а не -2

    def test_v03_take_or_pay_minimum(self):
        self.assertAlmostEqual(F.payable_volume(50, 0.70, 100), 70)
        self.assertAlmostEqual(F.variable_payment(2, 50, 0.70, 100), 140)

    def test_v04_no_double_take_or_pay(self):
        pay = F.variable_payment(2, 50, 0.70, 100)
        self.assertAlmostEqual(pay, 140)
        self.assertNotAlmostEqual(pay, 140 + 70 * 2)

    def test_v05_reservation_proration(self):
        self.assertAlmostEqual(F.reservation_payment(0.4, 100, 0.5), 20)

    def test_v06_losses_once_on_throughput(self):
        self.assertAlmostEqual(F.losses(20, 0.05), 1)

    def test_v07_reserve_45_days(self):
        self.assertAlmostEqual(F.reserve_requirement(365), 45)

    def test_v08_capacity_exceeded(self):
        self.assertAlmostEqual(F.capacity_excess(reserved=12, capacity=10), 2)
        self.assertAlmostEqual(F.capacity_excess(reserved=8, capacity=10), 0)

    def test_v09_critical_nested_in_total(self):
        self.assertAlmostEqual(F.combined_total_demand(100, 60), 100)    # а не 160
        with self.assertRaises(ValueError):
            F.combined_total_demand(50, 60)
        _, served_t = F.serve_demand(available=1000, demand_critical=60, demand_total=100)
        self.assertAlmostEqual(served_t, 100)

    def test_v10_stress_delivery_no_double_reliability(self):
        self.assertAlmostEqual(F.stress_delivery(20, 0.50), 10)
        self.assertNotAlmostEqual(F.stress_delivery(20, 0.50), 20 * 0.50 * 0.80)

    def test_service_level_zero_demand_is_defined(self):
        self.assertEqual(F.service_level(0, 0), 1.0)

    def test_discount_factor(self):
        self.assertAlmostEqual(F.discount_factor(0.05, 2035, 2035), 1.0)
        self.assertAlmostEqual(F.discount_factor(0.05, 2036, 2035), 1 / 1.05)


if __name__ == "__main__":
    unittest.main()
