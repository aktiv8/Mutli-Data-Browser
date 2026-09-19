"""User annotations (names, notes, edits, BE shifts, markers) and the
binding-energy calibration helpers.

Run:  python -m unittest discover tests
"""

import math
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import annotations as an  # noqa: E402
import calibration as cal  # noqa: E402
import workbook as wbk  # noqa: E402
from test_metasummary import Doc, region  # noqa: E402


class TestAnnotations(unittest.TestCase):
    def test_names_reset_and_precedence(self):
        a = an.Annotations()
        a.set_name("sample_names", an.sample_key("f1", "S1"), "Pristine", "S1")
        a.set_name("region_names", an.region_key("f1", "S1", "C 1s"),
                   "Carbon", "C 1s")
        self.assertEqual(a.sample_label("f1", "S1"), "Pristine")
        self.assertEqual(a.sample_label("f1", "S2"), "S2")
        self.assertEqual(a.region_label("f1", "S1", "C 1s"), "Carbon")
        a.set_name("sample_names", an.sample_key("f1", "S1"), "S1", "S1")
        self.assertEqual(a.sample_label("f1", "S1"), "S1")      # reset
        self.assertNotIn(an.sample_key("f1", "S1"), a.sample_names)

    def test_shift_most_specific_scope_wins(self):
        a = an.Annotations()
        a.set_shift("f1", 0.5)
        self.assertAlmostEqual(a.shift_for("f1", "S", "C 1s"), 0.5)
        a.set_shift(an.sample_key("f1", "S"), 0.8)
        a.set_shift(an.region_key("f1", "S", "C 1s"), 1.2)
        self.assertAlmostEqual(a.shift_for("f1", "S", "C 1s"), 1.2)
        self.assertAlmostEqual(a.shift_for("f1", "S", "O 1s"), 0.8)
        self.assertAlmostEqual(a.shift_for("f1", "T", "O 1s"), 0.5)
        self.assertEqual(a.shift_for("f2", "S", "C 1s"), 0.0)
        a.set_shift(an.region_key("f1", "S", "C 1s"), 0.0)       # remove
        self.assertAlmostEqual(a.shift_for("f1", "S", "C 1s"), 0.8)

    def test_apply_metadata(self):
        r = region("C 1s", 40, sample="S1")
        a = an.Annotations()
        a.set_name("sample_names", an.sample_key("f1", "S1"), "Pristine", "S1")
        a.set_note("sample_notes", an.sample_key("f1", "S1"), "  dry  ")
        a.set_shift(an.sample_key("f1", "S1"), 0.35)
        a.set_meta("f1", 0, "Operator", "Dr X")
        a.set_meta("f1", 0, "Extra field", 7)
        md = {"Sample": "S1", "Region": "C 1s", "Operator": ""}
        out = a.apply_metadata("f1", 0, r, md)
        self.assertEqual(out["Sample"], "Pristine")
        self.assertEqual(out["Operator"], "Dr X")
        self.assertEqual(out["Extra field"], "7")
        self.assertEqual(out["BE shift (eV)"], "+0.350")
        self.assertEqual(out["Notes"], "dry")
        self.assertEqual(md["Operator"], "")                    # input intact
        self.assertEqual(a.edited_keys("f1", 0), {"Operator", "Extra field"})
        a.reset_meta("f1", 0, "Operator")
        self.assertEqual(a.edited_keys("f1", 0), {"Extra field"})
        a.reset_meta("f1", 0)
        self.assertEqual(a.edited_keys("f1", 0), set())

    def test_markers_are_deduplicated(self):
        a = an.Annotations()
        a.add_marker("f1", "S", "Survey", 285.0, "C 1s")
        a.add_marker("f1", "S", "Survey", 285.0, "C 1s")
        a.add_marker("f1", "S", "Survey", 532.0, "O 1s")
        self.assertEqual(len(a.markers_for("f1", "S", "Survey")), 2)
        a.remove_marker("f1", "S", "Survey", 285.0, "C 1s")
        self.assertEqual([m["label"] for m in a.markers_for("f1", "S", "Survey")],
                         ["O 1s"])
        a.remove_marker("f1", "S", "Survey", 532.0, "O 1s")
        self.assertNotIn(an.region_key("f1", "S", "Survey"), a.markers)
        a.add_marker("f1", "S", "Survey", 1.0, "X")
        a.clear_markers("f1", "S", "Survey")
        self.assertEqual(a.markers_for("f1", "S", "Survey"), [])

    def test_json_round_trip_and_tolerance(self):
        a = an.Annotations(experiment_notes="hello",
                           calibration_statement="stated")
        a.set_name("region_names", "f1|S|C 1s", "Carbon", "C 1s")
        a.set_shift("f1", -0.4, {"reference": 284.8, "measured": 285.2})
        a.add_marker("f1", "S", "Survey", 285.0, "C 1s")
        a.set_meta("f1", 3, "k", "v")
        a.extra = {"future": 1}
        b = an.Annotations.from_json(a.to_json())
        self.assertEqual(b.to_json(), a.to_json())
        self.assertFalse(b.is_empty())
        self.assertTrue(an.Annotations().is_empty())
        junk = an.Annotations.from_json({
            "shifts": {"f1": "abc", "f2": "1.5"}, "markers": {"k": [
                {"be": "x", "label": "a"}, {"be": 1, "label": "ok"}]},
            "md_edits": {"k": "nope"}, "sample_names": [1], "calibration": 3})
        self.assertEqual(junk.shifts, {"f2": 1.5})
        self.assertEqual(junk.markers, {"k": [{"be": 1.0, "label": "ok"}]})
        self.assertTrue(an.Annotations.from_json("x").is_empty())

    def test_copy_is_independent(self):
        a = an.Annotations()
        a.set_shift("f1", 1.0)
        b = a.copy()
        b.set_shift("f1", 2.0)
        self.assertEqual(a.shifts["f1"], 1.0)


