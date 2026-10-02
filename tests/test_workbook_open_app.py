"""Opening a workbook refreshes the tree once for the whole set of files, not
once per file (that made the cost grow with the square of the file count: 108
separate Avantage files took 3.9 s against 0.5 s batched). Needs a display and
matplotlib; skipped otherwise.

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


def make(path):
    """A one-region file at ``path`` (f3.vms -> sample S3)."""
    name = os.path.basename(path)
    n = 41
    e = [292.0 - i * 12.0 / (n - 1) for i in range(n)]
    c = [100 + 900 * math.exp(-((x - 286.0) / 1.0) ** 2) for x in e]
    r = Region(name="C 1s", index=0, offset=0, energy=e, counts=c,
               decodable=True, sample="S" + name[1:-4], photon_energy=1486.6,
               pass_energy=20.0, dwell=0.1, step=0.2, source=name,
               count_units="counts/s")
    f = SpectrumFile()
    f.path = path
    f.format_name = "Test"
    f.regions = [r]
    f.instrument = {"Instrument": "Test Spec"}
    f._finish()
    return f


@unittest.skipUnless(HAVE_MPL, "matplotlib / Tk not available")
class TestOpeningAWorkbook(unittest.TestCase):
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
        cls.dir = tempfile.mkdtemp()
        cls._load = ee.load_file
        ee.load_file = make
        cls._boxes = (ee.messagebox.showinfo, ee.messagebox.showwarning,
                      ee.messagebox.showerror, ee.messagebox.askyesno)
        ee.messagebox.showinfo = ee.messagebox.showwarning = \
            ee.messagebox.showerror = lambda *a, **k: None
        ee.messagebox.askyesno = lambda *a, **k: True

    @classmethod
    def tearDownClass(cls):
        (ee.messagebox.showinfo, ee.messagebox.showwarning,
         ee.messagebox.showerror, ee.messagebox.askyesno) = cls._boxes
        ee.load_file = cls._load
        cls.root.destroy()
        import matplotlib
        matplotlib.rcParams.update(cls._rc)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def saved(self, n):
        """A workspace with ``n`` files loaded, all ticked and saved as a
        workbook; returns ``(workspace, workbook path)``."""
        folder = os.path.join(self.dir, f"data{n}")
        os.makedirs(folder, exist_ok=True)
        ws = ee.Workspace(self.root)
        for i in range(n):
            path = os.path.join(folder, f"f{i}.vms")
            with open(path, "wb") as fh:
                fh.write(b"stand-in for an instrument file")
            ws._add_file(path, refresh=False)
        ws._finish_adding()
        ws.checked = {id(r) for d in ws.docs for r in d.regions}
        path = os.path.join(self.dir, f"book{n}{wbk.EXT}")
        ws.wb_path = path
        self.assertTrue(ws.save_workbook())
        return ws, path

    @staticmethod
    def state(ws):
        names = sorted(r.sample for d in ws.docs for r in d.regions
                       if id(r) in ws.checked)
        return {"files": sorted(os.path.basename(d.path) for d in ws.docs),
                "ids": sorted(ws.file_ids.values()),
                "ticked": names,
                "rows": len(ws.tree.get_children())}

    def reopen(self, ws, path):
        """Open ``path`` in ``ws`` and count the refreshes of the tree."""
        calls = []
        real = ws._finish_adding

        def spy():
            calls.append(1)
            return real()
        ws._finish_adding = spy
        try:
            ws.open_workbook(path)
        finally:
            del ws.__dict__["_finish_adding"]
        return len(calls)

    def test_many_files_refresh_the_tree_once(self):
        ws, path = self.saved(6)
        before = self.state(ws)
        self.assertEqual(len(before["files"]), 6)
        refreshes = self.reopen(ws, path)
        self.assertEqual(refreshes, 1)
        # ... and the result is what was saved
        after = self.state(ws)
        self.assertEqual(after["files"], before["files"])
        self.assertEqual(after["ids"], before["ids"])
        self.assertEqual(after["ticked"], before["ticked"])
        self.assertEqual(after["rows"], before["rows"])
        self.assertEqual(sorted(ws.region_parser.values(), key=id),
                         sorted((d for d in ws.docs for _r in d.regions),
                                key=id))

    def test_one_or_two_files_are_opened_as_before(self):
        for n in (1, 2):
            ws, path = self.saved(n)
            before = self.state(ws)
            self.assertEqual(self.reopen(ws, path), n)    # a refresh per file
            self.assertEqual(self.state(ws), before)

    def test_the_tree_and_colours_are_built_after_a_batched_open(self):
        ws, path = self.saved(5)
        self.reopen(ws, path)
        self.assertEqual(len(ws.tree.get_children()), 5)
        ws._render()          # colours are handed out when a page is drawn
        self.assertTrue(ws.trace_color)
        self.assertTrue(all(id(r) in ws.trace_color
                            for d in ws.docs for r in d.regions
                            if id(r) in ws.checked))


if __name__ == "__main__":
    unittest.main()
