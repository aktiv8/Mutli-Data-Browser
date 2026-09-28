"""Persisting a CasaXPS CSV import (casacsv.py) and the Quantification tab's
RSF choice (quant_ui.py) across a workbook save/reopen -- both used to be
silently lost (see spectradeck.Workspace._remember_csv_import /
_reapply_csv_imports and capture_state/apply_state's "quant_rsf" key).

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

import casacsv  # noqa: E402
import casafit  # noqa: E402
import quant_ui  # noqa: E402
import workbook as wbk  # noqa: E402
from readers import Region, SpectrumFile  # noqa: E402

try:
    import numpy as np  # noqa: F401
    HAVE_NP = True
except Exception:
    HAVE_NP = False


def _be_axis(n=21):
    return [280.0 + 0.1 * i for i in range(n)]


def _write_csv(path, be, sample="S1", scan="C1s Scan", bg=50.0):
    """A minimal "rows"-layout CasaXPS ASCII export: one spectrum, a
    background and no fitted components -- the simplest block casacsv.py
    will still attach (see match_to_regions: n_total == 0 skips all
    component alignment, so only the BE range/point count need to agree)."""
    # a "Name" preamble row is how casacsv.detect_layout recognises the
    # "rows" layout (see casacsv._parse_rows)
    lines = ["Name,,", f"B.E.,Cycle 0:{sample}:{scan}:CPS,Background CPS"]
    for i, e in enumerate(be):
        lines.append(f"{e},{100.0 + i},{bg}")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def _make_doc(path):
    """A fresh SpectrumFile/Region/Fit each call -- standing in for a real
    reopen, which re-parses the file into brand new objects (never reuses
    the ones from before saving)."""
    be = _be_axis()
    hv = 1486.6
    r = Region(name="C 1s", index=0, offset=0, energy=be,
              counts=[100.0] * len(be), decodable=True, sample="S1",
              photon_energy=hv, dwell=0.1, count_units="counts/s",
              source="a.vms")
    r.fit = casafit.Fit(regions=[casafit.FitRegion(
        name="C 1s", start_ke=hv - max(be), end_ke=hv - min(be),
        params=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0))])
    f = SpectrumFile()
    f.path = path
    f.format_name = "Test"
    f.regions = [r]
    f.instrument = {}
    f._finish()
    return f


@unittest.skipUnless(HAVE_MPL and HAVE_NP, "numpy / matplotlib / Tk not available")
class TestCsvImportAndQuantRsfPersistence(unittest.TestCase):
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
        # save_workbook()/open_workbook() call update_idletasks(), which in a
        # window-manager-less test environment can spin forever processing
        # geometry idle tasks that never settle; it is a UI nicety (repaint
        # promptness), not part of what is being tested here
        cls.root.update_idletasks = lambda: None
        cls.dir = tempfile.mkdtemp(prefix="csvimport_")
        cls.data = os.path.join(cls.dir, "a.vms")
        with open(cls.data, "wb") as fh:
            fh.write(b"stand-in for an instrument file")
        cls.csv_path = os.path.join(cls.dir, "export.csv")
        _write_csv(cls.csv_path, _be_axis())
        cls._load = ee.load_file
        ee.load_file = lambda p: _make_doc(p)
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
        self.addCleanup(ws._drop_wb_dir)
        return ws

    def _import_csv(self, ws, path):
        """Mirror Workspace.import_casaxps_csv without the file dialog."""
        regions = [r for p in ws.docs for r in p.regions]
        csv_import = casacsv.parse(path)
        report = casacsv.match_to_regions(csv_import.blocks, regions)
        casacsv.apply_matches(report)
        ws._remember_csv_import(path)
        ws._refresh_csv_curves_availability()
        return report

    def test_csv_curves_and_rsf_choice_survive_a_reopen(self):
        ws = self._ws()
        ws._add_file(self.data)
        ws.checked = {id(r) for r in ws.docs[0].regions}
        report = self._import_csv(ws, self.csv_path)
        # the synthetic fixture must actually match, or the rest is moot
        self.assertTrue(any(r.csv_curves is not None for r in report.results),
                        casacsv.summarise(report))
        self.assertTrue(ws._any_csv_curves())
        ws.csv_curves_var.set(True)
        ws.quant_panel.rsf_var.set(quant_ui.RSF_LABELS["scofield"])
        self.assertEqual(len(ws.casa_csv_imports), 1)

        path = os.path.join(self.dir, "roundtrip" + wbk.EXT)
        ws.wb_path = path
        self.assertTrue(ws.save_workbook())

        ws2 = self._ws()
        ws2.open_workbook(path)
        # brand new Region/Fit objects (see _make_doc) -- this only passes if
        # the CSV bytes were actually stored and re-matched, not reused from
        # the first Workspace's in-memory state
        self.assertIsNot(ws2.docs[0].regions[0], ws.docs[0].regions[0])
        self.assertTrue(ws2._any_csv_curves())
        self.assertTrue(ws2.csv_curves_var.get())
        self.assertEqual(len(ws2.casa_csv_imports), 1)
        self.assertEqual(ws2.quant_panel.rsf_choice(), "scofield")

    def test_a_workbook_without_either_stays_off(self):
        ws = self._ws()
        ws._add_file(self.data)
        path = os.path.join(self.dir, "plain" + wbk.EXT)
        ws.wb_path = path
        self.assertTrue(ws.save_workbook())

        ws2 = self._ws()
        ws2.open_workbook(path)
        self.assertFalse(ws2._any_csv_curves())
        self.assertFalse(ws2.csv_curves_var.get())
        self.assertEqual(ws2.casa_csv_imports, [])
        self.assertEqual(ws2.quant_panel.rsf_choice(), "off")


if __name__ == "__main__":
    unittest.main()
