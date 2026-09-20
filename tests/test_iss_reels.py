"""ISS kinematics and element identification, the REELS band gap, their
storage beside the data, and how they are drawn.

Run:  python -m unittest discover tests
"""

import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import annotations  # noqa: E402
import elements as el  # noqa: E402
import reels  # noqa: E402
from readers import Region  # noqa: E402

try:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure
    HAVE_MPL = True
except Exception:
    HAVE_MPL = False

HE, AU, CU = 4.0026, 196.9666, 62.9296


class TestKinematics(unittest.TestCase):
    def test_head_on_backscatter_is_the_textbook_formula(self):
        for m2 in (CU, AU, 12.0):
            a = m2 / HE
            self.assertAlmostEqual(el.kinematic_factor(HE, m2, 180.0),
                                   ((a - 1) / (a + 1)) ** 2, 12)

    def test_ninety_degrees_is_the_other_textbook_formula(self):
        for m2 in (CU, AU, 12.0):
            a = m2 / HE
            self.assertAlmostEqual(el.kinematic_factor(HE, m2, 90.0),
                                   (a - 1) / (a + 1), 12)

    def test_heavier_targets_scatter_more_energy(self):
        ks = [el.kinematic_factor(HE, m, 123.03)
              for m in (12.0, 28.0, 63.0, 197.0)]
        self.assertEqual(ks, sorted(ks))
        self.assertTrue(all(0 < k < 1 for k in ks))

    def test_a_lighter_target_cannot_backscatter(self):
        self.assertIsNone(el.kinematic_factor(20.0, HE, 123.0))
        self.assertIsNone(el.kinematic_factor(20.0, 19.0, 150.0))
        self.assertIsNone(el.kinematic_factor(20.0, HE, 30.0))   # beyond arcsin(A)
        self.assertIsNotNone(el.kinematic_factor(20.0, HE, 5.0))  # small angles ok
        self.assertIsNone(el.kinematic_factor(0.0, 10.0, 100.0))

    def test_energy_scales_with_the_beam(self):
        self.assertAlmostEqual(el.iss_energy(2000.0, HE, CU, 123.03)
                               / el.iss_energy(1000.0, HE, CU, 123.03), 2.0)

    def test_known_peak_positions(self):
        # He+ 1 keV, 123.03 deg (worked out from the formula)
        for sym, mass in (("Cu", CU), ("Au", AU)):
            a = mass / HE
            th = math.radians(123.03)
            want = 1000 * ((math.cos(th) + math.sqrt(a * a - math.sin(th) ** 2))
                           / (1 + a)) ** 2
            e = el.iss_energy(1000.0, el.ion_mass("He+"), el.ELEMENTS[sym][1],
                              123.03)
            self.assertAlmostEqual(e, want, 6)
        self.assertGreater(el.iss_energy(1000, HE, AU, 123.03),
                           el.iss_energy(1000, HE, CU, 123.03))

    def test_table_is_sorted_and_excludes_light_targets(self):
        t = el.iss_table(1000.0, "He+", 123.03)
        e = [d["energy"] for d in t]
        self.assertEqual(e, sorted(e))
        syms = {d["symbol"] for d in t}
        self.assertNotIn("H", syms)
        self.assertNotIn("He", syms)                 # not heavier than He
        self.assertIn("Cu", syms)
        self.assertNotIn("He", {d["symbol"] for d in el.iss_table(
            1000, "Ne+", 123.03)})
        self.assertNotIn("C", {d["symbol"] for d in el.iss_table(
            1000, "Ar+", 123.03)})                   # lighter than the ion

    def test_candidates_near_a_measured_peak(self):
        cu = el.iss_energy(1000.0, HE, CU, 123.03)
        hits = el.candidates(cu + 1.2, 1000.0, "He+", 123.03)
        self.assertEqual(hits[0]["symbol"], "Cu")
        self.assertAlmostEqual(hits[0]["delta"], -1.2, 6)
        self.assertEqual([abs(h["delta"]) for h in hits],
                         sorted(abs(h["delta"]) for h in hits))
        self.assertEqual(el.candidates(10.0, 1000.0), [])
        wide = el.candidates(cu, 1000.0, window=60)
        self.assertGreater(len(wide), len(hits))

    def test_mass_from_energy_inverts_the_kinematics(self):
        for m in (12.0, CU, AU):
            e = el.iss_energy(1000.0, HE, m, 123.03)
            self.assertAlmostEqual(el.mass_from_energy(e, 1000.0, "He+",
                                                       123.03), m, 4)
        self.assertIsNone(el.mass_from_energy(-5.0, 1000.0))       # not physical
        self.assertIsNone(el.mass_from_energy(1000.0, 1000.0))     # above E0 x k_max
        self.assertIsNone(el.mass_from_energy(500.0, 100.0))

    def test_ion_names(self):
        self.assertEqual(el.ion_mass("He"), HE)
        self.assertEqual(el.ion_mass("Ne+"), el.ION_MASS["Ne+"])
        with self.assertRaises(ValueError):
            el.ion_mass("Zz+")

    def test_symbols_and_marks(self):
        self.assertEqual(el.parse_symbols("cu, AU  xx ni Cu"),
                         ["Cu", "Au", "Ni"])
        self.assertEqual(el.parse_symbols(""), [])
        self.assertEqual(el.parse_symbols(None), [])
        m = el.marks_for(["Cu", "Au", "C"], 1000.0, "He+", 123.03)
        self.assertEqual([s for s, _e in m], ["Cu", "Au", "C"])
        m = el.marks_for(["Cu", "Au"], 1000.0, "He+", 123.03, lo=900, hi=960)
        self.assertEqual([s for s, _e in m], ["Au"])   # only the ones in range
        self.assertEqual(el.marks_for(["He"], 1000.0, "Ne+", 123.03), [])

    def test_element_table_is_sane(self):
        zs = [v[0] for v in el.ELEMENTS.values()]
        self.assertEqual(zs, sorted(zs))
        self.assertEqual(zs[0], 1)
        for sym, (z, mass, name) in el.ELEMENTS.items():
            self.assertGreaterEqual(mass, z * 0.99, sym)     # mass >= ~Z
            self.assertTrue(name)


