"""Tk-free tests for the per-panel view overrides.

Run:  python -m unittest discover tests
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import panelview as pv  # noqa: E402

DEFAULTS = {"view": "Stack", "norm": "None", "offset": 0.6, "z_axis": "Auto",
            "reverse": False,
            "fit_show": {"components": True, "envelope": True,
                         "background": True}}


class TestSanitise(unittest.TestCase):
    def test_keeps_valid_drops_invalid(self):
        d = pv.sanitise({"view": "Heatmap", "norm": "bogus", "z_axis": "Depth",
                         "reverse": "yes", "offset": 9, "junk": 1})
        self.assertEqual(d, {"view": "Heatmap", "z_axis": "Depth",
                             "offset": 3.0})

    def test_offset_is_clamped_and_bool_rejected(self):
        self.assertEqual(pv.sanitise({"offset": -2})["offset"], 0.0)
        self.assertNotIn("offset", pv.sanitise({"offset": True}))
        self.assertNotIn("offset", pv.sanitise({"offset": float("nan")}))

    def test_fit_show_keeps_only_known_bool_layers(self):
        d = pv.sanitise({"fit_show": {"envelope": False, "x": True,
                                      "components": "no"}})
        self.assertEqual(d, {"fit_show": {"envelope": False}})
        self.assertEqual(pv.sanitise({"fit_show": {"x": True}}), {})

    def test_not_a_dict(self):
        self.assertEqual(pv.sanitise(None), {})
        self.assertEqual(pv.sanitise("Stack"), {})
        self.assertEqual(pv.sanitise_all([1]), {})

    def test_sanitise_all_drops_empty_overrides(self):
        out = pv.sanitise_all({"C 1s": {"view": "Fit"}, "O 1s": {"view": "x"},
                               "N 1s": None})
        self.assertEqual(out, {"C 1s": {"view": "Fit"}})


class TestResolve(unittest.TestCase):
    def test_no_override_is_the_default(self):
        self.assertEqual(pv.resolve(DEFAULTS), DEFAULTS)
        self.assertEqual(pv.resolve(DEFAULTS, {}), DEFAULTS)

    def test_override_wins_and_default_untouched(self):
        look = pv.resolve(DEFAULTS, {"view": "Waterfall 3D", "offset": 1.5,
                                     "fit_show": {"envelope": False}})
        self.assertEqual(look["view"], "Waterfall 3D")
        self.assertEqual(look["offset"], 1.5)
        self.assertEqual(look["fit_show"],
                         {"components": True, "envelope": False,
                          "background": True})
        self.assertTrue(DEFAULTS["fit_show"]["envelope"])
        self.assertEqual(look["norm"], "None")

    def test_default_change_reaches_panels_without_that_key(self):
        d2 = dict(DEFAULTS, view="Heatmap")
        self.assertEqual(pv.resolve(d2, {"norm": "Max = 1"})["view"],
                         "Heatmap")
        self.assertEqual(pv.resolve(d2, {"view": "Stack"})["view"], "Stack")


class TestEditing(unittest.TestCase):
    def test_with_value_does_not_mutate_and_keeps_others(self):
        base = {"A": {"view": "Fit"}}
        out = pv.with_value(base, "B", "view", "Heatmap")
        self.assertEqual(base, {"A": {"view": "Fit"}})
        self.assertEqual(out, {"A": {"view": "Fit"},
                               "B": {"view": "Heatmap"}})

    def test_fit_layer(self):
        out = pv.with_value({}, "A", "fit_show", ("components", False))
        out = pv.with_value(out, "A", "fit_show", ("envelope", True))
        self.assertEqual(out["A"]["fit_show"],
                         {"components": False, "envelope": True})

    def test_invalid_value_leaves_no_entry(self):
        self.assertEqual(pv.with_value({}, "A", "view", "nope"), {})

    def test_reset(self):
        v = {"A": {"view": "Fit"}, "B": {"view": "Heatmap"}}
        self.assertEqual(pv.reset(v, "A"), {"B": {"view": "Heatmap"}})
        self.assertEqual(pv.reset(v), {})
        self.assertEqual(v["A"], {"view": "Fit"})


class TestArrange(unittest.TestCase):
    @staticmethod
    def z_order(regs, mode):
        return sorted(range(len(regs)), key=lambda i: -regs[i])

    def test_series_views_use_z_order(self):
        look = pv.resolve(DEFAULTS, {"view": "Heatmap"})
        self.assertEqual(pv.arrange([1, 3, 2], look, self.z_order), [3, 2, 1])

    def test_stack_keeps_order_or_reverses(self):
        look = pv.resolve(DEFAULTS)
        self.assertEqual(pv.arrange([1, 3, 2], look, self.z_order), [1, 3, 2])
        look = pv.resolve(DEFAULTS, {"reverse": True})
        self.assertEqual(pv.arrange([1, 3, 2], look, self.z_order), [2, 3, 1])

    def test_fit_is_not_a_series_view(self):
        look = pv.resolve(DEFAULTS, {"view": "Fit"})
        self.assertFalse(pv.is_series(look["view"]))
        self.assertEqual(pv.arrange([1, 3, 2], look, self.z_order), [1, 3, 2])

    def test_does_not_modify_input(self):
        rs = [1, 2, 3]
        pv.arrange(rs, pv.resolve(DEFAULTS, {"reverse": True}), self.z_order)
        self.assertEqual(rs, [1, 2, 3])


class TestDescribe(unittest.TestCase):
    def test_empty_override_says_nothing(self):
        self.assertEqual(pv.describe({}, DEFAULTS), "")

    def test_waterfall_with_z(self):
        self.assertEqual(
            pv.describe({"view": "Waterfall 3D", "z_axis": "Etch level"},
                        DEFAULTS), "Waterfall 3D, by Etch level")

    def test_fit_layers(self):
        s = pv.describe({"view": "Fit",
                         "fit_show": {"background": False,
                                      "envelope": False}}, DEFAULTS)
        self.assertEqual(s, "Fit, showing components")

    def test_stack_offset_and_norm(self):
        s = pv.describe({"offset": 1.0, "norm": "Max = 1"}, DEFAULTS)
        self.assertEqual(s, "Stack, normalised Max = 1, offset 1×")


if __name__ == "__main__":
    unittest.main()
