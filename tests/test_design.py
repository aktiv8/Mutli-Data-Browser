"""Design-system tests: palette contrast, data-palette separation, trace
colour rules, label helpers, font fallback.

Run:  python -m unittest discover tests
"""

import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import spectradeck as ee  # noqa: E402
import fonts  # noqa: E402
import themes  # noqa: E402
from readers import Region  # noqa: E402


def lab(h):
    """CIELAB of a #RRGGBB colour (D65) for perceptual distances."""
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in themes._rgb(h))
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116
    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def delta_e(a, b):
    return math.dist(lab(a), lab(b))


class TestPalettes(unittest.TestCase):
    def test_every_palette_defines_every_key(self):
        for name, pal in themes.PALETTES.items():
            self.assertFalse(set(themes.KEYS) - set(pal), name)

    def test_text_contrast_meets_wcag_aa(self):
        for name, p in themes.PALETTES.items():
            for label, fg, bg, need in (
                    ("ink on chrome", p["fg"], p["bg"], 4.5),
                    ("muted on chrome", p["muted"], p["bg"], 4.5),
                    ("ink on fields", p["fg"], p["entry"], 4.5),
                    ("selection", p["select_fg"], p["select_bg"], 4.5),
                    ("warning text", p["hint"], p["bg"], 4.5),
                    ("plot ink", p["plot_fg"], p["plot_bg"], 4.5),
                    ("accent on chrome", p["accent"], p["bg"], 3.0)):
                self.assertGreaterEqual(
                    themes.contrast(fg, bg), need, f"{name}: {label}")

    def test_data_colours_are_visible_and_distinct(self):
        for name, p in themes.PALETTES.items():
            cyc = p["cycle"]
            for c in cyc:
                self.assertGreaterEqual(themes.contrast(c, p["plot_bg"]), 3.0,
                                        f"{name}: {c} on the plot")
            for i, a in enumerate(cyc):
                for b in cyc[i + 1:]:
                    self.assertGreater(delta_e(a, b), 18.0,
                                       f"{name}: {a} vs {b} too similar")

    def test_dark_plot_is_recessed_below_the_chrome(self):
        d = themes.PALETTES["Dark"]
        self.assertLess(themes.luminance(d["plot_bg"]),
                        themes.luminance(d["bg"]))

    def test_light_is_default_and_system_keeps_native(self):
        self.assertEqual(themes.DEFAULT, "Light")
        self.assertEqual(themes.NATIVE, "System")
        self.assertIn("System", themes.THEME_NAMES)

    def test_print_style_is_white_paper(self):
        rc = themes.mpl_rc(themes.PRINT)
        self.assertEqual(rc["figure.facecolor"].lower(), "#ffffff")
        self.assertEqual(rc["text.color"].lower(), "#000000")


class TestColourMaths(unittest.TestCase):
    def test_contrast_extremes(self):
        self.assertAlmostEqual(themes.contrast("#000000", "#FFFFFF"), 21.0, 1)
        self.assertAlmostEqual(themes.contrast("#777777", "#777777"), 1.0, 3)

    def test_ramp_fades_but_stays_visible(self):
        bg = "#FFFFFF"
        cols = themes.ramp("#0072B2", 10, bg)
        self.assertEqual(cols[0].upper(), "#0072B2")
        lum = [themes.luminance(c) for c in cols]
        self.assertEqual(lum, sorted(lum))                # fading toward bg
        self.assertGreaterEqual(themes.contrast(cols[-1], bg), 1.5)
        self.assertEqual(themes.ramp("#0072B2", 1, bg), ["#0072B2"])


def reg(name, sample="", source="a.vms", **kw):
    return Region(name=name, index=0, offset=0, energy=[1.0, 2.0],
                  counts=[1.0, 2.0], decodable=True, sample=sample,
                  source=source, **kw)


class FakeDoc:
    def __init__(self, path, regions):
        self.path, self.regions = path, regions


