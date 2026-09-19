"""Element identification: the line table, candidate lookup and auto-labelling.

Run:  python -m unittest discover tests
"""

import json
import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import xpslines as xl  # noqa: E402

LINES = xl.load_lines()


def label(be, window=2.0, hv=None):
    c = xl.candidates(be, window, LINES, hv)
    return xl.label_of(c[0][1]) if c else None


class TestTable(unittest.TestCase):
    def test_bundled_table_is_sane(self):
        self.assertGreater(len(LINES), 80)
        els = {e["el"] for e in LINES}
        for el in ("C", "O", "N", "Si", "Al", "Mo", "S", "Au", "Ag", "Cu"):
            self.assertIn(el, els)
        for e in LINES:
            if "be" in e:
                self.assertTrue(0 < e["be"] < 1500, e)
            else:
                self.assertTrue(0 < e["ke"] < 1500, e)

    def test_missing_or_broken_file_gives_an_empty_table(self):
        self.assertEqual(xl.load_lines("/no/such/file.json"), [])
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.json")
            with open(p, "w") as fh:
                fh.write("{not json")
            self.assertEqual(xl.load_lines(p), [])
            with open(p, "w") as fh:
                json.dump({"lines": [{"el": "X", "line": "1s", "be": 5},
                                     {"el": "Y"}, "junk"]}, fh)
            self.assertEqual(len(xl.load_lines(p)), 1)


class TestCandidates(unittest.TestCase):
    def test_common_peaks(self):
        self.assertEqual(label(285.2), "C 1s")
        self.assertEqual(label(532.4), "O 1s")
        self.assertEqual(label(399.6), "N 1s")
        self.assertEqual(label(228.9), "Mo 3d5/2")
        self.assertEqual(label(163.5), "S 2p")
        self.assertEqual(label(83.9), "Au 4f7/2")

    def test_nothing_in_the_window(self):
        self.assertIsNone(label(1400.0))
        self.assertEqual(xl.candidates(287.5, 0.1, LINES), [])

    def test_sorted_nearest_first_with_secondary_lines_penalised(self):
        c = xl.candidates(119.0, 3.0, LINES)          # Al 2s 118 / Tl 4f 118
        self.assertTrue(c)
        self.assertLessEqual(abs(c[0][0]), abs(c[-1][0]) + 1.6)

    def test_auger_lines_follow_the_photon_energy(self):
        self.assertEqual(label(976.6, hv=1486.6), "O KLL")
        self.assertNotEqual(label(976.6, hv=1253.6), "O KLL")
        self.assertEqual(label(743.6, hv=1253.6), "O KLL")


def survey(peaks, lo=0.0, hi=1100.0, step=0.5, width=1.2, noise=0.0):
    n = int((hi - lo) / step) + 1
    e = [hi - i * step for i in range(n)]
    y = [200.0 for _ in e]
    for be, amp in peaks:
        y = [v + amp * math.exp(-((x - be) / width) ** 2)
             for v, x in zip(y, e)]
    return e, y


class TestPeaks(unittest.TestCase):
    def test_finds_the_peaks_strongest_first(self):
        e, y = survey([(285.0, 3000), (532.0, 9000), (99.0, 1500)])
        peaks = xl.find_peaks(e, y)
        self.assertEqual([round(p[0]) for p in peaks][:3], [532, 285, 99])

    def test_close_peaks_are_merged_and_noise_is_ignored(self):
        e, y = survey([(285.0, 3000), (286.5, 2900)])
        near = [p for p in xl.find_peaks(e, y, min_sep=3.0)
                if 280 < p[0] < 292]
        self.assertEqual(len(near), 1)
        import random
        rnd = random.Random(2)
        e, y = survey([(532.0, 9000)])
        y = [v + rnd.gauss(0, 20) for v in y]
        self.assertEqual(len(xl.find_peaks(e, y)), 1)

    def test_flat_or_tiny_input(self):
        self.assertEqual(xl.find_peaks([1, 2], [1, 1]), [])
        self.assertEqual(xl.find_peaks(list(range(50)), [5.0] * 50), [])

    def test_auto_label(self):
        e, y = survey([(285.3, 3000), (532.6, 9000), (74.0, 800),
                       (228.5, 2500)])
        got = dict((lbl, be) for be, lbl in xl.auto_label(e, y, LINES))
        for lbl, be in (("O 1s", 532.6), ("C 1s", 285.3), ("Al 2p", 74.0),
                        ("Mo 3d5/2", 228.5)):
            self.assertIn(lbl, got)
            self.assertAlmostEqual(got[lbl], be, delta=0.5)


if __name__ == "__main__":
    unittest.main()
