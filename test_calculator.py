import unittest
from calculator import SalaryCalculator, format_rupiah


class TestSalaryCalculator(unittest.TestCase):
    def setUp(self):
        self.calc = SalaryCalculator()

    def test_noorman_exact_match(self):
        """Test calculation exactly matching Noorman row from CALCULATION sheet."""
        # Noorman: PRO, 12 units of Product 2 (FTTH >= 229k s.d < 299k)
        products = [0, 12, 0, 0, 0, 0, 0, 0]
        res = self.calc.calculate(
            position="PRO",
            product_quantities=products,
            agent_name="Noorman"
        )

        self.assertEqual(res["basic_salary"], 3500000)
        self.assertEqual(res["total_units"], 12)
        self.assertEqual(res["total_insentif_produk"], 600000)
        self.assertEqual(res["total_spesial_insentif"], 0)
        self.assertEqual(res["multiplier"], 2.0)
        self.assertEqual(res["total_insentif_multiplier"], 1200000)
        self.assertEqual(res["total_insentif_pemasangan"], 1170000)
        self.assertEqual(res["total_insentif"], 2970000)
        self.assertEqual(res["take_home_pay"], 6470000)
        self.assertEqual(res["achievement_pct"], 100.0)

        # Check pemasangan tier breakdown
        t1, t2, t3 = res["pemasangan_tiers"][0], res["pemasangan_tiers"][1], res["pemasangan_tiers"][2]
        self.assertEqual(t1["subtotal"], 480000)  # 6 * 80k
        self.assertEqual(t2["subtotal"], 300000)  # 3 * 100k
        self.assertEqual(t3["subtotal"], 390000)  # 3 * 130k

    def test_ojt_calculation(self):
        """Test OJT calculations (multiplier must be 0, different installation tiers)."""
        # OJT: 5 units of Product 2
        products = [0, 5, 0, 0, 0, 0, 0, 0]
        res = self.calc.calculate(
            position="OJT",
            product_quantities=products,
            agent_name="Budi OJT"
        )

        self.assertEqual(res["basic_salary"], 2500000)
        self.assertEqual(res["total_units"], 5)
        self.assertEqual(res["multiplier"], 0.0)
        self.assertEqual(res["total_insentif_multiplier"], 0)
        self.assertEqual(res["total_insentif_produk"], 250000)

        # OJT Tiers:
        # 1-2: 2 * 80k = 160k
        # 3-4: 2 * 100k = 200k
        # 5-6: 1 * 130k = 130k
        # Total Pemasangan = 490k
        self.assertEqual(res["total_insentif_pemasangan"], 490000)
        self.assertEqual(res["total_insentif"], 740000)
        self.assertEqual(res["take_home_pay"], 3240000)

    def test_special_incentives_p7_p8(self):
        """Test products 7 and 8 with special incentives."""
        # 2 units P7 (rate 125k, special 125k) + 2 units P8 (rate 150k, special 150k) = 4 units total
        products = [0, 0, 0, 0, 0, 0, 2, 2]
        res = self.calc.calculate(
            position="PRO",
            product_quantities=products
        )

        expected_reg = (2 * 125000) + (2 * 150000)  # 250k + 300k = 550k
        expected_spc = (2 * 125000) + (2 * 150000)  # 550k
        self.assertEqual(res["total_insentif_produk"], expected_reg)
        self.assertEqual(res["total_spesial_insentif"], expected_spc)
        # 4 units in PRO -> Multiplier is 0.0 (bracket 1-6)
        self.assertEqual(res["multiplier"], 0.0)

    def test_high_performer_elite(self):
        """Test 35 units for ELITE position (tier 30-39, multiplier 4.25x)."""
        products = [0, 35, 0, 0, 0, 0, 0, 0]
        res = self.calc.calculate(
            position="ELITE",
            product_quantities=products
        )
        self.assertEqual(res["basic_salary"], 4000000)
        self.assertEqual(res["multiplier"], 4.25)


if __name__ == "__main__":
    unittest.main()
