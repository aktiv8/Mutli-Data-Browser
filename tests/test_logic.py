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

import escape_explorer as ee  # noqa: E402
import themes  # noqa: E402
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


class TestThemes(unittest.TestCase):
    def test_every_palette_defines_every_key(self):
        for name, pal in themes.PALETTES.items():
            missing = set(themes.KEYS) - set(pal)
            self.assertFalse(missing, f"{name} lacks {missing}")
            self.assertGreaterEqual(len(pal["cycle"]), 6)

    def test_light_is_the_default_native_theme(self):
        self.assertEqual(themes.NATIVE, "Light")
        self.assertEqual(themes.THEME_NAMES[0], "Light")
        self.assertIn("Dark", themes.THEME_NAMES)

    def test_print_style_is_white_paper(self):
        rc = themes.mpl_rc(themes.PRINT)
        self.assertEqual(rc["figure.facecolor"], "#ffffff")
        self.assertEqual(rc["text.color"], "#000000")

    def test_dark_rc_follows_palette(self):
        rc = themes.mpl_rc(themes.PALETTES["Dark"])
        self.assertEqual(rc["axes.facecolor"], themes.PALETTES["Dark"]["plot_bg"])


class TestConfig(unittest.TestCase):
    def test_round_trip_and_bad_file(self):
        with tempfile.TemporaryDirectory() as d:
            ee.CONFIG_PATH = os.path.join(d, "c.json")
            self.assertEqual(ee.load_config(), {})               # missing file
            self.assertTrue(ee.save_config({"theme": "Dark", "n": 3}))
            self.assertEqual(ee.load_config()["theme"], "Dark")
            with open(ee.CONFIG_PATH, "w") as fh:
                fh.write("not json")
            self.assertEqual(ee.load_config(), {})               # corrupt file
            with open(ee.CONFIG_PATH, "w") as fh:
                json.dump([1, 2], fh)
            self.assertEqual(ee.load_config(), {})               # wrong type


if __name__ == "__main__":
    unittest.main()
