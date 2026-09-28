"""imfp.py: the TPP-2M average-matrix IMFP and the KE^0.6 Avantage-style
proxy used by quant.py's "scofield_tpp2m"/"scofield_ke06" RSF-fallback
tiers.

Run:  python -m unittest discover tests
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import imfp  # noqa: E402


class TestImfpNm(unittest.TestCase):
    # hand-computed from the same formula independently, at the module's
    # fixed average-matrix constants -- see imfp.py's own docstring
    REFERENCE = {50: 0.5066507922262123, 100: 0.577623423099999,
                200: 0.7947830339179165, 500: 1.4263303268788368,
                1000: 2.368001423854056, 2000: 4.060332098481516}

    def test_reference_values(self):
        for ke, expected in self.REFERENCE.items():
            self.assertAlmostEqual(imfp.imfp_nm(ke), expected, places=9,
                                   msg=f"KE={ke}")

    def test_increases_with_kinetic_energy(self):
        values = [imfp.imfp_nm(ke) for ke in
                 (50, 100, 200, 500, 1000, 2000)]
        self.assertEqual(values, sorted(values))

    def test_just_inside_the_valid_range(self):
        self.assertIsNotNone(imfp.imfp_nm(50.0))
        self.assertIsNotNone(imfp.imfp_nm(2000.0))

    def test_outside_the_valid_range_gives_none(self):
        self.assertIsNone(imfp.imfp_nm(49.9))
        self.assertIsNone(imfp.imfp_nm(2000.1))
        self.assertIsNone(imfp.imfp_nm(0))
        self.assertIsNone(imfp.imfp_nm(None))


class TestKePowerFactor(unittest.TestCase):
    def test_matches_the_plain_power_law(self):
        for ke in (50, 200, 954.7, 1419, 2000):
            self.assertAlmostEqual(imfp.ke_power_factor(ke), ke ** 0.6,
                                   places=9, msg=f"KE={ke}")

    def test_no_upper_or_lower_bound_unlike_tpp2m(self):
        # not a published-range-restricted formula the way TPP-2M is
        self.assertIsNotNone(imfp.ke_power_factor(10))
        self.assertIsNotNone(imfp.ke_power_factor(5000))

    def test_non_positive_or_missing_gives_none(self):
        self.assertIsNone(imfp.ke_power_factor(0))
        self.assertIsNone(imfp.ke_power_factor(-5))
        self.assertIsNone(imfp.ke_power_factor(None))


if __name__ == "__main__":
    unittest.main()
