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


class TestReportBlock(unittest.TestCase):
    def test_pass_energy_grouped_and_constants_hoisted(self):
        doc = Doc([region("Survey", 160, step=1.0), region("Mo 3d", 40),
                   region("S 2p", 40)])
        info, columns = exporters._sample_block(doc.metadata_rows())
        info = dict(info)
        self.assertEqual(info["Pass energy (eV)"],
                         "40: Mo 3d, S 2p; 160: Survey")
        self.assertEqual(info["Photon energy (eV)"], "1486.60")
        self.assertEqual(info["Lens mode"], "Hybrid")
        heads = [c[0] for c in columns]
        self.assertNotIn("PE (eV)", heads)       # now in the header block
        self.assertNotIn("hv (eV)", heads)       # constant
        self.assertIn("Step (eV)", heads)        # differs (survey vs narrow)

    def test_single_region_keeps_its_columns(self):
        doc = Doc([region("Mo 3d", 40)])
        _info, columns = exporters._sample_block(doc.metadata_rows())
        self.assertEqual(len(columns), len(exporters._REGION_COLS))

    def test_pdf_builds(self):
        doc = Doc([region("Survey", 160, step=1.0), region("Mo 3d", 40),
                   region("S 2p", 40)])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "meta.pdf")
            exporters.export_metadata_pdf(doc, path)
            self.assertGreater(os.path.getsize(path), 1000)
            with open(path, "rb") as fh:
                self.assertTrue(fh.read(5).startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