class TestTraceColours(unittest.TestCase):
    def test_one_colour_per_file_when_several_files(self):
        a = FakeDoc("a", [reg("C 1s", "S1"), reg("C 1s", "S2")])
        b = FakeDoc("b", [reg("C 1s", "S1")])
        slots = ee.colour_slots([a, b])
        self.assertEqual(slots[id(a.regions[0])], slots[id(a.regions[1])])
        self.assertNotEqual(slots[id(a.regions[0])], slots[id(b.regions[0])])

    def test_one_colour_per_sample_within_a_single_file(self):
        a = FakeDoc("a", [reg("C 1s", "S1"), reg("O 1s", "S1"),
                          reg("C 1s", "S2")])
        s = ee.colour_slots([a])
        self.assertEqual(s[id(a.regions[0])], s[id(a.regions[1])])
        self.assertNotEqual(s[id(a.regions[0])], s[id(a.regions[2])])

    def test_slots_depend_on_load_order_only(self):
        a = FakeDoc("a", [reg("C 1s")])
        b = FakeDoc("b", [reg("C 1s")])
        self.assertEqual(ee.colour_slots([a, b]), ee.colour_slots([a, b]))

    def test_single_hue_stack_becomes_a_ramp(self):
        cyc = themes.PALETTES["Light"]["cycle"]
        cols = ee.stack_colours([0] * 6, cyc, "#FFFFFF")
        self.assertEqual(len(set(cols)), 6)
        self.assertEqual(cols[0].upper(), cyc[0].upper())

    def test_mixed_stack_uses_categorical_colours(self):
        cyc = themes.PALETTES["Light"]["cycle"]
        self.assertEqual(ee.stack_colours([0, 1, 0], cyc, "#FFFFFF"),
                         [cyc[0], cyc[1], cyc[0]])
        self.assertEqual(ee.stack_colours([9], cyc, "#FFFFFF"),
                         [cyc[9 % len(cyc)]])


class TestPlotHelpers(unittest.TestCase):
    def test_nice_step(self):
        for x, want in ((0.9, 0.5), (1, 1), (1.9, 1), (2.4, 2), (7, 5),
                        (1234, 1000), (0.037, 0.02), (0, 1)):
            self.assertAlmostEqual(ee.nice_step(x), want, msg=str(x))

    def test_dodge_separates_labels_and_keeps_order(self):
        vals = [10.0, 10.2, 10.3, 30.0, 5.0]
        out = ee.dodge(vals, 2.0)
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        for a, b in zip(order, order[1:]):
            self.assertGreaterEqual(out[b] - out[a], 2.0 - 1e-9)
        self.assertEqual(ee.dodge([1.0], 2.0), [1.0])

    def test_trace_labels(self):
        self.assertEqual(ee.trace_label(reg("C 1s", "Pt #001"),
                                        show_name=False), "Pt #001")
        self.assertEqual(ee.trace_label(reg("C 1s", "Pt #001"),
                                        show_name=True), "Pt #001 C 1s")
        self.assertEqual(ee.trace_label(reg("C 1s", "", "file.vms"), True),
                         "file")
        self.assertEqual(ee.trace_label(reg("C 1s", "")), "C 1s")
        lvl = reg("Mo 3d", "P", etch_level=3, etch_time=90.0)
        self.assertEqual(ee.trace_label(lvl), "L3 (90 s)")
        self.assertLessEqual(len(ee.trace_label(reg("C 1s", "x" * 60))), 23)


class TestFonts(unittest.TestCase):
    def test_bundled_files_exist_with_licence(self):
        self.assertEqual(len(fonts.font_paths()), len(fonts.FILES))
        self.assertTrue(os.path.isfile(os.path.join(fonts.FONT_DIR, "OFL.txt")))

    def test_missing_font_files_fall_back_quietly(self):
        old = fonts.FONT_DIR
        try:
            fonts.FONT_DIR = os.path.join(old, "does-not-exist")
            self.assertFalse(fonts.register_process_fonts())
            self.assertEqual(fonts.font_paths(), [])
        finally:
            fonts.FONT_DIR = old


if __name__ == "__main__":
    unittest.main()