class TestReels(unittest.TestCase):
    def spectrum(self, gap=3.2, slope=400.0, base=100.0, el_ke=1000.0):
        """Loss spectrum: elastic peak, flat baseline, then a linear onset."""
        ke, y = [], []
        for i in range(0, 1201):
            loss = i * 0.01                          # 0..12 eV
            v = base + (slope * (loss - gap) if loss > gap else 0.0)
            v += 20000 * math.exp(-(loss / 0.25) ** 2)
            ke.append(el_ke - loss)
            y.append(v)
        return ke, y

    def test_the_gap_is_recovered_from_two_points_on_the_edge(self):
        ke, y = self.spectrum(gap=3.2)
        loss = reels.loss_axis(ke, 1000.0)
        p1 = (4.0, 100 + 400 * 0.8)
        p2 = (5.0, 100 + 400 * 1.8)
        res = reels.band_gap(loss, y, p1, p2)
        self.assertAlmostEqual(res["gap"], 3.2, 6)
        self.assertAlmostEqual(res["slope"], 400.0, 6)
        self.assertAlmostEqual(res["base"], 100.0, 6)

    def test_order_of_the_two_points_does_not_matter(self):
        ke, y = self.spectrum()
        loss = reels.loss_axis(ke, 1000.0)
        a = reels.band_gap(loss, y, (4.0, 420.0), (5.0, 820.0))
        b = reels.band_gap(loss, y, (5.0, 820.0), (4.0, 420.0))
        self.assertAlmostEqual(a["gap"], b["gap"], 9)

    def test_an_explicit_baseline_wins(self):
        ke, y = self.spectrum()
        loss = reels.loss_axis(ke, 1000.0)
        res = reels.band_gap(loss, y, (4.0, 420.0), (5.0, 820.0), base=0.0)
        self.assertAlmostEqual(res["gap"], 4.0 - 420.0 / 400.0, 9)

    def test_bad_picks_give_none(self):
        ke, y = self.spectrum()
        loss = reels.loss_axis(ke, 1000.0)
        self.assertIsNone(reels.band_gap(loss, y, (4.0, 420.0), (4.0, 820.0)))
        self.assertIsNone(reels.band_gap(loss, y, (4.0, 820.0), (5.0, 420.0)))
        self.assertIsNone(reels.band_gap(loss, y, (4.0, 100.0), (5.0, 100.0)))
        self.assertIsNone(reels.band_gap(loss, y, (float("nan"), 1.0),
                                         (2.0, 2.0)))
        # a tangent that would cross the baseline at a negative loss
        self.assertIsNone(reels.band_gap(loss, y, (0.1, 900.0), (0.2, 1300.0),
                                         base=100.0))

    def test_baseline_ignores_the_elastic_tail_and_falls_back(self):
        ke, y = self.spectrum(base=100.0)
        loss = reels.loss_axis(ke, 1000.0)
        self.assertAlmostEqual(reels.baseline(loss, y, (4.0, 5.0)), 100.0, 6)
        # onset right after the elastic tail: too few points between
        near = reels.baseline(loss, y, (0.6, 5.0))
        self.assertIsNotNone(near)
        self.assertIsNone(reels.baseline([], [], (1.0, 2.0)))

    def test_elastic_peak_and_axes(self):
        ke, y = self.spectrum(el_ke=1486.6)
        self.assertAlmostEqual(reels.elastic_peak(ke, y), 1486.6, 6)
        self.assertIsNone(reels.elastic_peak([], []))
        self.assertIsNone(reels.elastic_peak([1, 2], [1]))
        self.assertEqual(reels.loss_axis([10, 9], 10), [0, 1])

    def test_tangent_points_run_from_the_gap_up_the_edge(self):
        res = {"gap": 3.2, "slope": 400.0, "base": 100.0}
        a, b = reels.tangent_points(res, (4.0, 420.0), (5.0, 820.0))
        self.assertEqual(a, (3.2, 100.0))
        self.assertGreater(b[0], 5.0)
        self.assertAlmostEqual(b[1], 100 + 400 * (b[0] - 3.2), 6)


