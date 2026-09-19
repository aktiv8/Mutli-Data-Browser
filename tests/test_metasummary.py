"""Tidied metadata: common values stated once, differing settings grouped by
the regions that share them.

Run:  python -m unittest discover tests
"""

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import exporters  # noqa: E402
import metasummary as ms  # noqa: E402
from readers import Region  # noqa: E402
from readers.base import SpectrumFile  # noqa: E402


def region(name, pe, step=0.1, hv=1486.6, lens="Hybrid", sample="S1",
           n=21, date="2020-01-01 10:00:00"):
    return Region(name=name, index=0, offset=0,
                  energy=[300.0 - i * step for i in range(n)],
                  counts=[1.0] * n, decodable=True, sample=sample,
                  photon_energy=hv, pass_energy=pe, step=step, dwell=0.1,
                  lens_mode=lens, date=date, source="a.vgd")


class Doc(SpectrumFile):
    def __init__(self, regions, path="a.vgd"):
        super().__init__()
        self.path = path
        self.regions = regions
        self._finish()


def rows_of(doc, regs=None):
    return [(r.name, doc.region_metadata(r)) for r in (regs or doc.regions)]


class TestSummarise(unittest.TestCase):
    def setUp(self):
        self.doc = Doc([region("Survey", 160, step=1.0),
                        region("Mo 3d", 40), region("S 2p", 40),
                        region("C 1s", 40)])

    def test_common_and_varying_split(self):
        common, varying = ms.summarise(rows_of(self.doc), ms.SETTING_FIELDS)
        common = dict(common)
        self.assertEqual(common["Lens mode"], "Hybrid")
        self.assertNotIn("Pass energy (eV)", common)
        v = dict(varying)
        # numbers ascending: 40 before 160
        self.assertEqual(v["Pass energy (eV)"],
                         [("40", ["Mo 3d", "S 2p", "C 1s"]),
                          ("160", ["Survey"])])

    def test_all_same_pass_energy_is_common(self):
        doc = Doc([region("Mo 3d", 40), region("S 2p", 40)])
        common, varying = ms.summarise(rows_of(doc), ["Pass energy (eV)"])
        self.assertEqual(common, [("Pass energy (eV)", "40")])
        self.assertEqual(varying, [])

    def test_missing_values_are_grouped_last(self):
        doc = Doc([region("A", 40), region("B", None), region("C", 160)])
        _c, varying = ms.summarise(rows_of(doc), ["Pass energy (eV)"])
        self.assertEqual([v for v, _l in varying[0][1]],
                         ["40", "160", ms.NOT_RECORDED])

    def test_empty_everywhere_is_dropped(self):
        doc = Doc([region("A", 40), region("B", 40)])
        common, varying = ms.summarise(rows_of(doc), ["Operator"])
        self.assertEqual((common, varying), ([], []))

    def test_compact_labels(self):
        self.assertEqual(ms.compact_labels(["C 1s"] * 3 + ["O 1s"]),
                         "C 1s ×3, O 1s")
        self.assertEqual(ms.compact_labels([f"R{i}" for i in range(9)], 3),
                         "R0, R1, R2, +6 more")

    def test_date_range(self):
        rows = [("a", {"Date acquired": "2020-01-01 10:00:00"}),
                ("b", {"Date acquired": "2020-01-01 11:00:00"})]
        self.assertEqual(ms.date_range(rows, " to "),
                         "2020-01-01 10:00:00 to 2020-01-01 11:00:00")
        self.assertEqual(ms.date_range(rows[:1]), "2020-01-01 10:00:00")
        self.assertEqual(ms.date_range([("a", {})]), "")


def depth(name, level, time, date="", sample="D", pe=40):
    r = region(name, pe, sample=sample, date=date)
    r.etch_level, r.etch_time = level, time
    return r


def layout_of(regs):
    return ms.layout_file(Doc(regs).samples_metadata())


