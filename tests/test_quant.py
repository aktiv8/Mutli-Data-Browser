"""Quantification from CasaXPS fits: region rows, atomic percent, chemical
states, and (when the sample file is present) the numbers of a real fit.

Run:  python -m unittest discover tests
"""

import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import casafit  # noqa: E402
import quant  # noqa: E402
import readers  # noqa: E402
from readers import Region  # noqa: E402

try:
    import numpy as np
    HAVE_NP = True
except Exception:
    HAVE_NP = False

if HAVE_NP:
    from test_casafit import CASA, model_data

REAL = os.environ.get("XPS_QUANT_FILE", os.path.join(
    os.path.expanduser("~"), "Downloads", "For GK",
    "vanadium fitting example (1).vms"))


def linear_region(scans=25, dwell=0.27, hv=1486.71):
    """A synthetic fitted region (flat background under two components)."""
    lines = [l.replace("(*Shirley*)", "(*Linear*)") for l in CASA]
    fit = casafit.parse(lines)
    be, counts = model_data(fit, hv, dwell, scans, n=481, lo_be=440.0,
                            hi_be=475.0)
    r = Region(name="Ti 2p", index=0, offset=0, energy=be, counts=counts,
               decodable=True, sample="S", photon_energy=hv, dwell=dwell,
               pass_energy=20.0, step=0.1, count_units="counts",
               source="a.vms")
    r.extra["n_scans"] = scans
    r.fit = fit
    return r


@unittest.skipUnless(HAVE_NP, "numpy not installed")
class TestFitRows(unittest.TestCase):
    def test_one_row_with_its_numbers(self):
        r = linear_region()
        rows = quant.fit_rows(r)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["region"], "Ti 2p")
        self.assertEqual(row["background"], "Linear")
        self.assertAlmostEqual(row["rsf"], 2.001)
        self.assertEqual(row["basis"], "data")
        stored = sum(c["area"] for c in row["components"])
        self.assertAlmostEqual(row["area"] / stored, 1.0, delta=0.03)
        self.assertEqual(len(row["components"]), 2)
        self.assertIsNone(row["area_t"])            # no transmission function

    def test_area_does_not_depend_on_scans(self):
        # counts scale with dwell x scans; the area is per second
        a = quant.fit_rows(linear_region(scans=10))[0]["area"]
        b = quant.fit_rows(linear_region(scans=40))[0]["area"]
        self.assertAlmostEqual(a, b, delta=abs(a) * 1e-6)

    def test_component_positions_are_in_the_drawn_frame(self):
        r = linear_region()
        row = quant.fit_rows(r)[0]
        c = row["components"][0]
        # the fit's own binding energy for it: 1486.71 - (1028.1128 + shift)
        fit = r.fit
        self.assertAlmostEqual(
            c["be"], r.photon_energy - (fit.components[0].pos_ke
                                        + fit.shift_of_comps()), 9)
        j = int(np.argmax(np.asarray(r.counts)))
        self.assertAlmostEqual(c["be"], r.energy[j], delta=0.4)

    def test_region_limits_are_binding_energies(self):
        row = quant.fit_rows(linear_region())[0]
        self.assertLess(row["be_lo"], row["be_hi"])
        self.assertTrue(440.0 < row["be_lo"] and row["be_hi"] < 475.0)

    def test_overlapping_regions_of_one_name_count_once(self):
        r = linear_region()
        wide = copy.copy(r.fit.regions[0])
        wide.start_ke -= 3.0
        wide.end_ke += 3.0
        r.fit.regions.append(wide)
        rows = quant.fit_rows(r)
        self.assertEqual(len(rows), 1)

    def test_transmission_is_divided_out_when_present(self):
        r = linear_region()
        ke = r.kinetic_energy
        r.tf_ke = [min(ke) - 10, max(ke) + 10]
        r.tf_values = [2.0, 2.0]
        row = quant.fit_rows(r)[0]
        self.assertAlmostEqual(row["area_t"], row["area"] / 2.0,
                               delta=row["area"] * 1e-6)

    def test_no_fit_no_rows(self):
        r = linear_region()
        r.fit = None
        self.assertEqual(quant.fit_rows(r), [])
        r = linear_region()
        r.photon_energy = None
        self.assertEqual(quant.fit_rows(r), [])

    def test_unreproduced_background_falls_back_to_components(self):
        r = linear_region()
        r.fit.regions[0].background = "Tougaard 3 Parameter"   # not reproduced
        row = quant.fit_rows(r)[0]
        self.assertEqual(row["basis"], "components")
        self.assertAlmostEqual(
            row["area"], sum(c["area"] for c in row["components"]))
        self.assertFalse(row["background_known"])