class TestStorage(unittest.TestCase):
    def test_kinetic_markers_round_trip_and_stay_apart(self):
        a = annotations.Annotations()
        a.add_marker("f1", "S", "ISS", 850.5, "Cu", kin=True)
        a.add_marker("f1", "S", "ISS", 850.5, "Cu", kin=True)      # duplicate
        a.add_marker("f1", "S", "ISS", 285.0, "C 1s")               # binding
        ms = a.markers_for("f1", "S", "ISS")
        self.assertEqual(len(ms), 2)
        self.assertTrue(ms[0]["kin"])
        self.assertNotIn("kin", ms[1])
        b = annotations.Annotations.from_json(a.to_json())
        self.assertEqual(b.markers_for("f1", "S", "ISS"), ms)

    def test_reels_round_trip_metadata_and_clearing(self):
        a = annotations.Annotations()
        self.assertIsNone(a.reels_for("f1", "S", "R"))
        d = {"elastic": 1486.6, "p1": [4.0, 420.0], "p2": [5.0, 820.0],
             "gap": 3.2, "base": 100.0, "slope": 400.0}
        a.set_reels("f1", "S", "R", d)
        self.assertFalse(a.is_empty())
        self.assertEqual(a.reels_for("f1", "S", "R")["gap"], 3.2)
        b = annotations.Annotations.from_json(a.to_json())
        self.assertEqual(b.reels_for("f1", "S", "R"), a.reels_for("f1", "S", "R"))
        r = Region(name="R", index=0, offset=0, sample="S")
        md = a.apply_metadata("f1", 0, r, {"Sample": "S", "Region": "R"})
        self.assertEqual(md["REELS band gap (eV)"], "3.20")
        self.assertEqual(md["REELS elastic peak (eV KE)"], "1486.60")
        a.set_reels("f1", "S", "R", None)
        self.assertTrue(a.is_empty())

    def test_a_construction_without_a_gap_is_kept_but_not_reported(self):
        a = annotations.Annotations()
        a.set_reels("f1", "S", "R", {"elastic": 1.0, "p1": [1, 2],
                                     "p2": [3, 4]})
        self.assertIsNone(a.reels_for("f1", "S", "R")["gap"])
        r = Region(name="R", index=0, offset=0, sample="S")
        self.assertNotIn("REELS band gap (eV)",
                         a.apply_metadata("f1", 0, r, {"Sample": "S"}))

    def test_loading_is_tolerant(self):
        b = annotations.Annotations.from_json({"reels": {
            "a": {"elastic": "x"}, "b": "junk", "c": {"elastic": 1,
                                                       "p1": [1], "p2": [1, 2]},
            "d": {"elastic": float("nan"), "p1": [1, 2], "p2": [1, 2]},
            "ok": {"elastic": 5, "p1": [1, 2], "p2": [2, 3], "gap": "bad"}}})
        self.assertEqual(list(b.reels), ["ok"])
        self.assertIsNone(b.reels["ok"]["gap"])
        self.assertEqual(annotations.Annotations.from_json(
            {"reels": [1]}).reels, {})
        b = annotations.Annotations.from_json({"markers": {"k": [
            {"be": 1, "label": "x", "kin": "yes"}, {"be": "z", "label": "y"}]}})
        self.assertEqual(b.markers["k"], [{"be": 1.0, "label": "x"}])


