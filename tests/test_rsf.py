"""rsf.py: the RSF fallback table loader/lookup. Uses a small inline fixture,
not the real curated assets/xps_rsf.json, so this is independent of the
curation content.

Run:  python -m unittest discover tests
"""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import rsf  # noqa: E402

FIXTURE = [
    {"library": "scofield", "anode": "Al", "line": "C 1s", "rsf": 1.0},
    {"library": "scofield", "anode": "Al", "line": "Pt 4f", "rsf": 15.45},
    {"library": "scofield", "anode": "Al", "line": "Pt 4f7/2", "rsf": 8.65},
    {"library": "scofield", "anode": "Mg", "line": "Pt 4f", "rsf": 15.86},
    {"library": "kratos_f1s", "anode": "Al", "line": "Pt 4f", "rsf": 5.58},
    {"library": "kratos_f1s", "anode": "Al", "line": "F 1s", "rsf": 1.0},
]


class TestLoadRsf(unittest.TestCase):
    def test_missing_file_gives_empty_list(self):
        self.assertEqual(rsf.load_rsf("no such file.json"), [])

    def test_malformed_json_gives_empty_list(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                f.write("not json")
            self.assertEqual(rsf.load_rsf(path), [])
        finally:
            os.remove(path)

    def test_a_valid_file_loads_and_drops_bad_rows(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"rsf": FIXTURE + [
                    {"library": "scofield", "anode": "Al", "line": "X 1s",
                    "rsf": 0.0},               # rsf <= 0: dropped
                    {"library": "scofield", "line": "Y 1s", "rsf": 1.0},
                    # missing anode: dropped
                    "not a dict",
                ]}, f)
            out = rsf.load_rsf(path)
            self.assertEqual(len(out), len(FIXTURE))
        finally:
            os.remove(path)

    def test_the_shipped_asset_itself_loads(self):
        out = rsf.load_rsf()
        self.assertGreater(len(out), 1000)
        libs = {e["library"] for e in out}
        self.assertEqual(libs, {"scofield", "kratos_f1s"})


class TestAnodeFor(unittest.TestCase):
    def test_al_is_the_default(self):
        self.assertEqual(rsf.anode_for(None), "Al")
        self.assertEqual(rsf.anode_for(1486.6), "Al")

    def test_mg_when_nearer_to_it(self):
        self.assertEqual(rsf.anode_for(1253.6), "Mg")
        self.assertEqual(rsf.anode_for(1260.0), "Mg")

    def test_equidistant_falls_back_to_al(self):
        mid = (rsf.AL_HV + rsf.MG_HV) / 2.0
        self.assertEqual(rsf.anode_for(mid), "Al")


class TestRsfOf(unittest.TestCase):
    def test_exact_match(self):
        self.assertEqual(rsf.rsf_of("C 1s", FIXTURE, "scofield", 1486.6), 1.0)
        self.assertEqual(rsf.rsf_of("Pt 4f", FIXTURE, "scofield", 1486.6),
                         15.45)

    def test_split_line_is_not_combined_from_the_whole_subshell(self):
        # "Pt 4f7/2" is its own row, distinct from "Pt 4f" -- not derived
        self.assertEqual(
            rsf.rsf_of("Pt 4f7/2", FIXTURE, "scofield", 1486.6), 8.65)
        self.assertIsNone(
            rsf.rsf_of("Pt 4f5/2", FIXTURE, "scofield", 1486.6))

    def test_anode_picked_from_photon_energy(self):
        self.assertEqual(rsf.rsf_of("Pt 4f", FIXTURE, "scofield", 1253.6),
                         15.86)

    def test_different_libraries_give_different_values(self):
        self.assertEqual(rsf.rsf_of("Pt 4f", FIXTURE, "kratos_f1s", 1486.6),
                         5.58)

    def test_no_match_gives_none(self):
        self.assertIsNone(rsf.rsf_of("Zz 9z", FIXTURE, "scofield", 1486.6))
        self.assertIsNone(rsf.rsf_of("F 1s", FIXTURE, "scofield", 1486.6))


if __name__ == "__main__":
    unittest.main()
