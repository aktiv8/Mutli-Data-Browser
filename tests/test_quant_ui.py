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