def region(kinetic=True, hv=1000.0, n=501):
    """An ISS-like spectrum: KE axis, peaks at Cu and Au energies."""
    cu = el.iss_energy(hv, HE, CU, 123.03)
    au = el.iss_energy(hv, HE, AU, 123.03)
    ke = [600.0 + i * 0.75 for i in range(n)]
    y = [50 + 900 * math.exp(-((k - cu) / 6) ** 2)
         + 1500 * math.exp(-((k - au) / 6) ** 2) for k in ke]
    if kinetic:
        return Region(name="ISS", index=0, offset=0, energy=ke, counts=y,
                      decodable=True, sample="S", photon_energy=hv,
                      energy_label="Kinetic Energy", technique="ISS")
    return Region(name="ISS", index=0, offset=0,
                  energy=[hv - k for k in ke], counts=y, decodable=True,
                  sample="S", photon_energy=hv, energy_label="Binding Energy")


@unittest.skipUnless(HAVE_MPL, "matplotlib not installed")
class TestDrawing(unittest.TestCase):
    def draw(self, r, markers=(), reels_arg=None, norm="None"):
        import plots
        fig = Figure(figsize=(6, 4))
        ax = fig.add_subplot(111)
        plots.draw_stack(ax, [r], 0.6, norm, None, ["#1f77b4"], "ISS", "",
                         (), False, markers=markers, reels=reels_arg,
                         scale="Kinetic" if "kinetic" in r.energy_label.lower()
                         else "Binding")
        fig.canvas.draw()
        return fig, ax

    def marker_xs(self, ax):
        return sorted(round(float(t.get_position()[0]), 1) for t in ax.texts
                      if t.get_text() in ("Cu", "Au"))

    def test_kinetic_markers_land_on_the_peak_on_a_kinetic_axis(self):
        r = region(kinetic=True)
        cu = el.iss_energy(1000.0, HE, CU, 123.03)
        au = el.iss_energy(1000.0, HE, AU, 123.03)
        _fig, ax = self.draw(r, [(cu, "Cu", True), (au, "Au", True)])
        self.assertEqual(self.marker_xs(ax), sorted([round(cu, 1),
                                                     round(au, 1)]))

    def test_the_same_markers_follow_the_axis_when_it_is_binding(self):
        r = region(kinetic=False)
        cu = el.iss_energy(1000.0, HE, CU, 123.03)
        _fig, ax = self.draw(r, [(cu, "Cu", True)])
        self.assertEqual(self.marker_xs(ax), [round(1000.0 - cu, 1)])

    def test_binding_markers_are_unchanged(self):
        r = region(kinetic=False)
        _fig, ax = self.draw(r, [(400.0, "Cu")])            # 2-tuple as before
        self.assertEqual(self.marker_xs(ax), [400.0])

    def reels_dict(self):
        return {"elastic": 1000.0, "p1": [4.0, 420.0], "p2": [5.0, 820.0],
                "gap": 3.2, "base": 100.0, "slope": 400.0}

    def reels_region(self):
        ke, y = TestReels().spectrum(el_ke=1000.0)
        return Region(name="REELS", index=0, offset=0, energy=ke, counts=y,
                      decodable=True, sample="S", photon_energy=1000.0,
                      energy_label="Kinetic Energy")

    def test_reels_overlay_draws_the_tangent_and_names_the_gap(self):
        r = self.reels_region()
        _fig, ax = self.draw(r, reels_arg=self.reels_dict())
        self.assertTrue(any("Eg = 3.20 eV" in t.get_text()
                            for t in ax.texts))
        tangent = [ln for ln in ax.lines if len(ln.get_xdata()) == 2
                   and ln.get_linestyle() == "-"]
        self.assertTrue(tangent)
        xs = list(tangent[-1].get_xdata())
        self.assertAlmostEqual(max(xs), 1000.0 - 3.2, 5)        # KE = el - gap

    def test_reels_overlay_follows_a_binding_axis(self):
        ke, y = TestReels().spectrum(el_ke=1000.0)
        r = Region(name="REELS", index=0, offset=0,
                   energy=[1000.0 - k for k in ke], counts=y, decodable=True,
                   sample="S", photon_energy=1000.0,
                   energy_label="Binding Energy")
        _fig, ax = self.draw(r, reels_arg=self.reels_dict())
        tangent = [ln for ln in ax.lines if len(ln.get_xdata()) == 2
                   and ln.get_linestyle() == "-"][-1]
        # loss L sits at BE = hv - (el - L) = L on this axis (el = hv)
        self.assertAlmostEqual(min(tangent.get_xdata()), 3.2, 5)

    def test_reels_overlay_scales_with_normalisation(self):
        r = self.reels_region()
        _fig, ax = self.draw(r, reels_arg=self.reels_dict(), norm="Max = 1")
        tangent = [ln for ln in ax.lines if len(ln.get_xdata()) == 2
                   and ln.get_linestyle() == "-"][-1]
        self.assertLess(max(tangent.get_ydata()), 5.0)          # not raw counts

    def test_incomplete_construction_draws_only_the_points(self):
        r = self.reels_region()
        d = {"elastic": 1000.0, "p1": [4.0, 420.0], "p2": [5.0, 820.0],
             "gap": None}
        _fig, ax = self.draw(r, reels_arg=d)
        self.assertFalse(any("Eg" in t.get_text() for t in ax.texts))

    def test_no_overlay_on_a_stack(self):
        import plots
        fig = Figure()
        ax = fig.add_subplot(111)
        r1, r2 = self.reels_region(), self.reels_region()
        plots.draw_stack(ax, [r1, r2], 0.6, "None", None, ["#000", "#111"],
                         "R", "", (), False, reels=self.reels_dict(),
                         scale="Kinetic")
        self.assertFalse(any("Eg" in t.get_text() for t in ax.texts))


class TestBrowserPayload(unittest.TestCase):
    def test_kinetic_markers_are_flagged_and_not_shifted(self):
        import htmlbrowser
        from readers import SpectrumFile
        r = region(kinetic=True)
        f = SpectrumFile()
        f.path = "a.vms"
        f.format_name = "Test"
        f.regions = [r]
        f._finish()
        ann = annotations.Annotations()
        f.annotations, f.file_id = ann, "f1"
        ann.add_marker("f1", "S", "ISS", 821.3, "Cu", kin=True)
        ann.add_marker("f1", "S", "ISS", 285.0, "C 1s")
        ann.set_shift(annotations.sample_key("f1", "S"), 0.8)
        marks = htmlbrowser.build_payload([f])["samples"][0]["regions"][0][
            "markers"]
        self.assertEqual(marks[0], {"be": 821.3, "label": "Cu", "kin": True})
        self.assertEqual(marks[1], {"be": 285.8, "label": "C 1s"})


if __name__ == "__main__":
    unittest.main()