@unittest.skipUnless(HAVE_NP, "numpy not installed")
class TestCurvesAndStates(unittest.TestCase):
    def test_curves_start_at_the_regions_first_point(self):
        r = linear_region()
        row = quant.fit_rows(r, curves=True)[0]
        cur = row["curves"]
        n = len(cur["env"])
        self.assertEqual([len(c) for c in cur["comps"]], [n, n])
        self.assertLess(cur["i0"] + n, len(r.counts) + 1)
        self.assertNotIn("curves", quant.fit_rows(r)[0])
        # counts, not per second: the envelope reaches the data's scale
        top = max(range(n), key=lambda k: cur["env"][k])
        self.assertAlmostEqual(cur["env"][top], r.counts[cur["i0"] + top],
                               delta=r.counts[cur["i0"] + top] * 0.1)

    def test_component_state_names(self):
        row = quant.fit_rows(linear_region())[0]
        c0, c1 = row["components"]
        self.assertEqual(c0["gk"], "n" + c0["name"])       # INDEX -1: stands alone
        self.assertEqual(c0["state"], c0["name"])
        self.assertEqual(c1["gk"], "i3")                   # INDEX 3, group "Ti(IV)"
        self.assertEqual(c1["state"], "Ti(IV)")

    def test_a_group_tag_that_is_only_the_region_label_is_not_a_name(self):
        c = {"name": "V 2p3/2 V(0)", "group": "V 2p", "index": 2}
        self.assertEqual(quant.state_of(c, "V 2p"), ("i2", "V 2p3/2 V(0)"))
        self.assertEqual(quant.state_of(dict(c, group="Metal"), "V 2p"),
                         ("i2", "Metal"))


class TestNormalise(unittest.TestCase):
    def rows(self):
        return [{"area": 100.0, "area_t": 50.0, "rsf": 1.0},
                {"area": 300.0, "area_t": 300.0, "rsf": 3.0},
                {"area": 40.0, "area_t": None, "rsf": 0.0},
                {"area": None, "rsf": 2.0},
                {"area": 200.0, "rsf": 2.0}]

    def test_atomic_percent(self):
        out = quant.normalise(self.rows())
        # area / RSF: 100, 100, (no RSF), (no area), 100  ->  a third each
        self.assertAlmostEqual(out[0]["at_pct"], 100 / 3)
        self.assertAlmostEqual(sum(x["at_pct"] for x in out
                                   if x["at_pct"] is not None), 100.0)
        self.assertEqual(out[2]["why"], "no RSF")
        self.assertEqual(out[3]["why"], "no area")
        self.assertIsNone(out[2]["at_pct"])

    def test_include_leaves_rows_out(self):
        out = quant.normalise(self.rows(), include=[True, False, True, True,
                                                    True])
        self.assertEqual(out[1]["why"], "not included")
        self.assertAlmostEqual(out[0]["at_pct"], 50.0)
        self.assertAlmostEqual(out[4]["at_pct"], 50.0)

    def test_transmission_switch(self):
        out = quant.normalise(self.rows(), transmission=True)
        # 50/1, 300/3, and the last row has no area_t so its area is used
        self.assertAlmostEqual(out[0]["corrected"], 50.0)
        self.assertAlmostEqual(out[4]["corrected"], 100.0)

    def test_nothing_usable(self):
        out = quant.normalise([{"area": 5.0, "rsf": 0.0}])
        self.assertIsNone(out[0]["at_pct"])
        self.assertEqual(quant.normalise([]), [])


class TestStates(unittest.TestCase):
    def test_index_groups_and_standalone_components(self):
        row = {"components": [
            {"name": "A 3/2", "group": "Metal", "index": 1, "area": 60.0},
            {"name": "A 1/2", "group": "Metal", "index": 1, "area": 30.0},
            {"name": "Oxide", "group": "", "index": -1, "area": 10.0}]}
        st = quant.states(row, 40.0)
        self.assertEqual([s["name"] for s in st], ["Metal", "Oxide"])
        self.assertAlmostEqual(st[0]["frac"], 0.9)
        self.assertAlmostEqual(st[0]["at_pct"], 36.0)
        self.assertAlmostEqual(sum(s["at_pct"] for s in st), 40.0)

    def test_index_minus_one_components_are_not_merged(self):
        row = {"components": [
            {"name": "C-C", "index": -1, "area": 3.0},
            {"name": "C-O", "index": -1, "area": 1.0}]}
        self.assertEqual([s["name"] for s in quant.states(row)],
                         ["C-C", "C-O"])

    def test_negative_or_no_area(self):
        self.assertEqual(quant.states({"components": []}), [])
        self.assertEqual(quant.states({"components": [
            {"name": "x", "index": -1, "area": -2.0}]}), [])
        self.assertIsNone(quant.states({"components": [
            {"name": "x", "index": -1, "area": 2.0}]})[0]["at_pct"])


