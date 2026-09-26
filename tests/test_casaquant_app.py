"""CasaXPS exported-quantification sidecar files, wired into the app: the
directory-load hook (Workspace._scan_casa_quant / _add_file /
_open_folder_path) and workbook persistence (needs a display and
matplotlib; skipped otherwise).

Run:  python -m unittest discover tests
"""

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import tkinter as tk
    import spectradeck as ee
    HAVE_MPL = ee.HAVE_MPL
except Exception:                                   # pragma: no cover
    tk, ee, HAVE_MPL = None, None, False

import casaquant
import workbook as wbk  # noqa: E402
from readers import Region, SpectrumFile  # noqa: E402

SURVEY = (
    "a.vms\t\n\n"
    "Sample Identifier\tName\tPosition\tFWHM\tRaw Area\t%At Conc\t\n"
    "PtCl2\tO 1s\t532.70\t2.10\t32369.00\t1.82\t\n"
    "\tC 1s\t284.91\t2.72\t183090.45\t27.46\t\n"
    "\n\nPeak Area Results Compact form (Atomic Concentrations)\n"
    "Name\t%Conc\tSample Identifier\n\tSt.Dev.\n"
    "O 1s\t1.82\tPtCl2\n\t \n\n\n"
    "Peak Area Results\n\n"
    "PtCl2\tO 1s\tC 1s\t\n"
    "%Conc\t1.82\t27.46\t\n"
    "St.Dev.\t \t \t\n"
)
REGIONS = (
    "a.vms\t\n\n"
    "Sample Identifier\tName\tPosition\tRaw Area\tArea/(RSF*T*MFP)\t%At Conc\t\n"
    "PtCl2\tC 1s\t284.69\t18766.53\t19751.56\t16.84\t\n"
    "\tO 1s\t532.70\t100.0\t50.0\t1.82\t\n"
    "\n\nPeak Area Results Compact form (Atomic Concentrations)\n"
)


def reg(name, sample):
    return Region(name=name, index=0, offset=0, energy=[1.0, 2.0],
                  counts=[1.0, 2.0], decodable=True, sample=sample)


@unittest.skipUnless(HAVE_MPL, "matplotlib / Tk not available")
class TestCasaQuantInApp(unittest.TestCase):
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
        cls.dir = tempfile.mkdtemp(prefix="casaquant_app_")
        cls.data = os.path.join(cls.dir, "a.vms")
        with open(cls.data, "wb") as fh:
            fh.write(b"stand-in for an instrument file")
        with open(os.path.join(cls.dir, "quant_survey.txt"), "w",
                 encoding="latin-1") as fh:
            fh.write(SURVEY)
        with open(os.path.join(cls.dir, "quant_regions.txt"), "w",
                 encoding="latin-1") as fh:
            fh.write(REGIONS)
        f = SpectrumFile()
        f.path = cls.data
        f.format_name = "Test"
        f.regions = [reg("C 1s", "PtCl2")]
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

    def test_scan_on_single_file_open(self):
        """Opening a lone .vms file (not "Open folder") still notices the
        sidecar files in the same directory."""
        ws = ee.Workspace(self.root)
        ws._add_file(self.data)
        self.assertIsNotNone(ws.casa_quant)
        self.assertEqual(set(ws.casa_quant.samples), {"PtCl2"})
        s = ws.casa_quant.samples["PtCl2"]
        self.assertEqual(s.survey, [{"element": "O 1s", "pct": 1.82},
                                    {"element": "C 1s", "pct": 27.46}])
        self.assertEqual(len(s.regions), 2)

    def test_folder_is_scanned_once(self):
        ws = ee.Workspace(self.root)
        ws._add_file(self.data)
        self.assertIn(os.path.normcase(os.path.abspath(self.dir)),
                     ws._casa_quant_scanned)
        calls = []
        real = casaquant.load
        casaquant.load = lambda folder: (calls.append(folder) or real(folder))
        try:
            ws._scan_casa_quant(self.dir)
        finally:
            casaquant.load = real
        self.assertEqual(calls, [])          # already scanned: not reloaded

    def test_workbook_round_trip(self):
        """Save from a workspace that scanned the sidecar files, reopen in a
        fresh one: the parsed quantification (and its raw text) survives."""
        ws = ee.Workspace(self.root)
        ws._add_file(self.data)
        self.assertIsNotNone(ws.casa_quant)
        path = os.path.join(self.dir, "exp" + wbk.EXT)
        ws.wb_path = path
        self.assertTrue(ws.save_workbook())

        ws2 = ee.Workspace(self.root)
        ws2.open_workbook(path)
        self.assertIsNotNone(ws2.casa_quant)
        self.assertEqual(set(ws2.casa_quant.samples), {"PtCl2"})
        self.assertEqual(ws2.casa_quant.samples["PtCl2"].survey,
                         ws.casa_quant.samples["PtCl2"].survey)
        self.assertIn("survey", ws2.casa_quant.raw)
        self.assertIn("regions", ws2.casa_quant.raw)

    def test_panel_reflects_the_loaded_folder(self):
        """The desktop panel (casaquant_ui.CasaQuantPanel), wired into the
        info notebook, shows the same numbers ``casa_quant`` holds."""
        ws = ee.Workspace(self.root)
        ws._add_file(self.data)
        panel = ws.casaquant_panel
        self.assertEqual(ws.nb.tab(ws.tab_casaquant, "state"), "normal")
        self.assertEqual(panel.sample_box["values"], ("PtCl2",))
        self.assertEqual(panel.sample_var.get(), "PtCl2")
        survey_rows = [panel.survey_tab.tree.item(i, "values")
                      for i in panel.survey_tab.tree.get_children()]
        self.assertEqual(survey_rows, [("O 1s", "1.82"), ("C 1s", "27.46")])
        regions_rows = [panel.regions_tab.tree.item(i, "values")
                       for i in panel.regions_tab.tree.get_children()]
        self.assertEqual(regions_rows,
                         [("C 1s", "284.69", "16.84"),
                          ("O 1s", "532.7", "1.82")])
        # no Quant_Dparam.txt in this fixture: the tab stays hidden
        self.assertEqual(panel.nb.tab(panel.dparam_tab, "state"), "hidden")

    def test_tab_hidden_without_any_quant_files(self):
        with tempfile.TemporaryDirectory(prefix="casaquant_none_") as empty_dir:
            data = os.path.join(empty_dir, "b.vms")
            with open(data, "wb") as fh:
                fh.write(b"stand-in")
            doc = SpectrumFile()
            doc.path, doc.format_name = data, "Test"
            doc.regions, doc.instrument = [reg("O 1s", "S1")], {}
            doc._finish()
            ee.load_file = lambda p: doc
            ws = ee.Workspace(self.root)
            ws._add_file(data)
            self.assertIsNone(ws.casa_quant)
            self.assertEqual(ws.nb.tab(ws.tab_casaquant, "state"), "hidden")
            self.assertFalse(ws.casaquant_panel.sample_box["values"])
        ee.load_file = lambda p: self.doc


if __name__ == "__main__":
    unittest.main()
