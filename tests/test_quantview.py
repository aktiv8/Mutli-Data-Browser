"""What the desktop Quantification tab lets the user change (quantview.py):
region ticks, the transmission choice, levels, profile modes and the CSV.

Run:  python -m unittest discover tests
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import quant  # noqa: E402
import quantview as qv  # noqa: E402
import resultspages as rp  # noqa: E402
from test_results import (level, row, sample,  # noqa: E402
                          three_element_level)


def pct(lv):
    return {e["row"]["region"]: x["at_pct"]
            for e, x in zip(lv.entries, lv.res)}


def with_transmission(r, factor):
    out = dict(r)
    out["area_t"] = r["area"] * factor
    return out


class TestTicks(unittest.TestCase):
    def setUp(self):
        self.s = sample("S", [three_element_level(None)])
        self.st = qv.ViewState()

    def test_with_no_choices_the_numbers_are_the_reports(self):
        eff = qv.effective(self.s, 0, self.st)
        self.assertEqual(pct(eff), pct(self.s.levels[0]))
        self.assertEqual(eff.include, self.s.levels[0].include)

    def test_unticking_a_region_shares_the_total_between_the_rest(self):
        names = [e["row"]["region"] for e in self.s.levels[0].entries]
        self.st.toggle(self.s.key, 0, names.index("C 1s"), True)
        eff = qv.effective(self.s, 0, self.st)
        got = pct(eff)
        self.assertIsNone(got["C 1s"])
        self.assertEqual(eff.res[names.index("C 1s")]["why"], "not included")
        self.assertAlmostEqual(got["Ti 2p"] + got["O 1s"], 100.0)
        # and the report's own level is untouched
        self.assertIsNotNone(pct(self.s.levels[0])["C 1s"])

    def test_toggling_back_to_the_default_forgets_the_choice(self):
        self.assertFalse(self.st.toggle(self.s.key, 0, 1, True))
        self.assertTrue(any(qv.changed(self.s, 0, self.st)))
        self.assertTrue(self.st.toggle(self.s.key, 0, 1, True))
        self.assertFalse(any(qv.changed(self.s, 0, self.st)))
        self.assertEqual(self.st.include, {})

    def test_a_region_the_report_leaves_out_can_be_ticked(self):
        lv = level(None, [row("C 1s", 0.25, 30.0), row("O 1s", 1.0, 100.0),
                          row("C 1s", 0.25, 60.0)])       # C 1s twice
        self.assertEqual(lv.include, [True, True, False])
        s = sample("T", [lv])
        eff = qv.effective(s, 0, self.st)
        self.assertEqual(eff.res[2]["why"], "counted once")   # default kept
        self.st.toggle(s.key, 0, 2, False)
        eff = qv.effective(s, 0, self.st)
        self.assertIsNotNone(eff.res[2]["at_pct"])
        self.assertEqual(eff.res[2]["why"], "")
        self.assertAlmostEqual(sum(x["at_pct"] for x in eff.res
                                   if x["at_pct"] is not None), 100.0)

    def test_unticking_a_default_exclusion_keeps_the_reports_reason(self):
        lv = level(None, [row("C 1s", 0.25, 30.0), row("C 1s", 0.25, 60.0)])
        s = sample("T", [lv])
        self.st.toggle(s.key, 0, 0, True)            # untick the one counted
        eff = qv.effective(s, 0, self.st)
        self.assertEqual(eff.res[0]["why"], "not included")
        self.assertEqual(eff.res[1]["why"], "counted once")

    def test_reset_forgets_one_sample_or_all(self):
        other = sample("U", [three_element_level(None)])
        self.st.toggle(self.s.key, 0, 0, True)
        self.st.toggle(other.key, 0, 0, True)
        self.st.reset(self.s.key)
        self.assertEqual(list(self.st.include), [(other.key, 0, 0)])
        self.st.reset()
        self.assertEqual(self.st.include, {})

    def test_composition_cells_follow_the_ticks(self):
        self.st.toggle(self.s.key, 0, 0, True)           # Ti 2p out
        cells = {c[0]: c for k, c in qv.composition(self.s, 0, self.st)
                 if k == "region"}
        self.assertEqual(cells["Ti 2p"][5], "not included")


class TestTransmission(unittest.TestCase):
    def make(self, with_t):
        rows = [row("A", 1.0, 100.0), row("B", 1.0, 100.0)]
        if with_t:
            rows[0] = with_transmission(rows[0], 2.0)    # only A has one
        return sample("T", [level(None, rows)])

    def test_available_only_when_a_row_carries_it(self):
        self.assertFalse(qv.transmission_available([self.make(False)]))
        self.assertTrue(qv.transmission_available([self.make(True)]))

    def test_dividing_it_out_changes_the_shares(self):
        s = self.make(True)
        st = qv.ViewState()
        off = pct(qv.effective(s, 0, st))
        st.transmission = True
        on = pct(qv.effective(s, 0, st))
        self.assertAlmostEqual(off["A"], 50.0)
        self.assertAlmostEqual(on["A"], 200.0 / 300.0 * 100.0)

    def test_without_it_the_choice_changes_nothing(self):
        s = self.make(False)
        st = qv.ViewState()
        off = pct(qv.effective(s, 0, st))
        st.transmission = True
        self.assertEqual(pct(qv.effective(s, 0, st)), off)


class TestLevelsAndProfile(unittest.TestCase):
    def setUp(self):
        self.s = sample("D", [three_element_level(i, etch=10.0 * i)
                              for i in range(3)])
        self.st = qv.ViewState()

    def test_level_index_is_clamped(self):
        self.st.level[self.s.key] = 7
        self.assertEqual(self.st.level_index(self.s), 2)
        self.st.level[self.s.key] = -3
        self.assertEqual(self.st.level_index(self.s), 0)
        self.assertEqual(self.st.level_index(sample("E", [])), 0)

    def test_a_profile_sample_opens_on_the_profile_and_one_level_on_demand(self):
        self.assertIsNone(self.st.shown(self.s))
        self.st.level[self.s.key] = 1
        self.assertEqual(self.st.shown(self.s), 1)
        self.st.level[self.s.key] = None
        self.assertIsNone(self.st.shown(self.s))
        one = sample("O", [three_element_level(None)])
        self.assertEqual(self.st.shown(one), 0)           # not a profile

    def test_ticks_are_dropped_when_the_regions_change(self):
        self.st.sync([self.s])
        self.st.toggle(self.s.key, 0, 0, True)
        self.st.sync([self.s])                            # same regions
        self.assertEqual(len(self.st.include), 1)
        again = sample("D", [three_element_level(i, etch=10.0 * i)
                             for i in range(3)])
        again.levels[0].entries.pop()                     # a spectrum left
        self.st.sync([again])
        self.assertEqual(self.st.include, {})

    def test_level_labels_say_what_is_known(self):
        lv = three_element_level(2, etch=40.0, depth=2.5)
        self.assertEqual(qv.level_label(lv, 0), "Level 2 (etch 40 s, 2.5 nm)")
        self.assertEqual(qv.level_label(three_element_level(None), 4),
                         "Level 5")

    def test_the_default_profile_is_the_reports(self):
        self.assertEqual(qv.profile_cells(self.s, self.st),
                         rp.profile_cells(self.s))

    def test_modes_give_regions_states_or_shares(self):
        names = lambda: [x["name"] for x in qv.profile(self.s, self.st)["series"]]  # noqa: E731,E501
        self.assertEqual(names(), ["Ti 2p", "O 1s", "C 1s"])
        self.st.profile_mode = "state"
        self.assertIn("Ti 2p: Ti-C", names())
        self.st.profile_mode = "share"
        series = {x["name"]: x["values"]
                  for x in qv.profile(self.s, self.st)["series"]}
        self.assertAlmostEqual(series["Ti 2p: Ti-C"][0], 60.0)

    def test_a_tick_in_one_level_reaches_only_that_level(self):
        before = qv.profile(self.s, self.st)["series"][0]["values"]
        ei = [e["row"]["region"] for e in self.s.levels[1].entries] \
            .index("C 1s")
        self.st.toggle(self.s.key, 1, ei, True)
        series = {x["name"]: x["values"]
                  for x in qv.profile(self.s, self.st)["series"]}
        self.assertIsNone(series["C 1s"][1])
        self.assertIsNotNone(series["C 1s"][0])
        self.assertNotEqual(series["Ti 2p"][1], before[1])
        self.assertEqual(series["Ti 2p"][0], before[0])


class TestCsv(unittest.TestCase):
    def setUp(self):
        self.a = sample("A", [three_element_level(0), three_element_level(1)])
        self.b = sample("B", [three_element_level(None, ti=50.0)])
        self.st = qv.ViewState()

    def test_defaults_equal_quant_csv_rows_with_one_header(self):
        got = qv.csv_table([self.a, self.b], self.st)
        want = quant.csv_rows(
            [{"sample": "A", "level": 0, "entries": self.a.levels[0].entries},
             {"sample": "A", "level": 1, "entries": self.a.levels[1].entries}],
            [self.a.levels[0].include, self.a.levels[1].include])
        want += quant.csv_rows(
            [{"sample": "B", "level": None,
              "entries": self.b.levels[0].entries}],
            [self.b.levels[0].include])[1:]
        self.assertEqual(got, want)
        self.assertEqual(sum(r == list(quant.CSV_HEADER) for r in got), 1)

    def test_ticks_and_transmission_reach_the_file(self):
        self.st.toggle(self.a.key, 0, 2, True)           # C 1s of level 0
        got = qv.csv_table([self.a], self.st)
        c1s = [r for r in got if r[3] == "C 1s" and r[1] == "0"
               and r[9] == ""]
        self.assertEqual(c1s[0][8], "")                   # no at %
        self.assertEqual(c1s[0][11], "not included")
        other = [r for r in got if r[3] == "C 1s" and r[1] == "1"
                 and r[9] == ""]
        self.assertNotEqual(other[0][8], "")


if __name__ == "__main__":
    unittest.main()
