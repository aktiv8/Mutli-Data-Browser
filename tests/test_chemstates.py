"""Chemical-state identification: the reference table and candidate lookup.

Run:  python -m unittest discover tests
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chemstates as cs  # noqa: E402

STATES = cs.load_states()

FIXTURE = [
    {"core_level": "Fe 2p", "state": "Fe2p3/2 aFe2O3 peak 1", "be": 709.83,
     "fwhm": 1.0, "model": "GL (Area)", "source": "Biesinger et al."},
    {"core_level": "Fe 2p", "state": "Fe2p3/2 aFe2O3 peak 2", "be": 710.73,
     "fwhm": 1.2, "model": "GL (Area)", "source": "Biesinger et al."},
    {"core_level": "Fe 2p", "state": "Fe2p3/2 Metal", "be": 706.9,
     "fwhm": 0.9, "model": "GL (Area)", "source": "Biesinger et al."},
    {"core_level": "Ti 2p", "state": "Ti2p3/2 TiO2", "be": 709.6,
     "fwhm": 1.1, "model": "GL (Area)", "source": "Biesinger et al."},
]


class TestTable(unittest.TestCase):
    def test_bundled_table_is_sane(self):
        self.assertGreater(len(STATES), 100)
        levels = cs.core_levels(STATES)
        for lv in ("Fe 2p", "Ti 2p", "C 1s", "O 1s"):
            self.assertIn(lv, levels)
        for e in STATES:
            self.assertTrue(0 < e["be"] < 1500, e)
            self.assertTrue(e["source"])

    def test_core_levels_are_canonicalised(self):
        # no raw "Fe2p"/"Fe2p4"-style sheet key should have leaked through
        for lv in cs.core_levels(STATES):
            self.assertRegex(lv, r"^[A-Z][a-z]? \d[spdf]$")

    def test_missing_or_broken_file_gives_an_empty_table(self):
        self.assertEqual(cs.load_states("/no/such/file.json"), [])
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.json")
            with open(p, "w") as fh:
                fh.write("{not json")
            self.assertEqual(cs.load_states(p), [])
            with open(p, "w") as fh:
                json.dump({"states": [
                    {"core_level": "Fe 2p", "state": "X", "be": 710.0},
                    {"core_level": "Fe 2p", "state": "Y"},   # no be: dropped
                    "junk"]}, fh)
            self.assertEqual(len(cs.load_states(p)), 1)


class TestCandidates(unittest.TestCase):
    def test_nearest_first(self):
        got = cs.state_candidates(709.9, 4.0, FIXTURE, core_level="Fe 2p")
        self.assertEqual([cs.label_of(e) for _d, e in got],
                         ["Fe2p3/2 aFe2O3 peak 1", "Fe2p3/2 aFe2O3 peak 2",
                          "Fe2p3/2 Metal"])

    def test_core_level_restricts_the_match(self):
        # 709.6 is close to both an Fe 2p and a Ti 2p entry in the fixture
        got_all = cs.state_candidates(709.7, 1.0, FIXTURE)
        levels = {e["core_level"] for _d, e in got_all}
        self.assertEqual(levels, {"Fe 2p", "Ti 2p"})
        got_fe = cs.state_candidates(709.7, 1.0, FIXTURE, core_level="Fe 2p")
        self.assertTrue(all(e["core_level"] == "Fe 2p" for _d, e in got_fe))

    def test_core_level_is_canonicalised(self):
        # "Fe2p" (no space, as a Region.name might read) must match "Fe 2p"
        got = cs.state_candidates(709.9, 2.0, FIXTURE, core_level="Fe2p")
        self.assertTrue(got)
        self.assertTrue(all(e["core_level"] == "Fe 2p" for _d, e in got))

    def test_nothing_in_the_window(self):
        self.assertEqual(cs.state_candidates(600.0, 2.0, FIXTURE), [])
        self.assertEqual(
            cs.state_candidates(709.9, 0.01, FIXTURE, core_level="Fe 2p"), [])


if __name__ == "__main__":
    unittest.main()