class TestLayout(unittest.TestCase):
    def test_common_sample_and_row_levels(self):
        regs = [region("Survey", 160, step=1.0, sample="A"),
                region("Mo 3d", 40, sample="A"),
                region("Mo 3d", 40, sample="B")]
        for r, x in zip(regs, (1.0, 1.0, 2.0)):
            r.pos_x, r.pos_y = x, 5.0
        lay = layout_of(regs)
        common = dict(lay.common)
        self.assertEqual(common["Photon energy (eV)"], "1486.60")
        self.assertEqual(common["Lens mode"], "Hybrid")
        self.assertNotIn("Pass energy (eV)", common)     # 160 vs 40
        a, b = lay.samples
        self.assertEqual(dict(a.line)["Position X (mm)"], "1.000")
        self.assertEqual(dict(b.line)["Position X (mm)"], "2.000")
        self.assertIn("PE (eV)", a.columns)              # varies within A
        self.assertNotIn("PE (eV)", b.columns)           # constant in B
        self.assertEqual(dict(b.line)["Pass energy (eV)"], "40")
        for sl in (a, b):
            self.assertIn("BE start", sl.columns)        # ranges never go

    def test_varying_position_becomes_a_column(self):
        regs = [region("A", 40), region("B", 40)]
        regs[0].pos_x, regs[1].pos_x = 1.0, 2.0
        regs[0].pos_y = regs[1].pos_y = 0.0
        sl = layout_of(regs).samples[0]
        self.assertIn("X (mm)", sl.columns)
        self.assertEqual([r["X (mm)"] for r in sl.rows], ["1.000", "2.000"])

    def test_regular_depth_profile_collapses_to_one_row_per_region(self):
        same = "2020-01-01 10:00:00"
        regs = []
        for k in range(5):                      # levels interleave C / O
            regs += [depth("C 1s", k, k * 30.0, same),
                     depth("O 1s", k, k * 30.0, same)]
        sl = layout_of(regs).samples[0]
        self.assertEqual([r["Region"] for r in sl.rows], ["C 1s", "O 1s"])
        self.assertEqual(sl.rows[0]["Levels"], "0–4 (5)")
        self.assertEqual(sl.rows[0]["Etch"], "0–120 s, 30 s steps")
        self.assertEqual(sl.strips, [])         # nothing left to spell out

    def test_gapped_levels_are_still_exact(self):
        regs = [depth("C 1s", k, k * 30.0, "2020-01-01 10:00:00")
                for k in (0, 1, 2, 5, 6)]
        row = layout_of(regs).samples[0].rows[0]
        self.assertEqual(row["Levels"], "0–2, 5–6 (5)")
        self.assertEqual(row["Etch"], "0–180 s, 30 s steps")

    def test_no_etch_column_when_no_etch_times_were_recorded(self):
        regs = []
        for k in range(3):
            r = depth("C 1s", k, None, "2020-01-01 10:00:00")
            regs.append(r)
        sl = layout_of(regs).samples[0]
        self.assertIn("Levels", sl.columns)
        self.assertNotIn("Etch", sl.columns)
        self.assertEqual(sl.rows[0]["Levels"], "0–2 (3)")

    def test_irregular_etch_times_are_listed_in_full(self):
        times = [0, 15, 45, 60, 150]
        regs = [depth("C 1s", k, t, "2020-01-01 10:00:00")
                for k, t in enumerate(times)]
        sl = layout_of(regs).samples[0]
        self.assertEqual(sl.rows[0]["Etch"], "per level, see below")
        (title, entries), = sl.strips
        self.assertEqual([(l, e) for l, e, _d in entries],
                         [(str(k), f"{t:g}") for k, t in enumerate(times)])

    def test_per_level_dates_are_kept(self):
        regs = [depth("C 1s", k, k * 30.0, f"2020-01-01 10:0{k}:00")
                for k in range(4)]
        sl = layout_of(regs).samples[0]
        (title, entries), = sl.strips
        self.assertEqual([d for _l, _e, d in entries],
                         ["10:00:00", "10:01:00", "10:02:00", "10:03:00"])
        self.assertIn("10:00:00", sl.rows[0]["Acquired"])
        self.assertIn("10:03:00", sl.rows[0]["Acquired"])
        self.assertEqual(dict(layout_of(regs).common)["Date acquired"],
                         "2020-01-01")

    def test_nothing_is_lost_for_a_depth_profile(self):
        """Every level, etch time and date can be recovered from the layout."""
        regs = []
        for k in range(12):
            t = k * 20.0 if k < 8 else 160 + (k - 8) * 45.0     # irregular
            regs.append(depth("C 1s", k, t, f"2020-01-01 10:{k:02d}:07"))
            regs.append(depth("O 1s", k, k * 20.0,
                              f"2020-01-01 11:{k:02d}:07"))
        lay = layout_of(regs)
        sl = lay.samples[0]
        for name in ("C 1s", "O 1s"):
            row = next(r for r in sl.rows if r["Region"] == name)
            levels = set()
            for part in row["Levels"].split(" (")[0].split(", "):
                a, _, b = part.partition("–")
                levels |= set(range(int(a), int(b or a) + 1))
            self.assertEqual(levels, set(range(12)), name)
            strip = dict((l, (e, d)) for t_, ent in sl.strips
                         if t_.startswith(name) for l, e, d in ent)
            want = {str(r.etch_level): (f"{r.etch_time:g}", r.date[11:])
                    for r in regs if r.name == name}
            if strip:                                   # spelled out
                self.assertEqual(strip, want, name)
            else:
                self.fail(f"{name}: dates differ, a strip is required")


class TestReportPdf(unittest.TestCase):
    def build(self, regs):
        doc = Doc(regs, "big.avg")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = os.path.join(self.tmp.name, "meta.pdf")
        exporters.export_metadata_pdf(doc, path)
        return path

    def test_pdf_builds_and_is_portrait(self):
        path = self.build([region("Survey", 160, step=1.0),
                           region("Mo 3d", 40), region("S 2p", 40)])
        with open(path, "rb") as fh:
            self.assertTrue(fh.read(5).startswith(b"%PDF"))
        try:
            import pymupdf as mu
        except ImportError:
            self.skipTest("PyMuPDF not installed")
        with mu.open(path) as d:
            self.assertEqual(len(d), 1)
            self.assertLess(d[0].rect.width, d[0].rect.height)

    def test_many_samples_and_a_depth_profile_stay_compact(self):
        try:
            import pymupdf as mu
        except ImportError:
            self.skipTest("PyMuPDF not installed")
        regs = []
        for i in range(6):
            for n, pe in (("Survey", 160), ("Mo 3d", 40), ("S 2p", 40),
                          ("C 1s", 40), ("O 1s", 40)):
                regs.append(region(n, pe, sample=f"Sample {i}"))
        for k in range(40):
            regs.append(depth("C 1s", k, k * 15.0, f"2020-01-01 10:{k:02d}:00"))
        path = self.build(regs)
        with mu.open(path) as d:
            text = "\n".join(p.get_text() for p in d)
            pages = len(d)
        # the old layout needed a page per sample (7) plus a row per level
        self.assertLessEqual(pages, 3)
        for token in ("Sample 0", "Sample 5", "Survey", "Mo 3d", "160", "40",
                      "0–39 (40)", "Common to every region",
                      "Page 1 of"):
            self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
