"""Ticking every region that shares a name, across every loaded sample
(needs a display and matplotlib/Tk; skipped otherwise).

Run:  python -m unittest discover tests
"""

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


def reg(name, sample, peak, n=21):
    e = [292.0 - i * 12.0 / (n - 1) for i in range(n)]
    c = [100 + 900 * 2.718281828 ** (-((x - peak) / 1.0) ** 2) for x in e]
    return Region(name=name, index=0, offset=0, energy=e, counts=c,
                  decodable=True, sample=sample, photon_energy=1486.6,
                  pass_energy=20.0, dwell=0.1, step=0.2,
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
class TestTickMatchingInApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError:
            raise unittest.SkipTest("no display")
        cls.root.withdraw()
        cls.docs = {
            "a.vms": doc("a.vms", [reg("C 1s", "Sample A", 284.8),
                                   reg("O 1s", "Sample A", 532.0)]),
            "b.vms": doc("b.vms", [reg("C 1s", "Sample B", 285.1)]),
        }
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
        for p in self.docs:
            ws._add_file(p, file_id=p[:-4], refresh=False)
        ws._finish_adding()
        ws.checked = set()

    def _row_for(self, region):
        for iid, r in self.ws.leaf_region.items():
            if r is region:
                return iid
        raise AssertionError("no tree row found for region")

    def test_ticks_every_matching_region_everywhere(self):
        ws = self.ws
        c1s_a = self.docs["a.vms"].regions[0]
        c1s_b = self.docs["b.vms"].regions[0]
        o1s_a = self.docs["a.vms"].regions[1]

        row = self._row_for(c1s_a)
        ws._tick_matching(row)

        self.assertIn(id(c1s_a), ws.checked)
        self.assertIn(id(c1s_b), ws.checked)
        self.assertNotIn(id(o1s_a), ws.checked)

    def test_noop_on_empty_row(self):
        ws = self.ws
        ws._tick_matching("")
        self.assertEqual(ws.checked, set())


if __name__ == "__main__":
    unittest.main()