class TestReaderHooks(unittest.TestCase):
    def test_metadata_and_sample_names_flow_through_the_parser(self):
        doc = Doc([region("C 1s", 40, sample="S1"),
                   region("O 1s", 40, sample="S1"),
                   region("C 1s", 40, sample="S2")])
        doc.file_id = "f1"
        base = doc.region_metadata(doc.regions[0])
        self.assertEqual(base["Sample"], "S1")
        a = an.Annotations()
        a.set_name("sample_names", an.sample_key("f1", "S1"), "Pristine", "S1")
        a.set_meta("f1", 1, "Operator", "DM")
        doc.annotations = a
        self.assertEqual(doc.region_metadata(doc.regions[0])["Sample"],
                         "Pristine")
        self.assertEqual(doc.region_metadata(doc.regions[1])["Operator"], "DM")
        names = [s for s, _rows in doc.samples_metadata()]
        self.assertEqual(names, ["Pristine", "S2"])
        self.assertEqual(doc.region_pos(doc.regions[2]), 2)
        rows = doc.metadata_rows()                    # CSV path
        self.assertEqual(rows[1]["Operator"], "DM")


class TestWorkbookKeepsAnnotations(unittest.TestCase):
    def test_round_trip(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        src = os.path.join(tmp, "a.vgd")
        with open(src, "wb") as fh:
            fh.write(b"data")
        a = an.Annotations()
        a.set_shift("f1", 0.42)
        wb = wbk.Workbook(files=[wbk.FileEntry("f1", "a.vgd", src)],
                          annotations=a.to_json())
        path = os.path.join(tmp, "x" + wbk.EXT)
        wbk.save(path, wb)
        out = wbk.load(path, os.path.join(tmp, "e"))
        self.assertEqual(an.Annotations.from_json(out.annotations).shifts,
                         {"f1": 0.42})
        # an older workbook without the member still loads
        import zipfile
        old = os.path.join(tmp, "old" + wbk.EXT)
        with zipfile.ZipFile(path) as zin, zipfile.ZipFile(old, "w") as zout:
            for n in zin.namelist():
                if n != "annotations.json":
                    zout.writestr(n, zin.read(n))
        self.assertEqual(wbk.load(old, os.path.join(tmp, "e2")).annotations,
                         {})


class TestCalibration(unittest.TestCase):
    def peak(self, centre, lo=280.0, hi=292.0, step=0.05, descending=True):
        n = int(round((hi - lo) / step)) + 1
        e = [hi - i * step for i in range(n)] if descending \
            else [lo + i * step for i in range(n)]
        y = [50 + 1000 * math.exp(-((x - centre) / 0.6) ** 2) for x in e]
        return e, y

    def test_find_peak_is_accurate_to_a_fraction_of_the_step(self):
        for centre in (285.13, 284.87, 286.4):
            for desc in (True, False):
                e, y = self.peak(centre, descending=desc)
                be, h = cal.find_peak(e, y, 283, 288)
                self.assertAlmostEqual(be, centre, delta=0.02)
                self.assertGreater(h, 900)

    def test_noise_does_not_pull_the_peak_away(self):
        import random
        rnd = random.Random(1)
        e, y = self.peak(285.3)
        y = [v + rnd.gauss(0, 15) for v in y]
        be, _h = cal.find_peak(e, y, 283, 288)
        self.assertAlmostEqual(be, 285.3, delta=0.08)

    def test_window_limits_and_empty_window(self):
        e, y = self.peak(285.0)
        self.assertIsNone(cal.find_peak(e, y, 400, 410))
        be, _ = cal.find_peak(e, y, 290, 292)      # only the tail: at an edge
        self.assertGreaterEqual(be, 290)

    def test_shift_and_statement(self):
        self.assertAlmostEqual(cal.shift_for(285.3, 284.8), -0.5)
        entries = [{"scope": "f1", "shift": -0.5, "measured": 285.3,
                    "reference": 284.8, "ref_text": "C 1s", "scope_text": "x"},
                   {"scope": "f1", "shift": -0.6, "measured": 285.4,
                    "reference": 284.8, "ref_text": "C 1s", "scope_text": "x"}]
        text = cal.statement(entries)
        self.assertIn("-0.60 eV", text)                # latest per scope
        self.assertNotIn("-0.50", text)
        self.assertEqual(cal.statement(entries, "  Custom words. "),
                         "Custom words.")
        self.assertEqual(cal.statement([{"scope": "a", "shift": 0}]), "")

    def test_presets(self):
        labels = [p[0] for p in cal.PRESETS]
        self.assertIn("C 1s adventitious carbon - 284.8 eV", labels)
        self.assertEqual(cal.PRESETS[-1][0], "Custom")


if __name__ == "__main__":
    unittest.main()
