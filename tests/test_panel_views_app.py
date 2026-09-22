"""The per-panel views in the real window (needs a display and matplotlib;
skipped otherwise): panels draw in their own view, old figures carry none,
saved looks round-trip.

Run:  python -m unittest discover tests
"""

import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

try:
    import tkinter as tk
    import spectradeck as ee
    HAVE_MPL = ee.HAVE_MPL
except Exception:                                   # pragma: no cover
    tk, ee, HAVE_MPL = None, None, False

from readers import Region, SpectrumFile  # noqa: E402


def reg(name, sample, peak, level=None, n=61):
    e = [292.0 - i * 12.0 / (n - 1) for i in range(n)]
    c = [100 + 900 * math.exp(-((x - peak) / 1.0) ** 2) for x in e]
    return Region(name=name, index=0, offset=0, energy=e, counts=c,
                  decodable=True, sample=sample, photon_energy=1486.6,
                  pass_energy=20.0, dwell=0.1, step=0.2, etch_level=level,
                  etch_time=None if level is None else 30.0 * level,
                  source="a.vms", count_units="counts/s")


def doc(path, regions):
    f = SpectrumFile()
    f.path = path
    f.format_name = "Test"
    f.regions = regions
    f.instrument = {"Instrument": "Test Spec"}
    f._finish()
    return f


