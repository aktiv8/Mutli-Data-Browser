"""Tk-free tests for the alternative views: energy axis, z axis, heat-map
resampling and the extra grouping modes.

Run:  python -m unittest discover tests
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import escape_explorer as ee  # noqa: E402
import themes  # noqa: E402
import viewdata  # noqa: E402
from readers import Region  # noqa: E402


def reg(lo=280.0, hi=290.0, n=11, hv=1486.6, label="Binding Energy",
        sample="S1", name="C 1s", source="a.vgd", **kw):
    e = [hi - i * (hi - lo) / (n - 1) for i in range(n)]
    return Region(name=name, index=0, offset=0, energy=e, counts=[1.0] * n,
                  decodable=True, sample=sample, photon_energy=hv,
                  energy_label=label, source=source, **kw)


class TestEnergyAxis(unittest.TestCase):
    def test_binding_is_native_and_inverted(self):
        a = viewdata.energy_axis(reg(), "Binding")
        self.assertTrue(a.invert and a.ok)
        self.assertEqual(a.label, "Binding Energy")

    def test_kinetic_is_hv_minus_be_and_not_inverted(self):
        r = reg()
        a = viewdata.energy_axis(r, "Kinetic")
        self.assertFalse(a.invert)
        self.assertEqual(a.label, "Kinetic Energy")
        for be, ke in zip(r.energy, a.x):
            self.assertAlmostEqual(be + ke, 1486.6)

    def test_kinetic_without_photon_energy_keeps_binding(self):
        a = viewdata.energy_axis(reg(hv=None), "Kinetic")
        self.assertFalse(a.ok)
        self.assertTrue(a.invert)

    def test_native_kinetic_region_is_left_alone(self):
        r = reg(label="Kinetic Energy")
        a = viewdata.energy_axis(r, "Kinetic")
        self.assertEqual(a.x, r.energy)
        self.assertFalse(a.invert)

    def test_photon_energy_helpers(self):
        self.assertEqual(viewdata.photon_energy([reg(hv=None), reg(hv=1253.6)]),
                         1253.6)
        self.assertTrue(viewdata.mixed_photon_energy([reg(), reg(hv=1253.6)]))
        self.assertFalse(viewdata.mixed_photon_energy([reg(), reg()]))


class TestParseDate(unittest.TestCase):
    def test_formats(self):
        for text in ("2008-05-12 17:34:00", "2008-05-12T17:34:00",
                     "12/05/2008 17:34:00", "2008-05-12 17:34:00.123",
                     "2008-05-12 17:34:00+01:00"):
            d = viewdata.parse_date(text)
            self.assertIsNotNone(d, text)
            self.assertEqual((d.year, d.month, d.day), (2008, 5, 12), text)

    def test_junk(self):
        self.assertIsNone(viewdata.parse_date(""))
        self.assertIsNone(viewdata.parse_date("not a date"))


class TestZAxis(unittest.TestCase):
    def series(self, **per):
        n = len(next(iter(per.values())))
        return [reg(**{k: v[i] for k, v in per.items()}) for i in range(n)]

    def test_auto_prefers_etch_time(self):
        rs = self.series(etch_time=[0, 30, 60], etch_level=[0, 1, 2])
        z = viewdata.resolve_z(rs)
        self.assertEqual((z.mode, z.values), ("Etch time", [0, 30, 60]))

    def test_all_zero_etch_time_counts_as_absent(self):
        rs = self.series(etch_time=[0.0, 0.0, 0.0], etch_level=[0, 1, 2])
        self.assertEqual(viewdata.resolve_z(rs).mode, "Etch level")

    def test_acquisition_time_via_callback(self):
        rs = self.series(date=["2020-01-01 10:00:00", "2020-01-01 10:10:00",
                               "2020-01-01 10:30:00"])
        z = viewdata.resolve_z(rs, "Auto", lambda r: r.date)
        self.assertEqual(z.mode, "Acquisition time")
        self.assertEqual(z.values, [0.0, 10.0, 30.0])
        self.assertIn("min", z.label)
        # the callback, not Region.date, is the source
        z2 = viewdata.resolve_z(rs, "Auto", lambda r: "")
        self.assertEqual(z2.mode, "Trace order")

    def test_trace_order_is_last_resort(self):
        z = viewdata.resolve_z([reg(), reg(), reg()])
        self.assertEqual((z.mode, z.values), ("Trace order", [1.0, 2.0, 3.0]))

    def test_explicit_mode_falls_back_when_unusable(self):
        rs = self.series(etch_level=[0, 1, 2])
        self.assertEqual(viewdata.resolve_z(rs, "Etch time").mode,
                         "Etch level")
        self.assertEqual(viewdata.resolve_z(rs, "Trace order").mode,
                         "Trace order")

    def test_z_sorted_orders_regions(self):
        rs = self.series(etch_time=[60, 0, 30])
        order, z = viewdata.z_sorted(rs)
        self.assertEqual(order, [1, 2, 0])
        self.assertEqual(z.values, [0, 30, 60])

    def test_duplicate_z_falls_back_to_trace_order(self):
        rs = self.series(etch_level=[0, 1, 1, 2])
        order, z = viewdata.z_sorted(rs, "Etch level")
        self.assertEqual((order, z.mode), ([0, 1, 2, 3], "Trace order"))
        self.assertEqual(z.values, [1, 2, 3, 4])


class TestHeatMatrix(unittest.TestCase):
    def test_common_grid_and_nan_padding(self):
        import numpy as np
        a = reg(280, 290, 11)              # 280..290, step 1, descending
        b = reg(284, 294, 11)
        grid, rows = viewdata.build_matrix([a.energy, b.energy],
                                           [[1.0] * 11, [2.0] * 11])
        self.assertEqual((grid[0], grid[-1]), (280.0, 294.0))
        self.assertTrue(np.all(np.diff(grid) > 0))
        self.assertEqual(rows.shape, (2, len(grid)))
        self.assertTrue(np.isnan(rows[0, -1]) and np.isnan(rows[1, 0]))
        self.assertAlmostEqual(rows[0, 0], 1.0)
        self.assertAlmostEqual(rows[1, -1], 2.0)

    def test_interpolates_onto_grid(self):
        import numpy as np
        coarse = [0.0, 1.0, 2.0]
        fine = [0.0, 0.5, 1.0, 1.5, 2.0]        # finer step sets the grid
        grid, rows = viewdata.build_matrix(
            [coarse, fine], [[0, 10, 20], [0, 2.5, 5, 7.5, 10]])
        self.assertEqual(list(grid), fine)
        self.assertTrue(np.allclose(rows[0], [0, 5, 10, 15, 20]))
        self.assertTrue(np.allclose(rows[1], [0, 2.5, 5, 7.5, 10]))

    def test_point_cap(self):
        xs = [float(i) for i in range(1001)]
        grid, _rows = viewdata.build_matrix([xs, xs], [xs, xs],
                                            max_points=50)
        self.assertEqual(len(grid), 50)

    def test_edges(self):
        self.assertEqual(viewdata.edges([0, 10, 30]), [-5, 5, 20, 40])
        self.assertEqual(viewdata.edges([3]), [2.5, 3.5])


class TestNewGroupModes(unittest.TestCase):
    def setUp(self):
        self.rs = [reg(sample="A", source="one.vgd"),
                   reg(sample="A", source="one.vgd"),
                   reg(sample="B", source="one.vgd"),
                   reg(sample="A", source="two.vgd"),
                   reg(sample="A", source="one.vgd", name="O 1s")]

    def test_per_sample(self):
        g = ee.group_regions(self.rs, "sample")
        self.assertEqual([(k, len(v)) for k, v in g],
                         [("C 1s · A", 3), ("C 1s · B", 1), ("O 1s · A", 1)])

    def test_per_file(self):
        g = ee.group_regions(self.rs, "file")
        self.assertEqual([(k, len(v)) for k, v in g],
                         [("C 1s · one", 3), ("C 1s · two", 1),
                          ("O 1s · one", 1)])

    def test_unnamed_sample_uses_bare_element(self):
        g = ee.group_regions([reg(sample="")], "sample")
        self.assertEqual(g[0][0], "C 1s")


class TestHeatPalettes(unittest.TestCase):
    def test_every_palette_has_a_monotonic_ramp(self):
        for name, p in themes.PALETTES.items():
            lum = [themes.luminance(c) for c in p["heat"]]
            self.assertGreaterEqual(len(lum), 4, name)
            up = all(b > a for a, b in zip(lum, lum[1:]))
            down = all(b < a for a, b in zip(lum, lum[1:]))
            self.assertTrue(up or down, f"{name}: lightness not monotonic")
            # weak signal recedes into the plot background, strong stands out
            bg = themes.luminance(p["plot_bg"])
            self.assertLess(abs(lum[0] - bg), abs(lum[-1] - bg), name)


try:
    import matplotlib  # noqa: F401
    HAVE_MPL = True
except Exception:
    HAVE_MPL = False


@unittest.skipUnless(HAVE_MPL, "matplotlib not installed")
class TestColourScales(unittest.TestCase):
    def test_theme_default_keeps_theme_colours(self):
        for name, p in themes.PALETTES.items():
            self.assertIsNone(themes.scale_colours("Theme default", False, 5,
                                                   p))
            cmap = themes.scale_colourmap("Theme default", False, p)
            from matplotlib.colors import LinearSegmentedColormap, to_hex
            ref = LinearSegmentedColormap.from_list("heat", list(p["heat"]))
            for t in (0.0, 0.3, 0.7, 1.0):
                self.assertEqual(to_hex(cmap(t)), to_hex(ref(t)), name)

    def test_every_scale_is_visible_on_every_palette(self):
        for pname, p in themes.PALETTES.items():
            for scale in themes.SCALE_NAMES[1:]:
                for n in (1, 2, 8, 30):
                    cols = themes.scale_colours(scale, False, n, p)
                    self.assertEqual(len(cols), n)
                    for c in cols:
                        self.assertGreaterEqual(
                            themes.contrast(c, p["plot_bg"]),
                            themes.MIN_TRACE_CONTRAST - 1e-9,
                            f"{pname}/{scale}/{n}: {c}")
                    if n <= 8:
                        self.assertEqual(len(set(cols)), n,
                                         f"{pname}/{scale}/{n}")

    def test_reverse_reverses(self):
        p = themes.PALETTES["Light"]
        fwd = themes.scale_colours("Viridis", False, 6, p)
        self.assertEqual(themes.scale_colours("Viridis", True, 6, p),
                         fwd[::-1])

    def test_colourmap_is_a_private_copy(self):
        p = themes.PALETTES["Light"]
        self.assertIsNot(themes.scale_colourmap("Viridis", False, p),
                         themes.scale_colourmap("Viridis", False, p))


class TestAxisColour(unittest.TestCase):
    def test_default_returns_the_palette_unchanged(self):
        p = themes.PALETTES["Light"]
        self.assertEqual(themes.with_axis_colour(p, "Theme default"), (p, ""))
        self.assertEqual(themes.with_axis_colour(p, "Custom…", None), (p, ""))

    def test_black_on_light_replaces_only_frame_and_text(self):
        p = themes.PALETTES["Light"]
        q, note = themes.with_axis_colour(p, "Black")
        self.assertEqual(note, "")
        self.assertEqual((q["muted"], q["plot_fg"]), ("#000000", "#000000"))
        self.assertEqual({k: v for k, v in q.items()
                          if k not in ("muted", "plot_fg")},
                         {k: v for k, v in p.items()
                          if k not in ("muted", "plot_fg")})
        self.assertNotEqual(p["muted"], "#000000")     # original untouched
        rc = themes.mpl_rc(q)
        self.assertEqual(rc["axes.edgecolor"], "#000000")
        self.assertEqual(rc["xtick.color"], "#000000")
        self.assertEqual(rc["axes.labelcolor"], "#000000")

    def test_invisible_choices_fall_back_with_a_note(self):
        for pname, bad in (("Dark", "Black"), ("Light", "White"),
                           ("High contrast", "Black")):
            p = themes.PALETTES[pname]
            q, note = themes.with_axis_colour(p, bad)
            self.assertIs(q, p, pname)
            self.assertIn("hard to see", note)

    def test_custom_colour(self):
        p = themes.PALETTES["Light"]
        q, note = themes.with_axis_colour(p, "Custom…", "#7A1F1F")
        self.assertEqual((q["muted"], note), ("#7A1F1F", ""))


if __name__ == "__main__":
    unittest.main()