def sample_groups():
    """Two depth levels of one sample, hand-made rows: fixture for the CSV
    (the HTML browser writes the same table in JavaScript)."""
    def comp(name, area, idx=-1, group=""):
        c = {"name": name, "group": group, "index": idx, "area": area}
        c["gk"], c["state"] = quant.state_of(c, "C 1s")
        return c
    a = {"region": "C 1s", "background": "Shirley", "rsf": 0.278, "area": 348.5,
         "area_t": 300.25, "basis": "data", "components": [
             comp("C-C", 235.0), comp("C-O", 58.0, 2, "Ether"),
             comp("C=O", 52.0, 2, "Ether")]}
    b = {"region": "O 1s", "background": "Shirley", "rsf": 0.78, "area": 512.0,
         "area_t": 450.0, "basis": "data", "components": []}
    c = {"region": "N 1s", "background": "Linear", "rsf": 0.0, "area": 12.0,
         "area_t": None, "basis": "components", "components": []}
    return [{"sample": "S, 1", "level": 1, "entries": [
                {"spectrum": "C 1s", "row": a}, {"spectrum": "O 1s", "row": b},
                {"spectrum": "N 1s", "row": c}]},
            {"sample": "S, 1", "level": 2, "entries": [
                {"spectrum": "C 1s", "row": dict(a, area=200.0, area_t=None)}]}]


class TestCsvRows(unittest.TestCase):
    def test_header_regions_and_states(self):
        rows = quant.csv_rows(sample_groups())
        self.assertEqual(tuple(rows[0]), quant.CSV_HEADER)
        # level 1: C 1s, its 2 states, O 1s, N 1s (no RSF); level 2: C 1s + 2
        self.assertEqual([r[3] for r in rows[1:]].count("C 1s"), 6)
        c = rows[1]
        self.assertEqual(c[:5], ["S, 1", "1", "C 1s", "C 1s", "Shirley"])
        self.assertEqual(c[5], "0.278")
        total = 348.5 / 0.278 + 512.0 / 0.78
        self.assertAlmostEqual(float(c[8]), 100 * 348.5 / 0.278 / total,
                               places=3)
        states = rows[2:4]
        self.assertEqual([r[9] for r in states], ["C-C", "Ether"])
        self.assertAlmostEqual(sum(float(r[10]) for r in states),
                               float(c[8]), places=3)
        n = [r for r in rows if r[3] == "N 1s"][0]
        self.assertEqual((n[8], n[11]), ("", "no RSF"))

    def test_levels_are_normalised_separately(self):
        rows = quant.csv_rows(sample_groups())
        level2 = [r for r in rows[1:] if r[1] == "2" and r[9] == ""]
        self.assertEqual(float(level2[0][8]), 100.0)

    def test_include_and_transmission(self):
        rows = quant.csv_rows(sample_groups(),
                              include=[[True, False, True], [True]])
        o = [r for r in rows if r[3] == "O 1s"][0]
        self.assertEqual((o[8], o[11]), ("", "not included"))
        c = [r for r in rows if r[3] == "C 1s"][0]
        self.assertEqual(float(c[8]), 100.0)
        t = quant.csv_rows(sample_groups(), transmission=True)
        c = [r for r in t if r[3] == "C 1s"][0]
        self.assertEqual(c[6], "300.25")                  # area / T is shown
        self.assertAlmostEqual(float(c[7]), 300.25 / 0.278, delta=0.01)


@unittest.skipUnless(HAVE_NP and os.path.isfile(REAL),
                     "vanadium sample file not present")
class TestRealVanadium(unittest.TestCase):
    """Numbers of a real CasaXPS fit (96 and 25 scans, two overlapping C 1s
    regions). Region area = data - Shirley, per second; RSFs as in the file."""

    @classmethod
    def setUpClass(cls):
        cls.doc = readers.load_file(REAL)
        cls.rows = {r.name: quant.fit_rows(r) for r in cls.doc.regions}

    def test_regions_and_rsf(self):
        v = self.rows["V 2p"]
        self.assertEqual(len(v), 1)
        self.assertAlmostEqual(v[0]["rsf"], 2.116)
        self.assertEqual(v[0]["background"], "Shirley")
        self.assertEqual(len(v[0]["components"]), 13)
        self.assertEqual(self.rows["Survey"], [])

    def test_overlapping_c1s_regions_count_once(self):
        c = self.rows["C 1s"]
        self.assertEqual(len(c), 1)
        self.assertAlmostEqual(c[0]["rsf"], 0.278)

    def test_areas_are_per_second_not_per_sweep_sum(self):
        v = self.rows["V 2p"][0]
        stored = sum(c["area"] for c in v["components"])
        self.assertAlmostEqual(stored, 6930.4, delta=1.0)
        self.assertAlmostEqual(v["area"], 7259.7, delta=5.0)
        self.assertAlmostEqual(v["area"] / stored, 1.0, delta=0.08)
        c = self.rows["C 1s"][0]
        self.assertAlmostEqual(c["area"], 347.9, delta=2.0)

    def test_atomic_percent_from_area_over_rsf(self):
        rows = self.rows["V 2p"] + self.rows["C 1s"]
        out = quant.normalise(rows)
        v = 7259.7 / 2.116
        c = 347.9 / 0.278
        self.assertAlmostEqual(out[0]["at_pct"], 100 * v / (v + c), delta=0.2)
        self.assertAlmostEqual(out[0]["at_pct"] + out[1]["at_pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
