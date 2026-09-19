"""Plot style: the field list, validation, presets, and that the style really
reaches the drawing (fonts, lines, ticks, grid, frame, legend, titles, axis
ranges, y units, export size).

Run:  python -m unittest discover tests
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import plotstyle as ps  # noqa: E402
import themes  # noqa: E402
from readers import Region  # noqa: E402

try:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure
    HAVE_MPL = True
except Exception:
    HAVE_MPL = False


class TestFields(unittest.TestCase):
    def test_keys_are_unique_and_defaults_are_valid(self):
        keys = [f.key for f in ps.FIELDS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(ps.sanitise(None), ps.DEFAULTS)
        for f in ps.FIELDS:
            self.assertEqual(ps.sanitise({f.key: f.default})[f.key],
                             f.default, f.key)

    def test_every_field_is_well_formed(self):
        kinds = {"choice", "float", "int", "bool", "text", "optfloat"}
        for f in ps.FIELDS:
            self.assertIn(f.kind, kinds, f.key)
            self.assertTrue(f.label and f.group, f.key)
            if f.kind == "choice":
                self.assertIn(f.default, f.choices, f.key)
            if f.kind in ("float", "int"):
                self.assertIsNotNone(f.lo, f.key)
                self.assertIsNotNone(f.hi, f.key)
                self.assertTrue(f.lo <= f.default <= f.hi, f.key)
                self.assertTrue(f.step, f.key)

    def test_groups_keep_field_order(self):
        self.assertEqual(ps.GROUPS[0], "Text")
        self.assertEqual(set(ps.GROUPS), {f.group for f in ps.FIELDS})

    def test_choices_map_to_matplotlib_values(self):
        f = ps.BY_KEY
        self.assertEqual(set(f["line_style"].choices), set(ps.LINE_STYLES))
        self.assertEqual(set(f["marker"].choices), set(ps.MARKERS))
        self.assertEqual(set(f["y_units"].choices), set(ps.Y_UNITS))
        self.assertEqual(set(f["grid"].choices), set(ps.GRID_MODES))


class TestSanitise(unittest.TestCase):
    def test_unknown_and_wrong_types_take_the_default(self):
        s = ps.sanitise({"nonsense": 1, "font_size": "big", "frame": "Round",
                         "grid": 3, "title_bold": "yes", "line_width": None,
                         "font": ["Arial"]})
        self.assertEqual(s, ps.DEFAULTS)

    def test_numbers_are_clamped_and_coerced(self):
        s = ps.sanitise({"font_size": 500, "tick_size": 1, "line_width": "2",
                         "fig_dpi": 10000, "marker_size": float("nan"),
                         "tick_length": float("inf")})
        self.assertEqual(s["font_size"], 32)
        self.assertEqual(s["tick_size"], 4)
        self.assertEqual(s["line_width"], 2.0)
        self.assertEqual(s["fig_dpi"], 1200)
        self.assertEqual(s["marker_size"], ps.DEFAULTS["marker_size"])
        self.assertEqual(s["tick_length"], ps.DEFAULTS["tick_length"])
        self.assertIsInstance(s["font_size"], int)

    def test_booleans_are_not_numbers(self):
        self.assertEqual(ps.sanitise({"line_width": True})["line_width"],
                         ps.DEFAULTS["line_width"])

    def test_ranges_swap_when_reversed_and_may_be_open(self):
        s = ps.sanitise({"x_min": 300, "x_max": 280, "y_min": None,
                         "y_max": "5"})
        self.assertEqual((s["x_min"], s["x_max"]), (280.0, 300.0))
        self.assertEqual((s["y_min"], s["y_max"]), (None, 5.0))
        self.assertIsNone(ps.sanitise({"x_min": ""})["x_min"])

    def test_text_is_stripped_and_capped(self):
        s = ps.sanitise({"title_text": "  My title ", "xlabel": "x" * 999})
        self.assertEqual(s["title_text"], "My title")
        self.assertEqual(len(s["xlabel"]), 200)

    def test_changed_is_the_compact_form(self):
        self.assertEqual(ps.changed(ps.DEFAULTS), {})
        self.assertEqual(ps.changed({"font_size": 12}), {"font_size": 12})
        self.assertEqual(ps.sanitise(ps.changed({"font_size": 12})),
                         ps.sanitise({"font_size": 12}))

    def test_parse_field(self):
        f = ps.BY_KEY
        self.assertEqual(ps.parse_field(f["x_min"], " 280 "), 280.0)
        self.assertIsNone(ps.parse_field(f["x_min"], ""))
        self.assertEqual(ps.parse_field(f["font_size"], "11.4"), 11)
        self.assertEqual(ps.parse_field(f["xlabel"], ""), "")
        with self.assertRaises(ValueError):
            ps.parse_field(f["font_size"], "abc")
        with self.assertRaises(ValueError):
            ps.parse_field(f["x_max"], "nan")

    def test_resolve_fills_gaps_and_ignores_unknown_keys(self):
        self.assertEqual(ps.resolve(None), ps.DEFAULTS)
        r = ps.resolve({"font_size": 12, "junk": 1})
        self.assertEqual(r["font_size"], 12)
        self.assertNotIn("junk", r)
        full = ps.sanitise({"font_size": 12})
        self.assertIs(ps.resolve(full), full)


class TestPresets(unittest.TestCase):
    def test_builtins_are_valid_and_distinct(self):
        seen = []
        for name in ps.BUILTIN_PRESETS:
            st = ps.preset_style(name)
            self.assertEqual(st, ps.sanitise(st), name)
            self.assertNotIn(st, seen, name)
            seen.append(st)
        self.assertEqual(ps.preset_style("Default"), ps.DEFAULTS)

    def test_a_preset_replaces_everything(self):
        st = ps.preset_style("Journal (compact)")
        self.assertEqual(st["font_size"], 8)
        self.assertEqual(st["grid"], "Off")          # untouched = default

    def test_names_and_user_presets(self):
        user = {"Mine": {"font_size": 12}, "Default": {"font_size": 1}}
        self.assertEqual(ps.preset_names(user)[:len(ps.BUILTIN_PRESETS)],
                         list(ps.BUILTIN_PRESETS))
        self.assertEqual(ps.preset_names(user)[-1], "Mine")
        self.assertEqual(ps.preset_style("Mine", user)["font_size"], 12)
        self.assertEqual(ps.preset_style("Default", user), ps.DEFAULTS)
        self.assertIsNone(ps.preset_style("Nope", user))

    def test_clean_presets_drops_bad_entries(self):
        raw = {"Good": {"font_size": 12, "junk": 3}, "": {}, "Default": {},
               "Bad": "text", 5: {}}
        self.assertEqual(ps.clean_presets(raw), {"Good": {"font_size": 12}})
        self.assertEqual(ps.clean_presets("x"), {})

    def test_matching_preset(self):
        self.assertEqual(ps.matching_preset(ps.DEFAULTS), "Default")
        self.assertEqual(ps.matching_preset(
            ps.preset_style("Data points")), "Data points")
        self.assertIsNone(ps.matching_preset({"font_size": 13}))
        self.assertEqual(ps.matching_preset({"font_size": 13},
                                            {"Big": {"font_size": 13}}), "Big")


class TestHelpers(unittest.TestCase):
    def test_default_lines_match_the_original_look(self):
        kw = ps.line_kwargs(None, 3)
        self.assertEqual((kw["lw"], kw["ls"]), (1.1, "-"))
        self.assertAlmostEqual(ps.line_kwargs(None, 20)["lw"], 0.8, 1)
        self.assertAlmostEqual(ps.line_kwargs(None, 3, True)["lw"], 1.9)

    def test_markers_and_never_draw_nothing(self):
        kw = ps.line_kwargs({"marker": "Circle", "marker_size": 5}, 1)
        self.assertEqual((kw["marker"], kw["ms"]), ("o", 5))
        kw = ps.line_kwargs({"line_style": "None"}, 1)
        self.assertEqual(kw["ls"], "None")
        self.assertEqual(kw["marker"], "o")        # markers-only fallback
        kw = ps.line_kwargs({"marker": "Plus"}, 1)
        self.assertIn("mew", kw)

    def test_units(self):
        self.assertEqual(ps.y_unit(None, "counts/s"), "counts/s")
        self.assertEqual(ps.y_unit({"y_units": "Counts"}, "counts/s"),
                         "counts")
        self.assertEqual(ps.y_unit({"y_units": "None"}, "counts/s"), "")
        self.assertEqual(ps.with_unit("Intensity", "a.u."), "Intensity (a.u.)")
        self.assertEqual(ps.with_unit("Intensity", ""), "Intensity")

    def test_titles(self):
        self.assertEqual(ps.panel_titles(None, "C 1s", "S1"), ("C 1s", "S1"))
        self.assertEqual(ps.panel_titles({"title_text": "Fig"}, "C 1s", "S1"),
                         ("Fig", "S1"))
        self.assertEqual(ps.panel_titles({"show_title": False}, "C 1s", "S1"),
                         ("", "S1"))
        self.assertEqual(ps.panel_titles({"show_subtitle": False}, "C 1s",
                                         "S1"), ("C 1s", ""))

    def test_note_size_and_gutter_follow_the_tick_size(self):
        self.assertEqual(ps.note_size(None), 8)
        self.assertEqual(ps.note_size({"tick_size": 12}, -1), 11)
        self.assertEqual(ps.note_size({"tick_size": 4}, -3), 4)
        self.assertEqual(ps.label_gutter_points(None), 78.0)
        self.assertEqual(ps.label_gutter_points({"tick_size": 16}), 156.0)
        self.assertTrue(ps.end_labels(None))
        self.assertFalse(ps.end_labels({"labels": "Legend"}))

    def test_export_size(self):
        self.assertEqual(ps.export_size(None), (8.0, 5.0, 300))
        self.assertEqual(ps.export_size(ps.preset_style("Journal (compact)")),
                         (3.4, 2.7, 600))
        self.assertEqual(ps.export_size({"fig_width": 6}, (9, 9)),
                         (6, 9, 300))

    def test_rc_overrides(self):
        rc = ps.rc_overrides(None)
        self.assertEqual(rc["font.size"], 9)
        self.assertEqual(rc["axes.titlesize"], 10)
        self.assertEqual(rc["xtick.labelsize"], 8)
        self.assertFalse(rc["axes.spines.top"])
        self.assertFalse(rc["axes.grid"])
        self.assertEqual(rc["font.family"], ["DejaVu Sans"])
        self.assertEqual(ps.rc_overrides(None, "IBM Plex Sans")["font.family"],
                         ["IBM Plex Sans", "DejaVu Sans"])
        rc = ps.rc_overrides({"font": "Arial", "frame": "Box",
                              "grid": "Horizontal", "tick_direction": "in",
                              "title_bold": False, "minor_ticks": True})
        self.assertEqual(rc["font.family"], ["Arial", "DejaVu Sans"])
        self.assertTrue(rc["axes.spines.top"] and rc["axes.spines.right"])
        self.assertEqual((rc["axes.grid"], rc["axes.grid.axis"]),
                         (True, "y"))
        self.assertEqual(rc["xtick.direction"], "in")
        self.assertEqual(rc["axes.titleweight"], "normal")
        self.assertTrue(rc["xtick.minor.visible"])

    def test_mpl_rc_layers_the_style_over_the_theme(self):
        pal = themes.PALETTES["Light"]
        plain = themes.mpl_rc(pal)
        self.assertEqual(themes.mpl_rc(pal, style=ps.DEFAULTS)["font.size"],
                         plain["font.size"])
        rc = themes.mpl_rc(pal, style={"font_size": 14})
        self.assertEqual(rc["font.size"], 14)
        self.assertEqual(rc["axes.facecolor"], plain["axes.facecolor"])
        self.assertEqual(themes.mpl_rc(pal, style=ps.DEFAULTS)["axes.linewidth"],
                         plain["axes.linewidth"])


def reg(sample="S1", name="C 1s", n=41, lo=280.0, hi=292.0, peak=286.0,
        scale=1.0):
    e = [hi - i * (hi - lo) / (n - 1) for i in range(n)]
    c = [scale * (100 + 900 * 2.718 ** (-((x - peak) / 1.0) ** 2)) for x in e]
    return Region(name=name, index=0, offset=0, energy=e, counts=c,
                  decodable=True, sample=sample, photon_energy=1486.6,
                  energy_label="Binding Energy", source="a.vms",
                  count_units="counts/s", count_label="Intensity")


@unittest.skipUnless(HAVE_MPL, "matplotlib not installed")
class TestDrawing(unittest.TestCase):
    """The style must reach the axes that are actually drawn."""

    def stack(self, n=3, style=None, **kw):
        import plots
        regs = [reg(sample=f"S{i}", scale=1 + i) for i in range(n)]
        pal = themes.PALETTES["Light"]
        cols = pal["cycle"][:n]
        with matplotlib.rc_context(themes.mpl_rc(pal, style=style)):
            fig = Figure(figsize=(6, 4), dpi=80)
            ax = fig.add_subplot(111)
            plots.draw_stack(ax, regs, 0.6, "None", None, cols, "C 1s",
                             f"{n} spectra", (), False, style=style, **kw)
            fig.canvas.draw()
        return fig, ax

    def texts(self, ax):
        return [t.get_text() for t in ax.texts]

    @staticmethod
    def traces(ax):
        """The spectra (a stacked panel also draws its scale bar)."""
        return [ln for ln in ax.lines if len(ln.get_xdata()) > 5]

    def test_default_style_draws_as_before(self):
        fig, ax = self.stack(3)
        self.assertEqual(len(self.traces(ax)), 3)
        self.assertAlmostEqual(self.traces(ax)[0].get_linewidth(), 1.1)
        self.assertEqual(len(ax.collections), 0)          # no fill
        self.assertIsNone(ax.get_legend())
        self.assertTrue(ax.xaxis_inverted())
        self.assertEqual(ax.get_title(loc="left"), "C 1s")
        self.assertEqual(ax.get_title(loc="right"), "3 spectra")
        self.assertEqual(ax.get_xlabel(), "Binding energy (eV)")
        self.assertTrue({"S0", "S1", "S2"} <= set(self.texts(ax)))

    def test_line_width_style_marker(self):
        style = ps.sanitise({"line_width": 2.5, "line_style": "Dashed",
                             "marker": "Square", "marker_size": 6})
        _fig, ax = self.stack(2, style)
        ln = self.traces(ax)[0]
        self.assertEqual(ln.get_linewidth(), 2.5)
        self.assertEqual(ln.get_linestyle(), "--")
        self.assertEqual(ln.get_marker(), "s")
        self.assertEqual(ln.get_markersize(), 6)

    def test_fill_under_adds_one_shading_per_trace(self):
        _fig, ax = self.stack(3, ps.sanitise({"fill_under": True}))
        self.assertEqual(len(ax.collections), 3)

    def test_legend_mode_replaces_the_end_labels(self):
        style = ps.sanitise({"labels": "Legend", "legend_frame": True})
        _fig, ax = self.stack(3, style)
        leg = ax.get_legend()
        self.assertIsNotNone(leg)
        self.assertEqual([t.get_text() for t in leg.get_texts()],
                         ["S0", "S1", "S2"])
        self.assertNotIn("S0", self.texts(ax))
        self.assertTrue(leg.get_frame_on())

    def test_no_labels(self):
        _fig, ax = self.stack(3, ps.sanitise({"labels": "None"}))
        self.assertIsNone(ax.get_legend())
        self.assertFalse({"S0", "S1", "S2"} & set(self.texts(ax)))

    def test_titles_and_labels(self):
        style = ps.sanitise({"title_text": "Carbon", "show_subtitle": False,
                             "xlabel": "BE / eV"})
        _fig, ax = self.stack(3, style)
        self.assertEqual(ax.get_title(loc="left"), "Carbon")
        self.assertEqual(ax.get_title(loc="right"), "")
        self.assertEqual(ax.get_xlabel(), "BE / eV")
        _fig, ax = self.stack(3, ps.sanitise({"show_title": False}))
        self.assertEqual(ax.get_title(loc="left"), "")

    def test_single_spectrum_y_label_and_units(self):
        import plots
        pal = themes.PALETTES["Light"]
        for style, want in ((None, "Intensity (counts/s)"),
                            ({"y_units": "Arbitrary units (a.u.)"},
                             "Intensity (a.u.)"),
                            ({"y_units": "None"}, "Intensity"),
                            ({"ylabel": "Signal"}, "Signal")):
            st = ps.sanitise(style)
            with matplotlib.rc_context(themes.mpl_rc(pal, style=st)):
                fig = Figure()
                ax = fig.add_subplot(111)
                plots.draw_stack(ax, [reg()], 0.6, "None", None, ["#000"],
                                 "C 1s", "", (), False, style=st)
            self.assertEqual(ax.get_ylabel(), want, style)

    def test_energy_range_keeps_the_axis_direction(self):
        style = ps.sanitise({"x_min": 283, "x_max": 290})
        _fig, ax = self.stack(2, style)
        a, b = ax.get_xlim()
        self.assertTrue(a > b)                  # still binding energy
        self.assertEqual((round(b, 6), round(a, 6)), (283.0, 290.0))
        # one open end keeps the data limit on the other side
        _fig, ax = self.stack(2, ps.sanitise({"x_max": 288}))
        a, b = ax.get_xlim()
        self.assertEqual(round(a, 6), 288.0)
        self.assertLess(b, 281)

    def test_energy_window_skips_panels_it_does_not_reach(self):
        """One C 1s window on a page that also holds an O 1s panel."""
        import plots
        pal = themes.PALETTES["Light"]
        style = ps.sanitise({"x_min": 282, "x_max": 292})
        with matplotlib.rc_context(themes.mpl_rc(pal, style=style)):
            fig = Figure()
            ax = fig.add_subplot(111)
            plots.draw_stack(ax, [reg(name="O 1s", lo=525, hi=540, peak=532)],
                             0.6, "None", None, ["#000"], "O 1s", "", (),
                             False, style=style)
        self.assertGreater(min(ax.get_xlim()), 500)          # own range kept

    def test_x_window(self):
        st = ps.sanitise({"x_min": 282, "x_max": 292})
        self.assertEqual(ps.x_window(st, 278, 296), (282.0, 292.0))
        self.assertEqual(ps.x_window(st, 300, 310), None)        # misses
        self.assertEqual(ps.x_window(st, 285, 288), (282.0, 292.0))
        self.assertEqual(ps.x_window(ps.sanitise({"x_max": 288}), 280, 296),
                         (280, 288.0))
        self.assertIsNone(ps.x_window(ps.sanitise({"x_max": 288}), 525, 540))
        self.assertIsNone(ps.x_window(ps.DEFAULTS, 0, 1))

    def test_box_frame_keeps_the_left_line_on_stacks(self):
        _fig, ax = self.stack(3, ps.sanitise({"frame": "Box"}))
        self.assertTrue(ax.spines["left"].get_visible())
        _fig, ax = self.stack(3)
        self.assertFalse(ax.spines["left"].get_visible())

    def test_intensity_range(self):
        _fig, ax = self.stack(2, ps.sanitise({"y_min": 0, "y_max": 5000}))
        self.assertEqual(ax.get_ylim(), (0.0, 5000.0))

    def test_axis_style_reaches_the_ticks_and_frame(self):
        style = ps.sanitise({"frame": "Box", "grid": "Both",
                             "tick_direction": "in", "minor_ticks": True,
                             "spine_width": 1.5})
        _fig, ax = self.stack(1, style)
        self.assertTrue(ax.spines["top"].get_visible())
        self.assertEqual(ax.spines["left"].get_linewidth(), 1.5)
        self.assertTrue(any(g.get_visible()
                            for g in ax.get_xgridlines()))
        self.assertGreater(len(ax.xaxis.get_minor_ticks()), 0)
        self.assertEqual(ax.xaxis.get_major_ticks()[0]._tickdir, "in")

    def test_font_sizes_reach_titles_labels_and_notes(self):
        style = ps.sanitise({"title_size": 20, "font_size": 15,
                             "tick_size": 12})
        _fig, ax = self.stack(3, style)
        self.assertEqual(ax.title.get_fontsize(), 20)
        self.assertEqual(ax.xaxis.label.get_fontsize(), 15)
        self.assertEqual(ax.get_xticklabels()[0].get_fontsize(), 12)
        end = [t for t in ax.texts if t.get_text() == "S0"][0]
        self.assertEqual(end.get_fontsize(), 12)

    def test_font_family_falls_back_when_missing(self):
        # an uninstalled font must not break drawing
        _fig, ax = self.stack(2, ps.sanitise({"font": "No Such Font 123"}))
        self.assertEqual(len(self.traces(ax)), 2)

    def test_every_preset_draws(self):
        for name in ps.BUILTIN_PRESETS:
            _fig, ax = self.stack(3, ps.preset_style(name))
            self.assertEqual(len(self.traces(ax)), 3, name)

    def test_heatmap_and_waterfall_accept_the_style(self):
        import plots
        import viewdata
        from matplotlib.colors import LinearSegmentedColormap
        regs = [reg(sample="S", scale=1 + i) for i in range(4)]
        zi = viewdata.ZInfo([0.0, 1.0, 2.0, 3.0], "Trace", "Trace order")
        pal = themes.PALETTES["Light"]
        style = ps.sanitise({"title_size": 16, "xlabel": "BE", "x_min": 283,
                             "x_max": 289, "y_units": "Counts"})
        with matplotlib.rc_context(themes.mpl_rc(pal, style=style)):
            fig = Figure(figsize=(5, 4))
            ax = fig.add_subplot(111)
            plots.draw_heatmap(fig, ax, regs, zi, "None",
                               LinearSegmentedColormap.from_list(
                                   "h", ["#fff", "#000"]),
                               "C 1s", "4", style=style)
            fig.canvas.draw()
            self.assertEqual(ax.title.get_fontsize(), 16)
            self.assertEqual(ax.get_xlabel(), "BE")
            self.assertEqual(sorted(ax.get_xlim()), [283.0, 289.0])
            self.assertIn("counts", fig.axes[1].get_ylabel())
            fig = Figure(figsize=(5, 4))
            ax = fig.add_subplot(111, projection="3d")
            plots.draw_waterfall3d(ax, regs, zi, "None", pal["cycle"][:4],
                                   "C 1s", "4", pal, style=style)
            fig.canvas.draw()
            self.assertEqual(sorted(ax.get_xlim()), [283.0, 289.0])
            self.assertEqual(ax.get_xlabel(), "BE")


if __name__ == "__main__":
    unittest.main()
