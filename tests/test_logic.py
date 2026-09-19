"""Tk-free logic: grouping, tick state, grid shapes, themes, config.

Run:  python -m unittest discover tests
"""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import spectradeck as ee  # noqa: E402
from readers import Region  # noqa: E402


def reg(name, lo, hi, sample="S1", n=50):
    e = [hi - i * (hi - lo) / (n - 1) for i in range(n)]
    return Region(name=name, index=0, offset=0, energy=e, counts=[1.0] * n,
                  decodable=True, sample=sample)


class TestGrouping(unittest.TestCase):
    def setUp(self):
        self.rs = [reg("C 1s", 280, 295), reg("c 1s", 280, 295, "S2"),
                   reg("O 1s", 525, 540), reg("Survey", 0, 1100),
                   reg("Alt C", 281, 296)]

    def test_by_name_is_case_insensitive_and_ordered(self):
        g = ee.group_regions(self.rs, "name")
        self.assertEqual([(k, len(v)) for k, v in g],
                         [("C 1s", 2), ("O 1s", 1), ("Survey", 1), ("Alt C", 1)])

    def test_by_range_merges_overlapping_spans(self):
        g = ee.group_regions(self.rs, "range")
        self.assertEqual([len(v) for _k, v in g], [3, 1, 1])

    def test_tick_state(self):
        self.assertEqual(ee.tick_state(frozenset({1, 2}), set()), 0)
        self.assertEqual(ee.tick_state(frozenset({1, 2}), {1}), 1)
        self.assertEqual(ee.tick_state(frozenset({1, 2}), {1, 2, 9}), 2)
        self.assertEqual(ee.tick_state(frozenset(), {1}), 0)

    def test_grid_shapes(self):
        shapes = {n: ee._grid_dims(n) for n in (1, 2, 4, 6, 9, 12, 16)}
        self.assertEqual(shapes, {1: (1, 1), 2: (1, 2), 4: (2, 2), 6: (2, 3),
                                  9: (3, 3), 12: (3, 4), 16: (4, 4)})

    def test_normalisation_factors(self):
        r = reg("C 1s", 280, 295)
        r.counts = [1.0, 4.0, 2.0] + [1.0] * 47
        self.assertEqual(ee.norm_factor(r, "Max = 1"), 4.0)
        self.assertEqual(ee.norm_factor(r, "None"), 1.0)
        self.assertGreater(ee.norm_factor(r, "Area = 1"), 0)


class TestConfig(unittest.TestCase):
    def test_round_trip_and_bad_file(self):
        with tempfile.TemporaryDirectory() as d:
            ee.CONFIG_PATH = os.path.join(d, "c.json")
            ee.LEGACY_CONFIG_PATH = os.path.join(d, "old.json")
            self.assertEqual(ee.load_config(), {})               # missing file
            self.assertTrue(ee.save_config({"theme": "Dark", "n": 3}))
            self.assertEqual(ee.load_config()["theme"], "Dark")
            with open(ee.CONFIG_PATH, "w") as fh:
                fh.write("not json")
            self.assertEqual(ee.load_config(), {})               # corrupt file
            with open(ee.CONFIG_PATH, "w") as fh:
                json.dump([1, 2], fh)
            self.assertEqual(ee.load_config(), {})               # wrong type

    def test_settings_of_the_former_name_are_picked_up(self):
        with tempfile.TemporaryDirectory() as d:
            ee.CONFIG_PATH = os.path.join(d, "new.json")
            ee.LEGACY_CONFIG_PATH = os.path.join(d, "old.json")
            ee.CALIB_PATH = os.path.join(d, "newc.json")
            ee.LEGACY_CALIB_PATH = os.path.join(d, "oldc.json")
            with open(ee.LEGACY_CONFIG_PATH, "w") as fh:
                json.dump({"theme": "Dark"}, fh)
            with open(ee.LEGACY_CALIB_PATH, "w") as fh:
                json.dump({"mm_per_px": 0.5}, fh)
            self.assertEqual(ee.load_config(), {"theme": "Dark"})
            self.assertEqual(ee.load_calibration(), {"mm_per_px": 0.5})
            # once saved under the new name, the old file is no longer read
            ee.save_config({"theme": "Light"})
            self.assertEqual(ee.load_config(), {"theme": "Light"})
            ee.save_calibration({"mm_per_px": 0.9})
            self.assertEqual(ee.load_calibration(), {"mm_per_px": 0.9})
            # a damaged new file is empty, it does not fall back
            with open(ee.CONFIG_PATH, "w") as fh:
                fh.write("{")
            self.assertEqual(ee.load_config(), {})


if __name__ == "__main__":
    unittest.main()
