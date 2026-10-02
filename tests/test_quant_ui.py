"""The desktop "Quantification" tab (quant_ui.QuantPanel), wired into the
app: tab visibility on ticking, the composition/profile table shapes, the
panel's own RSF-library choice, and that a CasaXPS-export-only sample stays
out (it already has a home in the "CasaXPS quant" tab).

Run:  python -m unittest discover tests
"""

import copy
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

try:
    import tkinter as tk
    import spectradeck as ee
    HAVE_MPL = ee.HAVE_MPL
except Exception:                                   # pragma: no cover
    tk, ee, HAVE_MPL = None, None, False

import casaquant
import quant_ui
import resultspages
from readers import SpectrumFile
from test_casafit import HAVE_NP, fitted_region


@unittest.skipUnless(HAVE_MPL and HAVE_NP,
                     "numpy / matplotlib / Tk not available")
class TestQuantPanelInApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # a Workspace applies its theme to matplotlib's global settings;
        # give them back so other tests see the defaults
        import matplotlib
        cls._rc = matplotlib.rcParams.copy()
        try:
            cls.root = tk.Tk()
        except tk.TclError:
            raise unittest.SkipTest("no display")
        cls.root.withdraw()
        cls.dir = tempfile.mkdtemp(prefix="quant_ui_")
        cls.data = os.path.join(cls.dir, "a.vms")
        with open(cls.data, "wb") as fh:
            fh.write(b"stand-in for an instrument file")
        f = SpectrumFile()
        f.path = cls.data
        f.format_name = "Test"
        f.regions = [fitted_region()]
        f.instrument = {}
        f._finish()
        cls.doc = f
        cls._load = ee.load_file
        ee.load_file = lambda p: cls.doc
        cls._boxes = (ee.messagebox.showinfo, ee.messagebox.showwarning,
                     ee.messagebox.showerror)
        ee.messagebox.showinfo = ee.messagebox.showwarning = \
            ee.messagebox.showerror = lambda *a, **k: None

    @classmethod
    def tearDownClass(cls):
        (ee.messagebox.showinfo, ee.messagebox.showwarning,
         ee.messagebox.showerror) = cls._boxes
        ee.load_file = cls._load
        cls.root.destroy()
        import matplotlib
        matplotlib.rcParams.update(cls._rc)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _ws(self):
        ws = ee.Workspace(self.root)
        ws._add_file(self.data)
        return ws

    def test_tab_hidden_with_nothing_ticked(self):
        ws = self._ws()
        self.assertEqual(ws.checked, set())
        self.assertEqual(ws.nb.tab(ws.tab_quant, "state"), "hidden")
        self.assertFalse(ws.quant_panel.sample_box["values"])

    def test_tab_appears_and_fills_once_the_fit_is_ticked(self):
        ws = self._ws()
        region = ws.docs[0].regions[0]
        ws.checked.add(id(region))
        ws._render()
        self.assertEqual(ws.nb.tab(ws.tab_quant, "state"), "normal")
        panel = ws.quant_panel
        self.assertEqual(panel.sample_box["values"], ("S",))
        self.assertEqual(panel.sample_var.get(), "S")
        rows = [panel.tree.item(i, "values")
               for i in panel.tree.get_children()]
        self.assertTrue(rows)
        self.assertEqual(rows[0][0], "Ti 2p")             # region name
        self.assertEqual(len(panel.tree["columns"]),
                         len(resultspages.COMPOSITION_HEADER))

    def test_rsf_choice_reaches_resultspages_collect(self):
        ws = self._ws()
        region = ws.docs[0].regions[0]
        ws.checked.add(id(region))
        ws._render()
        panel = ws.quant_panel
        seen = {}
        real = resultspages.collect

        def spy(*a, **kw):
            seen["rsf_library"] = kw.get("rsf_library")
            seen["rsf_table"] = kw.get("rsf_table")
            return real(*a, **kw)
        resultspages.collect = spy
        try:
            panel.rsf_var.set(quant_ui.RSF_LABELS["scofield"])
            panel.refresh()
        finally:
            resultspages.collect = real
        self.assertEqual(seen["rsf_library"], "scofield")
        self.assertIsNotNone(seen["rsf_table"])

    def test_a_profile_sample_shows_the_depth_columns(self):
        ws = self._ws()
        r0 = ws.docs[0].regions[0]
        r0.etch_level = 0
        r1 = copy.deepcopy(fitted_region())
        r1.etch_level = 1
        ws.docs[0].regions.append(r1)
        ws.checked |= {id(r0), id(r1)}
        ws._render()
        panel = ws.quant_panel
        self.assertEqual(panel.sample_box["values"], ("S",))
        self.assertTrue(panel.sample.is_profile)
        header = [panel.tree.heading(c, "text")
                 for c in panel.tree["columns"]]
        self.assertEqual(header[0], "Level")
        ws.docs[0].regions.pop()          # leave the fixture as found

    def _ticked_panel(self, levels=1):
        ws = self._ws()
        r0 = ws.docs[0].regions[0]
        regs = [r0]
        if levels > 1:
            r0.etch_level = 0
            for n in range(1, levels):
                r = copy.deepcopy(fitted_region())
                r.etch_level = n
                ws.docs[0].regions.append(r)
                regs.append(r)
        ws.checked |= {id(r) for r in regs}
        ws._render()
        self.addCleanup(self._restore, levels)
        return ws, ws.quant_panel

    def _restore(self, levels):
        del self.doc.regions[1:]
        self.doc.regions[0].etch_level = None

    def _rows(self, panel):
        return [(i, panel.tree.item(i, "text"), panel.tree.item(i, "values"))
                for i in panel.tree.get_children()]

    def test_a_region_row_has_a_tick_that_leaves_it_out_of_the_total(self):
        ws, panel = self._ticked_panel()
        iid, tick, values = next(r for r in self._rows(panel)
                                 if r[0] in panel._row_entry)
        self.assertEqual(tick, quant_ui.TICK_ON)
        self.assertNotEqual(values[5], "not included")
        panel.toggle_row(iid)
        row = next(r for r in self._rows(panel) if r[0] in panel._row_entry)
        self.assertEqual(row[1], quant_ui.TICK_OFF)
        self.assertEqual(row[2][5], "not included")
        self.assertIn("changed", panel.tree.item(row[0], "tags"))
        panel.reset_ticks()
        row = next(r for r in self._rows(panel) if r[0] in panel._row_entry)
        self.assertEqual(row[1], quant_ui.TICK_ON)

    def test_clicking_the_tick_column_toggles_but_other_columns_do_not(self):
        # a withdrawn root never lays rows out, so the hit test is stubbed
        ws, panel = self._ticked_panel()
        hit = {"column": "#0"}
        panel.tree.identify_region = lambda x, y: "tree"
        panel.tree.identify_column = lambda x: hit["column"]
        panel.tree.identify_row = lambda y: next(iter(panel._row_entry))
        ev = type("E", (), {"x": 4, "y": 4})()
        text = lambda: panel.tree.item(next(iter(panel._row_entry)), "text")
        self.assertEqual(panel._on_click(ev), "break")      # rows are rebuilt
        self.assertEqual(text(), quant_ui.TICK_OFF)
        hit["column"] = "#1"                            # a value column
        self.assertIsNone(panel._on_click(ev))
        self.assertEqual(text(), quant_ui.TICK_OFF)
        panel.tree.identify_region = lambda x, y: "heading"
        hit["column"] = "#0"
        self.assertIsNone(panel._on_click(ev))
        self.assertEqual(text(), quant_ui.TICK_OFF)

    def test_ticks_survive_a_refresh_and_go_when_the_regions_change(self):
        ws, panel = self._ticked_panel()
        panel.toggle_row(next(iter(panel._row_entry)))
        panel.refresh()
        row = next(r for r in self._rows(panel) if r[0] in panel._row_entry)
        self.assertEqual(row[1], quant_ui.TICK_OFF)
        ws.checked.clear()
        panel.refresh()
        self.assertEqual(panel.samples, [])
        self.assertEqual(self._rows(panel), [])

    def test_transmission_is_offered_only_when_a_row_has_it(self):
        ws, panel = self._ticked_panel()
        self.assertEqual(str(panel.trans_check.cget("state")), "disabled")
        panel.set_transmission(True)
        panel.refresh()                          # nothing to divide out
        self.assertFalse(panel.view.transmission)
        self.assertFalse(panel.trans_var.get())

    def test_transmission_choice_is_part_of_the_saved_state(self):
        ws, panel = self._ticked_panel()
        self.assertFalse(ws.capture_state()["quant_transmission"])
        panel.view.transmission = True
        self.assertTrue(ws.capture_state()["quant_transmission"])
        ws.apply_state({"quant_transmission": False})
        self.assertFalse(panel.view.transmission)
        self.assertFalse(panel.trans_var.get())

    def test_a_profile_sample_can_show_one_level_with_ticks(self):
        ws, panel = self._ticked_panel(levels=2)
        values = list(panel.view_box["values"])
        self.assertEqual(values[0], quant_ui.PROFILE_LABEL)
        self.assertEqual(len(values), 3)
        self.assertEqual(panel.view_var.get(), quant_ui.PROFILE_LABEL)
        self.assertEqual(str(panel.mode_box.cget("state")), "readonly")
        self.assertFalse(panel._row_entry)         # no ticks on the profile
        panel.view_var.set(values[2])
        panel._view_chosen()
        self.assertEqual(panel.tree["columns"].__len__(),
                         len(resultspages.COMPOSITION_HEADER))
        self.assertTrue(panel._row_entry)
        self.assertEqual(str(panel.mode_box.cget("state")), "disabled")
        # a tick on level 2 leaves level 1 alone
        panel.toggle_row(next(iter(panel._row_entry)))
        panel.view_var.set(values[1])
        panel._view_chosen()
        row = next(r for r in self._rows(panel) if r[0] in panel._row_entry)
        self.assertEqual(row[1], quant_ui.TICK_ON)

    def test_the_profile_mode_changes_the_columns(self):
        ws, panel = self._ticked_panel(levels=2)
        before = [panel.tree.heading(c, "text") for c in panel.tree["columns"]]
        panel.mode_var.set(dict(quant_ui.quantview.PROFILE_MODES)["state"])
        panel._mode_chosen()
        after = [panel.tree.heading(c, "text") for c in panel.tree["columns"]]
        self.assertEqual(before[0], "Level")
        self.assertNotEqual(before, after)

    def test_export_writes_the_table_with_the_ticks_applied(self):
        import csv
        ws, panel = self._ticked_panel()
        panel.toggle_row(next(iter(panel._row_entry)))
        path = os.path.join(self.dir, "q.csv")
        self.assertEqual(panel.export_csv(path), path)
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(3), b"\xef\xbb\xbf")        # UTF-8 BOM
        with open(path, encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0][:4], ["Sample", "Level", "Spectrum",
                                       "Region"])
        self.assertEqual(rows[1][3], "Ti 2p")
        self.assertEqual(rows[1][8], "")                 # unticked: no at %
        self.assertEqual(rows[1][11], "not included")
        self.assertIsNone(quant_ui.QuantPanel.export_csv(
            type("P", (), {"samples": []})()))

    def test_a_casaxps_only_sample_is_left_to_the_other_tab(self):
        ws = self._ws()
        region = ws.docs[0].regions[0]
        ws.checked.add(id(region))
        ws.casa_quant = casaquant.CasaQuant(folder=self.dir)
        ws.casa_quant.samples["OtherSample"] = casaquant.SampleQuant(
            survey=[{"element": "O 1s", "pct": 10.0}])
        ws._render()
        labels = ws.quant_panel.sample_box["values"]
        self.assertIn("S", labels)
        self.assertNotIn("OtherSample", labels)
        ws.casa_quant = None


if __name__ == "__main__":
    unittest.main()
