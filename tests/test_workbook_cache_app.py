"""Saving a workbook from the real window stores the parsed results beside the
data, unless switched off (needs a display and matplotlib; skipped otherwise).

Run:  python -m unittest discover tests
"""

import math
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

import workbook as wbk  # noqa: E402
from readers import Region, SpectrumFile  # noqa: E402


def reg(name, sample, peak, n=61):
    e = [292.0 - i * 12.0 / (n - 1) for i in range(n)]
    c = [100 + 900 * math.exp(-((x - peak) / 1.0) ** 2) for x in e]
    return Region(name=name, index=0, offset=0, energy=e, counts=c,
                  decodable=True, sample=sample, photon_energy=1486.6,
                  pass_energy=20.0, dwell=0.1, step=0.2, source="a.vms",
                  count_units="counts/s")


@unittest.skipUnless(HAVE_MPL, "matplotlib / Tk not available")
class TestWorkbookCacheInApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError:
            raise unittest.SkipTest("no display")
        cls.root.withdraw()
        cls.dir = tempfile.mkdtemp()
        cls.data = os.path.join(cls.dir, "a.vms")
        with open(cls.data, "wb") as fh:
            fh.write(b"stand-in for an instrument file")
        f = SpectrumFile()
        f.path = cls.data
        f.format_name = "Test"
        f.regions = [reg("C 1s", "S1", 286.0), reg("O 1s", "S1", 288.0)]
        f.instrument = {"Instrument": "Test Spec"}
        f._finish()
        cls.doc = f
        cls._load = ee.load_file
        ee.load_file = lambda p: cls.doc
        cls.ws = ee.Workspace(cls.root)
        cls.ws._add_file(cls.data)
        cls.ws.checked = {id(r) for r in cls.doc.regions}

    @classmethod
    def tearDownClass(cls):
        ee.load_file = cls._load
        cls.root.destroy()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def save(self, name):
        path = os.path.join(self.dir, name + wbk.EXT)
        self.ws.wb_path = path
        self.assertTrue(self.ws.save_workbook())
        return path

    def test_results_are_stored_with_the_file_ids(self):
        self.ws.cache_var.set(True)
        path = self.save("on")
        payload, why = wbk.read_cache(path)
        self.assertEqual(why, "")
        names = [r["name"] for s in payload["samples"] for r in s["regions"]]
        self.assertEqual(names, ["C 1s", "O 1s"])
        fid = self.ws.file_ids[id(self.doc)]
        self.assertEqual(payload["files"][0]["id"], fid)
        self.assertEqual([f["id"] for f in payload["source_files"]], [fid])
        self.assertNotIn("cameras_data", payload)

    def test_switched_off_stores_nothing(self):
        self.ws.cache_var.set(False)
        try:
            path = self.save("off")
        finally:
            self.ws.cache_var.set(True)
        self.assertIn("no stored results", wbk.read_cache(path)[1])
        self.assertEqual(len(wbk.load(path, os.path.join(self.dir, "x")).files),
                         1)

    def test_renames_are_in_the_results_as_shown(self):
        # the results are the spectra as the app shows and exports them, so a
        # rename made in the app is in them (and in annotations.json as well)
        import annotations
        self.ws.cache_var.set(True)
        fid = self.ws.file_ids[id(self.doc)]
        key = annotations.region_key(fid, "S1", "C 1s")
        self.ws.ann.set_name("region_names", key, "Carbon", "C 1s")
        self.ws._ann_changed()
        try:
            path = self.save("names")
        finally:
            self.ws.ann.set_name("region_names", key, "", "C 1s")
            self.ws._ann_changed()
        names = [r["name"] for s in wbk.load_cache(path)["samples"]
                 for r in s["regions"]]
        self.assertEqual(names, ["Carbon", "O 1s"])

    def test_page_from_that_workbook(self):
        import htmlbrowser
        self.ws.cache_var.set(True)
        path = self.save("page")
        out = os.path.join(self.dir, "page.html")
        self.assertGreater(htmlbrowser.write_html_from_workbook(path, out), 0)
        with open(out, encoding="utf-8") as fh:
            self.assertIn("xps-data", fh.read())


if __name__ == "__main__":
    unittest.main()