@unittest.skipUnless(HAVE_MPL, "matplotlib / Tk not available")
class TestPanelViewsInApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError:
            raise unittest.SkipTest("no display")
        cls.root.withdraw()
        cls.docs = {
            "depth.vms": doc("depth.vms", [reg("C 1s", "Depth", 286 - i / 5,
                                               level=i + 1)
                                           for i in range(5)]),
            "bulk.vms": doc("bulk.vms", [reg("O 1s", "Bulk", 288 - i / 3)
                                         for i in range(3)])}
        cls._load = ee.load_file
        ee.load_file = lambda p: cls.docs[os.path.basename(p)]
        cls.ws = ee.Workspace(cls.root)

    @classmethod
    def tearDownClass(cls):
        ee.load_file = cls._load
        cls.root.destroy()

    def setUp(self):
        ws = self.ws
        for d in list(ws.docs):
            ws.docs.remove(d)
        ws.file_ids.clear()
        ws.region_parser.clear()
        ws.group_var.set("Element, per sample")
        ws.view_var.set("Stack")
        ws.norm_var.set("None")
        ws.z_var.set("Auto")
        ws.scale_var.set("Binding")
        ws.panels_var.set("Auto")
        ws.traces_var.set("All")
        ws.panel_views = {}
        ws.trace_start = 0
        for p in self.docs:
            ws._add_file(p, file_id=p[:-4], refresh=False)
        ws._finish_adding()
        ws.checked = {id(r) for d in ws.docs for r in d.regions}
        self.keys = [k for k, _ in ws._groups()]

    def kinds(self):
        self.ws._render()
        return {self.ws._axmap[a]: v[1] for a, v in self.ws._axinfo.items()}

    def test_default_is_the_page_view_everywhere(self):
        self.assertEqual(set(self.kinds().values()), {"stack"})

    def test_panels_can_differ_on_one_page(self):
        depth, bulk = self.keys
        self.ws.panel_views = {depth: {"view": "Waterfall 3D"},
                               bulk: {"view": "Heatmap"}}
        k = self.kinds()
        self.assertEqual((k[depth], k[bulk]), ("waterfall 3d", "heatmap"))

    def test_page_default_still_applies_to_the_rest(self):
        depth, bulk = self.keys
        self.ws.view_var.set("Heatmap")
        self.ws.panel_views = {depth: {"view": "Stack"}}
        k = self.kinds()
        self.assertEqual((k[depth], k[bulk]), ("stack", "heatmap"))

    def test_series_panel_is_z_sorted_and_stack_can_reverse(self):
        depth, bulk = self.keys
        self.ws.panel_views = {depth: {"view": "Heatmap",
                                       "z_axis": "Etch level"},
                               bulk: {"reverse": True}}
        groups = dict(self.ws._groups())
        self.assertEqual([r.etch_level for r in groups[depth]],
                         [1, 2, 3, 4, 5])
        self.ws.panel_views = {}
        base = [id(r) for r in dict(self.ws._groups())[bulk]]
        self.ws.panel_views = {bulk: {"reverse": True}}
        self.assertEqual([id(r) for r in dict(self.ws._groups())[bulk]],
                         base[::-1])

    def test_fit_panel_shows_one_trace_and_moves_the_slider(self):
        depth, _bulk = self.keys
        self.ws.panel_views = {depth: {"view": "Fit"}}
        self.ws._render()
        self.assertEqual(self.ws._trace_limit_now, 1)
        self.assertEqual(int(float(self.ws.trace_scale.cget("to"))), 4)
        self.assertTrue(any("no fit stored" in n
                            for n in self.ws._view_notes))

    def test_zoom_is_kept_when_nothing_about_a_panel_changed(self):
        depth, _bulk = self.keys
        self.ws._render()
        ax = next(a for a, k in self.ws._axmap.items() if k == depth)
        ax.set_xlim(280.0, 284.0)
        ax.set_ylim(200.0, 800.0)
        self.ws._render()          # nothing changed: same ticks, same look
        ax2 = next(a for a, k in self.ws._axmap.items() if k == depth)
        self.assertEqual(ax2.get_xlim(), (280.0, 284.0))
        self.assertEqual(ax2.get_ylim(), (200.0, 800.0))

    def test_zoom_is_dropped_when_the_panels_own_data_changes(self):
        depth, _bulk = self.keys
        self.ws._render()
        ax = next(a for a, k in self.ws._axmap.items() if k == depth)
        ax.set_xlim(280.0, 284.0)
        ax.set_ylim(200.0, 800.0)
        self.ws.norm_var.set("Max = 1")    # the panel's own values change
        self.ws._render()
        ax2 = next(a for a, k in self.ws._axmap.items() if k == depth)
        self.assertNotEqual(ax2.get_ylim(), (200.0, 800.0))

    def test_old_look_without_panel_views_clears_them(self):
        depth, _bulk = self.keys
        st = self.ws.capture_state()
        old ={k: v for k, v in st.items() if k != "panel_views"}
        self.ws.panel_views = {depth: {"view": "Fit"}}
        with self.ws._temp_state(old):
            self.assertEqual(self.ws.panel_views, {})
        self.assertEqual(self.ws.panel_views, {depth: {"view": "Fit"}})

    def test_look_round_trips_and_is_sanitised(self):
        depth, bulk = self.keys
        self.ws.panel_views = {depth: {"view": "Waterfall 3D"}}
        st = self.ws.capture_state()
        self.assertEqual(st["panel_views"], self.ws.panel_views)
        self.ws.panel_views = {}
        self.ws.apply_state(st, render=False)
        self.assertEqual(self.ws.panel_views, {depth: {"view": "Waterfall 3D"}})
        self.ws.apply_state({"panel_views": {bulk: {"view": "nope"},
                                             depth: {"norm": "Max = 1"}}},
                            render=False)
        self.assertEqual(self.ws.panel_views, {depth: {"norm": "Max = 1"}})

    def test_figure_pages_are_drawn_per_panel(self):
        depth, bulk = self.keys
        self.ws.panel_views = {depth: {"view": "Waterfall 3D"}}
        pages = []
        self.ws._render_figure_pages(
            {"name": "F", "caption": "", "state": self.ws.capture_state()},
            pages.append)
        self.assertTrue(pages)
        three_d = [ax for pg in pages for ax in pg.axes
                   if getattr(ax, "name", "") == "3d"]
        self.assertEqual(len(three_d), 1)
        flat = [ax for pg in pages for ax in pg.axes
                if getattr(ax, "name", "") != "3d"]
        self.assertTrue(flat)

    def test_menu_edits_one_panel_only(self):
        depth, bulk = self.keys
        self.ws._set_panel_view(depth, "view", "Heatmap")
        self.ws._set_panel_view(bulk, "norm", "Max = 1")
        self.ws._set_panel_view(bulk, "fit_show", ("envelope", False))
        self.assertEqual(self.ws.panel_views,
                         {depth: {"view": "Heatmap"},
                          bulk: {"norm": "Max = 1",
                                 "fit_show": {"envelope": False}}})
        self.ws.reset_panel_views(depth)
        self.assertEqual(list(self.ws.panel_views), [bulk])
        self.ws.reset_panel_views()
        self.assertEqual(self.ws.panel_views, {})


if __name__ == "__main__":
    unittest.main()
