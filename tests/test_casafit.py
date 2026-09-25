"""CasaXPS fits: line shapes and backgrounds, parsing the comment lines,
reconstructing the curves in the right energy frame and scale, writing the fit
back to VAMAS and CSV, and (when the sample files are present) agreement with
real CasaXPS fits.

Run:  python -m unittest discover tests
"""

import csv
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import casafit  # noqa: E402
import exporters  # noqa: E402
import lineshapes as ls  # noqa: E402
import readers  # noqa: E402
from readers import Region  # noqa: E402

try:
    import numpy as np
    HAVE_NP = True
except Exception:
    HAVE_NP = False

REAL_DIR = os.environ.get("XPS_CASA_DIR", os.path.join(
    os.path.expanduser("~"), "Documents",
    "Brazil Training Course September 2025",
    "September 2nd - Advanced Chemical State Analysis", "Data"))

CASA = [
    "Casa Info Follows",
    "1",
    "Calib M = 455.59 A = 458.6 BE ADD",
    "1",
    "annot comps Display 0.05 0.05 RGB(0,0,0) Font(14,18,0,0,Times New Roman)",
    "",
    "1",
    "CASA region (*Ti 2p*) (*Shirley*) 1019.0251 1034.8837 2.001 1 0 0 299 542 "
    "275 9.3 (*Ti 2p*) 47.8784",
    "2",
    "CASA comp (*Ti 2p3/2 Ti(IV)*) (*GL(30)*) Area 3394.1269 0.001 10000000 "
    "-1 1 MFWHM 1.2737472 0.29 7.36 -1 1 Position 1028.1128 1014.59 1034.69 "
    "-1 1 RSF 2.001 MASS 47.8784 INDEX -1 (*Ti 2p*)",
    "CASA comp (*Ti 2p1/2 Ti(IV)*) (*GL(30)*) Area 1697.0635 0.001 10000000 "
    "0 0.5 MFWHM 2.3 0.5 2.3 -1 1 Position 1022.3928 0 0 0 -5.72 RSF 0 MASS "
    "47.8784 INDEX 3 (*Ti(IV)*)",
    "   Lens Mode:Hybrid   Resolution:Pass energy 20",
    "e:\\some\\path.vms",
]


# ------------------------------------------------------------------ shapes
@unittest.skipUnless(HAVE_NP, "numpy not installed")
class TestShapes(unittest.TestCase):
    ke = np.linspace(1000.0, 1010.0, 4001)            # 0.0025 eV steps

    def area(self, y):
        return float(np.trapezoid(y, self.ke) if hasattr(np, "trapezoid")
                     else np.trapz(y, self.ke))

    def fwhm(self, y):
        half = y.max() / 2
        idx = np.where(y >= half)[0]
        return float(self.ke[idx[-1]] - self.ke[idx[0]])

    def test_area_is_the_stored_area(self):
        # a window wide enough to hold the full extent of every shape here,
        # including GL(100)'s slow Lorentzian tail: a component is
        # normalised against its own extent, not the window it happens to
        # be drawn on, so a narrower window is allowed to show less than
        # the stored area (see test_a_narrow_window_does_not_inflate_the_peak).
        wide = np.linspace(1005.0 - 200 * 1.3, 1005.0 + 200 * 1.3, 8001)
        for shape in ("GL(0)", "GL(30)", "GL(100)", "SGL(30)",
                      "LA(1.1,1.9,7)", "LA(50)", "LF(1.1,1.2,75,200)"):
            y = ls.component_curve(wide, shape, 1005.0, 1.3, 1234.5)
            area = float(np.trapezoid(y, wide) if hasattr(np, "trapezoid")
                         else np.trapz(y, wide))
            self.assertAlmostEqual(area / 1234.5, 1.0, 2, shape)

    def test_a_narrow_window_does_not_inflate_the_peak(self):
        # GL(100) is a pure Lorentzian: its tail reaches well past a tight
        # window. The regression this guards: component_curve used to
        # normalise over whatever grid it was given, so a window narrower
        # than the tail inflated the visible peak to make up the missing
        # area -- exactly the bug that let a reconstructed fit envelope
        # rise above the raw data it was fitted to.
        full = ls.component_curve(self.ke, "GL(100)", 1005.0, 1.3, 1234.5)
        narrow_x = np.linspace(1003.0, 1007.0, 1601)      # +-1.54 FWHM only
        narrow = ls.component_curve(narrow_x, "GL(100)", 1005.0, 1.3, 1234.5)
        self.assertAlmostEqual(float(narrow.max()), float(full.max()), 6)

    def test_gl_and_sgl_have_the_stated_fwhm_and_position(self):
        for shape in ("GL(0)", "GL(30)", "GL(100)", "SGL(30)"):
            y = ls.component_curve(self.ke, shape, 1005.0, 1.3, 1000.0)
            self.assertAlmostEqual(self.ke[int(np.argmax(y))], 1005.0, 2)
            if shape in ("GL(0)", "GL(100)", "SGL(100)"):
                self.assertAlmostEqual(self.fwhm(y), 1.3, 2, shape)

    def test_gl_extremes_are_gaussian_and_lorentzian(self):
        g = ls.component_curve(self.ke, "GL(0)", 1005.0, 1.3, 1.0)
        sig = 1.3 / 2.3548200450309493
        want = np.exp(-0.5 * ((self.ke - 1005.0) / sig) ** 2)
        want *= g.max() / want.max()
        self.assertLess(float(np.abs(g - want).max()) / g.max(), 1e-6)
        lor = ls.component_curve(self.ke, "GL(100)", 1005.0, 1.3, 1.0)
        want = 1 / (1 + 4 * ((self.ke - 1005.0) / 1.3) ** 2)
        want *= lor.max() / want.max()
        self.assertLess(float(np.abs(lor - want).max()) / lor.max(), 1e-9)

    def test_sgl_is_the_sum_and_gl_the_product(self):
        # compares shapes (each normalised to its own peak), not the area
        # scale -- that is test_area_is_the_stored_area's job, and is no
        # longer just "integral over this window" (see component_curve).
        t = (self.ke - 1005.0) / 1.3
        lor = 1 / (1 + 4 * t * t)
        gau = np.exp(-4 * np.log(2) * t * t)
        sgl = ls.component_curve(self.ke, "SGL(30)", 1005.0, 1.3, 1.0)
        want = 0.3 * lor + 0.7 * gau
        np.testing.assert_allclose(sgl / sgl.max(), want / want.max(), rtol=1e-9)
        gl = ls.component_curve(self.ke, "GL(30)", 1005.0, 1.3, 1.0)
        want = lor ** 0.3 * gau ** 0.7
        np.testing.assert_allclose(gl / gl.max(), want / want.max(), rtol=1e-9)

    def test_la_asymmetry_puts_the_tail_on_the_high_ke_side(self):
        y = ls.component_curve(self.ke, "LA(1.0,3.0,0)", 1005.0, 1.3, 1.0)
        peak = int(np.argmax(y))
        low = y[peak - 400]                       # 1 eV below the maximum
        high = y[peak + 400]
        self.assertGreater(low, high * 2)         # exponent a < b: heavier low side

    def test_symmetric_la_is_symmetric(self):
        y = ls.component_curve(self.ke, "LA(1.5,1.5,0)", 1005.0, 1.3, 1.0)
        np.testing.assert_allclose(y, y[::-1], atol=1e-3 * y.max())

    def test_shared_width_is_fwhm_for_an_unmodified_lorentzian(self):
        # a = b = 1 is the "no rescaling" baseline (GL/SGL and the 2-argument
        # LA(m)/LF(...) shorthand, which default a and b to 1): every such
        # already-working shape is untouched by the shared-width formula.
        self.assertAlmostEqual(ls._shared_width(1.3, 1.0, 1.0), 1.3, 9)

    def test_shared_width_matches_a_hand_computed_value(self):
        # F = 2*fwhm / (sqrt(2**(1/a)-1) + sqrt(2**(1/b)-1)), a=1.2, b=5
        import math
        want = 2 * 1.3 / (math.sqrt(2 ** (1 / 1.2) - 1)
                          + math.sqrt(2 ** (1 / 5.0) - 1))
        self.assertAlmostEqual(ls._shared_width(1.3, 1.2, 5.0), want, 9)
        self.assertAlmostEqual(want / 1.3, 1.575, 3)   # wider than fwhm

    def test_broadening_lowers_the_peak_and_keeps_the_area(self):
        sharp = ls.component_curve(self.ke, "LA(1.1,1.9,0)", 1005.0, 1.3, 1.0)
        soft = ls.component_curve(self.ke, "LA(1.1,1.9,7)", 1005.0, 1.3, 1.0)
        self.assertLess(soft.max(), sharp.max())
        self.assertAlmostEqual(self.area(soft), self.area(sharp), 3)

    def test_lf_tail_is_cut_off(self):
        y = ls.component_curve(self.ke, "LF(1.0,1.0,5,0)", 1005.0, 1.0, 1.0)
        self.assertEqual(float(y[0]), 0.0)         # beyond 5 FWHM: zero

    def test_degenerate_inputs_do_not_blow_up(self):
        y = ls.component_curve(self.ke, "GL(30)", 1005.0, 0.0, 10.0)
        self.assertTrue(np.isfinite(y).all())
        y = ls.component_curve(self.ke[:1].tolist() + [1001.0], "GL(30)",
                               1000.0, 1.0, 1.0)
        self.assertTrue(np.isfinite(y).all())

    def test_parse_shape(self):
        self.assertEqual(ls.parse_shape("GL(30)")["mix"], 30.0)
        p = ls.parse_shape("LA(1.1,1.9,7)")
        self.assertEqual((p["kind"], p["a"], p["b"], p["m"]),
                         ("LA", 1.1, 1.9, 7.0))
        self.assertEqual(ls.parse_shape("LA(50)")["m"], 50.0)
        p = ls.parse_shape("LF(1.1,1.2,75,200)")
        self.assertEqual((p["w"], p["m"]), (75.0, 200.0))
        self.assertEqual(ls.parse_shape("nonsense")["kind"], "GL")
        self.assertEqual(ls.parse_shape(None)["kind"], "GL")
        self.assertTrue(ls.is_exact("GL(30)") and ls.is_exact("SGL(50)"))
        self.assertFalse(ls.is_exact("LA(1,1,1)") or ls.is_exact("LF(1,1,1,1)"))

    def test_parse_shape_with_tail_suffix(self):
        """CasaXPS's GL/SGL tail suffix (GL(30)T(1.5)) must not corrupt the
        base shape's own mix -- the greedy single-regex parser used to
        swallow the whole "30)T(1.5" as an unparseable parameter list and
        silently fall back to mix=30 regardless of the real value."""
        p = ls.parse_shape("GL(30)T(1.5)")
        self.assertEqual((p["kind"], p["mix"], p["tail"]), ("GL", 30.0, True))
        p = ls.parse_shape("SGL(50)T(0.3)")
        self.assertEqual((p["kind"], p["mix"], p["tail"]),
                         ("SGL", 50.0, True))
        # A mix distinguishable from the old silent-fallback default (30).
        p = ls.parse_shape("GL(70)T(2)")
        self.assertEqual((p["mix"], p["tail"]), (70.0, True))
        self.assertFalse(ls.parse_shape("GL(30)")["tail"])
        self.assertFalse(ls.is_exact("GL(30)T(1.5)"))
        self.assertFalse(ls.is_exact("SGL(50)T(0.3)"))
        self.assertTrue(ls.is_exact("GL(30)"))


@unittest.skipUnless(HAVE_NP, "numpy not installed")
class TestBackgrounds(unittest.TestCase):
    def peak(self, n=201):
        x = np.linspace(0, 10, n)
        return 100 + 900 * np.exp(-((x - 5) / 0.8) ** 2)

    def test_shirley_runs_from_the_low_ke_end_to_the_high_ke_end(self):
        y = self.peak()
        y = y + np.linspace(50, 0, len(y))          # low-KE end higher
        b = ls.shirley(y)
        self.assertAlmostEqual(b[0], y[0], 6)
        self.assertAlmostEqual(b[-1], y[-1], 6)
        self.assertLessEqual(float(b.max()), float(y[0]) + 1e-9)

    def test_shirley_steps_where_the_peak_is(self):
        y = np.concatenate([np.full(50, 200.0), np.full(50, 100.0)])
        y[45:55] += 800                              # a peak on a step
        b = ls.shirley(y)
        self.assertGreater(b[10], b[90])
        self.assertAlmostEqual(b[0], 200.0, 6)
        self.assertAlmostEqual(b[-1], 100.0, 6)

    def test_shirley_of_flat_data_is_flat(self):
        b = ls.shirley(np.full(50, 7.0))
        np.testing.assert_allclose(b, 7.0)

    def test_end_averaging(self):
        y = np.array([0, 10, 10, 10, 10, 10, 10, 10, 10, 0], float)
        self.assertEqual(ls.linear_bg(y, avg=1)[0], 0.0)
        self.assertEqual(ls.linear_bg(y, avg=3)[0], 20 / 3)

    def test_linear(self):
        b = ls.linear_bg(np.array([10.0, 0.0, 0.0, 30.0]))
        np.testing.assert_allclose(b, [10, 16.6666667, 23.3333333, 30])

    def test_named_backgrounds(self):
        y = self.peak(50)
        self.assertEqual(len(ls.background("Shirley", y)), 50)
        self.assertEqual(len(ls.background("Linear", y)), 50)
        self.assertEqual(float(ls.background("None", y).sum()), 0.0)
        self.assertIsNone(ls.background("Tougaard", y))     # not reproduced
        self.assertIsNone(ls.background("U 3 Tougaard", y))
        self.assertEqual(len(ls.shirley(np.array([1.0, 2.0]))), 2)


# ------------------------------------------------------------------ parsing
class TestParse(unittest.TestCase):
    def test_a_real_looking_block(self):
        fit = casafit.parse(CASA)
        self.assertAlmostEqual(fit.calib_shift, 3.01, 6)
        self.assertEqual(len(fit.regions), 1)
        r = fit.regions[0]
        self.assertEqual((r.name, r.background), ("Ti 2p", "Shirley"))
        self.assertEqual((r.start_ke, r.end_ke), (1019.0251, 1034.8837))
        self.assertEqual((r.rsf, r.avg, r.mass), (2.001, 1, 47.8784))
        a, b = fit.components
        self.assertEqual((a.name, a.shape), ("Ti 2p3/2 Ti(IV)", "GL(30)"))
        self.assertEqual((a.area, a.fwhm, a.pos_ke), (3394.1269, 1.2737472,
                                                       1028.1128))
        self.assertEqual((a.rsf, a.index, a.region), (2.001, -1, "Ti 2p"))
        self.assertEqual((b.index, b.group), (3, "Ti(IV)"))
        self.assertEqual(b.pos_ke, 1022.3928)

    def test_no_fit_means_none(self):
        self.assertIsNone(casafit.parse([]))
        self.assertIsNone(casafit.parse(None))
        self.assertIsNone(casafit.parse(["Casa Info Follows", "0", "0", "0",
                                         "0", "X-ray spot-size: 400 um"]))
        self.assertIsNone(casafit.parse(["CASA region broken"]))

    def test_block_is_kept_verbatim_from_the_casa_header(self):
        fit = casafit.parse(["Etch level : 3"] + CASA)
        self.assertEqual(casafit.to_lines(fit), CASA[:-2])   # not the tail text
        self.assertEqual(casafit.to_lines(None), [])

    def test_several_regions_own_their_components(self):
        lines = ["CASA region (*A*) (*Linear*) 100 110 1 1 (*A*) 1",
                 "1",
                 "CASA comp (*a1*) (*GL(30)*) Area 5 0 9 -1 1 MFWHM 1 0 2 "
                 "-1 1 Position 105 0 0 -1 1 RSF 1 MASS 1 INDEX -1 (*A*)",
                 "CASA region (*B*) (*Shirley*) 200 210 1 1 (*B*) 1",
                 "1",
                 "CASA comp (*b1*) (*GL(30)*) Area 5 0 9 -1 1 MFWHM 1 0 2 "
                 "-1 1 Position 205 0 0 -1 1 RSF 1 MASS 1 INDEX -1 (*B*)"]
        fit = casafit.parse(lines)
        self.assertEqual([r.name for r in fit.regions], ["A", "B"])
        self.assertEqual([c.region for c in fit.components], ["A", "B"])
        self.assertEqual([c.name for c in fit.region_components(
            fit.regions[1])], ["b1"])

    def test_bad_component_lines_are_skipped(self):
        fit = casafit.parse(CASA[:9] + ["CASA comp (*x*) (*GL(30)*) nonsense"])
        self.assertEqual(len(fit.components), 0)

    def test_index_groups(self):
        fit = casafit.parse(CASA)
        a, b = fit.components
        self.assertNotEqual(fit.group_of(a), fit.group_of(b))
        self.assertEqual(fit.group_of(b), "i3")


# --------------------------------------------------------- reconstruction
def model_data(fit, hv, dwell, scans, n=241, lo_be=448.0, hi_be=470.0,
               descending=True, noise=0.0):
    """Data generated *from the fit itself* in the file's own frame: raw
    binding energies, counts = (background + components) x dwell x scans."""
    step = (hi_be - lo_be) / (n - 1)
    be = [hi_be - i * step for i in range(n)] if descending else \
        [lo_be + i * step for i in range(n)]
    ke_cal = np.array([hv - b - fit.calib_shift for b in be])
    reg = fit.regions[0]
    order = np.argsort(ke_cal)
    kk = ke_cal[order]
    inside = (kk >= reg.start_ke) & (kk <= reg.end_ke)
    total = np.zeros(len(kk))
    for c in fit.components:
        total += ls.component_curve(kk, c.shape, c.pos_ke, c.fwhm, c.area)
    cps = np.full(len(be), 200.0)
    base = np.zeros(len(kk))
    cps_sorted = 200.0 + total
    cps[order] = cps_sorted
    return be, (cps * dwell * scans).tolist()


@unittest.skipUnless(HAVE_NP, "numpy not installed")
class TestCurves(unittest.TestCase):
    def setUp(self):
        self.fit = casafit.parse(CASA)
        self.hv = 1486.71

    def test_components_sit_at_hv_minus_position_minus_shift(self):
        be, counts = model_data(self.fit, self.hv, 0.27, 25)
        cv = casafit.curves(self.fit, be, counts, self.hv, 0.27, 25)[0]
        comp, vals = cv.components[0]
        i = int(np.nanargmax(vals))
        want = self.hv - comp.pos_ke - self.fit.calib_shift        # raw BE
        self.assertAlmostEqual(be[i], want, delta=0.06)
        self.assertAlmostEqual(casafit.component_be(comp, self.hv),
                               self.hv - comp.pos_ke, 9)          # as Casa shows

    def test_without_the_calibration_offset_the_peak_would_be_elsewhere(self):
        be, counts = model_data(self.fit, self.hv, 0.27, 25)
        shifted = casafit.parse([l for l in CASA if not l.startswith("Calib")])
        cv = casafit.curves(shifted, be, counts, self.hv, 0.27, 25)[0]
        i = int(np.nanargmax(cv.components[0][1]))
        with_shift = casafit.curves(self.fit, be, counts, self.hv, 0.27, 25)[0]
        j = int(np.nanargmax(with_shift.components[0][1]))
        self.assertGreater(abs(be[i] - be[j]), 2.5)      # 3.01 eV apart

    def test_envelope_reproduces_data_made_from_the_same_model(self):
        be, counts = model_data(self.fit, self.hv, 0.27, 25)
        cv = casafit.curves(self.fit, be, counts, self.hv, 0.27, 25)[0]
        self.assertIsNotNone(cv.envelope)
        self.assertLess(cv.residual_rms, 0.05)         # within the Shirley model
        self.assertFalse(cv.approximate)                # GL is exact
        self.assertTrue(cv.scale_known)

    def test_envelope_never_exceeds_the_data_it_was_built_from(self):
        """Regression for the reported bug: a component's tail can run past
        its own CasaXPS region window (a broad or asymmetric peak commonly
        does -- a tight region box does not mean the instrument stopped
        recording there). The reconstructed envelope must not be inflated
        to compensate: CasaXPS's own rendering never rises above the raw
        data, and neither should ours."""
        reg = casafit.FitRegion(name="Wide", background="none",
                                start_ke=1025.0, end_ke=1029.0)
        comp = casafit.FitComponent(name="Wide", shape="GL(100)",
                                    area=6000.0, fwhm=4.0, pos_ke=1027.0,
                                    region="Wide")
        fit = casafit.Fit(regions=[reg], components=[comp])
        # the "true" data: the same component evaluated over a range much
        # wider than the CasaXPS region box, as the instrument would record
        be = np.linspace(self.hv - 1027.0 - 30, self.hv - 1027.0 + 30,
                         601).tolist()
        ke = np.array([self.hv - b for b in be])
        counts = ls.component_curve(ke, "GL(100)", 1027.0, 4.0, 6000.0)
        cv = casafit.curves(fit, be, counts.tolist(), self.hv, None, 1)[0]
        env = np.array(cv.envelope)
        keep = ~np.isnan(env)
        self.assertTrue(keep.any())
        diff = env[keep] - counts[keep]
        self.assertLessEqual(float(diff.max()), 1e-6 * float(counts.max()))

    def test_tail_modified_component_is_marked_approximate(self):
        """A GL/SGL component with a CasaXPS tail suffix reconstructs as its
        plain base shape (the tail itself is not modelled) but must be
        flagged approximate, not silently treated as exact."""
        reg = casafit.FitRegion(name="Tail", background="none",
                                start_ke=1025.0, end_ke=1029.0)
        comp = casafit.FitComponent(name="Tail", shape="GL(30)T(1.5)",
                                    area=6000.0, fwhm=4.0, pos_ke=1027.0,
                                    region="Tail")
        fit = casafit.Fit(regions=[reg], components=[comp])
        be = np.linspace(self.hv - 1027.0 - 10, self.hv - 1027.0 + 10,
                         201).tolist()
        ke = np.array([self.hv - b for b in be])
        counts = ls.component_curve(ke, "GL(30)", 1027.0, 4.0, 6000.0)
        cv = casafit.curves(fit, be, counts.tolist(), self.hv, None, 1)[0]
        self.assertTrue(cv.approximate)
        self.assertIsNotNone(cv.envelope)                # base shape drawn
        self.assertTrue(np.isfinite(np.array(cv.envelope)).any())

    def test_intensity_is_in_the_spectrums_own_counts(self):
        be, counts = model_data(self.fit, self.hv, 0.27, 25)
        a = casafit.curves(self.fit, be, counts, self.hv, 0.27, 25)[0]
        b = casafit.curves(self.fit, be, [c * 2 for c in counts], self.hv,
                           0.27, 25)[0]
        i = int(np.nanargmax(a.components[0][1]))
        # the same component drawn over twice-the-counts data keeps its size
        # (area is in counts/s: scaled by dwell x scans only)
        self.assertAlmostEqual(a.components[0][1][i], b.components[0][1][i], 6)
        peak_cps = a.components[0][1][i] / (0.27 * 25)
        self.assertAlmostEqual(peak_cps * 1.27374 * 1.0, 3394.1 * 1.0, delta=3394.1 * 0.5)

    def test_order_of_the_energy_axis_does_not_matter(self):
        be, counts = model_data(self.fit, self.hv, 0.27, 25, descending=True)
        d = casafit.curves(self.fit, be, counts, self.hv, 0.27, 25)[0]
        be2, counts2 = model_data(self.fit, self.hv, 0.27, 25,
                                  descending=False)
        a = casafit.curves(self.fit, be2, counts2, self.hv, 0.27, 25)[0]
        di = int(np.nanargmax(d.envelope))
        ai = int(np.nanargmax(a.envelope))
        self.assertAlmostEqual(be[di], be2[ai], delta=0.1)
        self.assertEqual(len(d.envelope), len(be))          # aligned with the points

    def test_nan_outside_the_fit_region(self):
        be, counts = model_data(self.fit, self.hv, 0.27, 25)
        cv = casafit.curves(self.fit, be, counts, self.hv, 0.27, 25)[0]
        env = np.array(cv.envelope)
        self.assertTrue(np.isnan(env).any() and (~np.isnan(env)).any())
        keep = ~np.isnan(env)
        ke = self.hv - np.array(be)[keep] - self.fit.calib_shift
        reg = self.fit.regions[0]
        self.assertTrue(((ke >= reg.start_ke - 1e-9)
                         & (ke <= reg.end_ke + 1e-9)).all())

    def test_missing_dwell_shows_counts_per_second_and_says_so(self):
        be, counts = model_data(self.fit, self.hv, 1.0, 1)
        cv = casafit.curves(self.fit, be, counts, self.hv, None, 1)[0]
        self.assertFalse(cv.scale_known)

    def test_nothing_reconstructed_without_the_needed_inputs(self):
        be, counts = model_data(self.fit, self.hv, 0.27, 25)
        self.assertEqual(casafit.curves(None, be, counts, self.hv), [])
        self.assertEqual(casafit.curves(self.fit, be, counts, None), [])
        self.assertEqual(casafit.curves(self.fit, [], [], self.hv), [])
        self.assertEqual(casafit.curves(self.fit, be[:2], counts[:2],
                                        self.hv), [])

    def test_a_shifted_axis_moves_the_fit_with_it(self):
        """The app's energy calibration moves the photon energy with the
        binding-energy axis: kinetic energies (where the fit lives) stay."""
        be, counts = model_data(self.fit, self.hv, 0.27, 25)
        shift = 0.8
        base = casafit.curves(self.fit, be, counts, self.hv, 0.27, 25)[0]
        moved = casafit.curves(self.fit, [b + shift for b in be], counts,
                               self.hv + shift, 0.27, 25)[0]
        np.testing.assert_allclose(np.nan_to_num(base.envelope),
                                   np.nan_to_num(moved.envelope))

    def test_linear_background_and_unknown_type(self):
        lines = [l.replace("(*Shirley*)", "(*Linear*)") for l in CASA]
        fit = casafit.parse(lines)
        be, counts = model_data(fit, self.hv, 0.27, 25)
        cv = casafit.curves(fit, be, counts, self.hv, 0.27, 25)[0]
        self.assertIsNotNone(cv.background)
        lines = [l.replace("(*Shirley*)", "(*Tougaard*)") for l in CASA]
        fit = casafit.parse(lines)
        cv = casafit.curves(fit, be, counts, self.hv, 0.27, 25)[0]
        self.assertIsNone(cv.background)
        self.assertFalse(cv.background_known)
        self.assertTrue(cv.components)            # components still drawn
        self.assertIsNone(cv.envelope)            # but no envelope on air


# ------------------------------------------------------ files and exports
def fitted_region(n=241):
    fit = casafit.parse(CASA)
    hv = 1486.71
    be, counts = model_data(fit, hv, 0.27, 25, n=n)
    r = Region(name="Ti 2p", index=0, offset=0, energy=be, counts=counts,
               decodable=True, sample="S", photon_energy=hv, dwell=0.27,
               pass_energy=20.0, step=0.1, count_units="counts",
               source="a.vms")
    r.extra["n_scans"] = 25
    r.fit = fit
    return r


@unittest.skipUnless(HAVE_NP, "numpy not installed")
class TestExports(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_vamas_round_trip_keeps_the_fit(self):
        r = fitted_region()
        path = os.path.join(self.dir, "x.vms")
        exporters.export_vamas([r], path)
        back = readers.load_file(path)
        b = back.regions[0]
        self.assertIsNotNone(b.fit)
        self.assertEqual(casafit.to_lines(b.fit), casafit.to_lines(r.fit))
        self.assertAlmostEqual(b.fit.calib_shift, 3.01, 6)
        self.assertEqual([(c.name, c.shape, c.area, c.pos_ke)
                          for c in b.fit.components],
                         [(c.name, c.shape, c.area, c.pos_ke)
                          for c in r.fit.components])
        with open(path, encoding="latin-1") as fh:
            self.assertIn("Casa Info Follows", fh.read())

    def test_curves_survive_the_round_trip(self):
        r = fitted_region()
        path = os.path.join(self.dir, "x.vms")
        exporters.export_vamas([r], path)
        b = readers.load_file(path).regions[0]
        a = casafit.curves(r.fit, r.energy, r.counts, r.photon_energy,
                           r.dwell, 25)[0]
        c = casafit.curves(b.fit, b.energy, b.counts, b.photon_energy,
                           b.dwell, b.extra["n_scans"])[0]
        np.testing.assert_allclose(np.nan_to_num(a.envelope),
                                   np.nan_to_num(c.envelope), rtol=1e-3,
                                   atol=1e-3 * max(1, np.nanmax(a.envelope)))

    def test_a_file_without_a_fit_has_none(self):
        r = fitted_region()
        r.fit = None
        path = os.path.join(self.dir, "y.vms")
        exporters.export_vamas([r], path)
        self.assertIsNone(readers.load_file(path).regions[0].fit)

    def test_csv_gets_background_components_and_envelope(self):
        r = fitted_region()
        path = os.path.join(self.dir, "x.csv")
        exporters.export_csv([r], path)
        with open(path, newline="") as fh:
            rows = list(csv.reader(fh))
        head = rows[0]
        self.assertEqual(len(head), 2 + 1 + 2 + 1)
        self.assertIn("S Ti 2p fit: background", head)
        self.assertIn("S Ti 2p fit: Ti 2p3/2 Ti(IV)", head)
        self.assertIn("S Ti 2p fit: envelope", head)
        env = [row[head.index("S Ti 2p fit: envelope")] for row in rows[1:]]
        self.assertIn("", env)                       # blank outside the region
        self.assertTrue(any(v != "" for v in env))
        self.assertEqual(len(rows) - 1, len(r.counts))

    def test_csv_without_fits_is_unchanged_and_can_opt_out(self):
        r = fitted_region()
        path = os.path.join(self.dir, "a.csv")
        exporters.export_csv([r], path, include_fits=False)
        with open(path, newline="") as fh:
            self.assertEqual(len(next(csv.reader(fh))), 2)
        r.fit = None
        exporters.export_csv([r], path)
        with open(path, newline="") as fh:
            self.assertEqual(len(next(csv.reader(fh))), 2)

    def test_metadata_mentions_the_fit(self):
        from readers import SpectrumFile
        f = SpectrumFile()
        f.path = "a.vms"
        f.regions = [fitted_region()]
        f._finish()
        md = f.region_metadata(f.regions[0])
        self.assertIn("2 component(s)", md["CasaXPS fit"])
        self.assertIn("Shirley", md["CasaXPS fit"])
        self.assertIn("+3.01", md["CasaXPS fit"])


# ---------------------------------------------------------------- real files
def _real(name):
    path = os.path.join(REAL_DIR, name)
    return path if os.path.isfile(path) else None


@unittest.skipUnless(HAVE_NP and _real("titanium fitting example.vms"),
                     "CasaXPS sample files not present")
class TestRealCasaFits(unittest.TestCase):
    """Fits made by CasaXPS itself, checked against their own data."""

    def load(self, name):
        return readers.load_file(_real(name))

    def curves_of(self, r):
        return casafit.curves(r.fit, r.energy, r.counts, r.photon_energy,
                              r.dwell, r.extra.get("n_scans", 1))

    def test_titanium_example(self):
        r = self.load("titanium fitting example.vms").regions[0]
        self.assertIsNotNone(r.fit)
        self.assertAlmostEqual(r.fit.calib_shift, 3.01, 6)
        self.assertEqual(len(r.fit.components), 8)
        cv = self.curves_of(r)[0]
        self.assertLess(cv.residual_rms, 0.08)
        # the strongest component sits on the data's strongest peak, in the
        # spectrum's own (uncalibrated) binding energy
        top = max(cv.components, key=lambda c: np.nanmax(c[1]))
        i = int(np.nanargmax(top[1]))
        j = int(np.argmax(r.counts))
        self.assertAlmostEqual(r.energy[i], r.energy[j], delta=0.3)
        # the same fit with no calibration offset is far worse
        bare = casafit.parse([l for l in r.fit.lines
                              if not l.startswith("Calib")])
        worse = casafit.curves(bare, r.energy, r.counts, r.photon_energy,
                               r.dwell, r.extra["n_scans"])[0]
        self.assertGreater(worse.residual_rms, 3 * cv.residual_rms)

    def test_every_fitted_spectrum_in_the_samples_is_reproduced(self):
        n = 0
        for name in sorted(os.listdir(REAL_DIR)):
            if not name.endswith(".vms"):
                continue
            for r in readers.load_file(os.path.join(REAL_DIR, name)).regions:
                if r.fit is None or not r.fit.components:
                    continue
                for cv in self.curves_of(r):
                    n += 1
                    self.assertLess(cv.residual_rms, 0.10, f"{name} {cv.region}")
        self.assertGreaterEqual(n, 1)

    def test_depth_profile_blocks_carry_their_own_fit(self):
        path = _real("Titanium Metal Depth Profile - INSTRUCTORS.vms")
        if not path:
            self.skipTest("depth profile sample not present")
        f = readers.load_file(path)
        fitted = [i for i, r in enumerate(f.regions) if r.fit is not None]
        self.assertGreaterEqual(len(fitted), 2)
        counts = {len(f.regions[i].fit.components) for i in fitted}
        self.assertGreater(len(counts), 1)              # each block its own fit
        groups = {c.group for c in f.regions[fitted[0]].fit.components
                  if c.index >= 0}
        self.assertTrue(groups)                          # INDEX groups read

    def test_real_fit_survives_an_export_and_reread(self):
        f = self.load("titanium fitting example.vms")
        r = f.regions[0]
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        path = os.path.join(d, "t.vms")
        exporters.export_vamas([r], path)
        b = readers.load_file(path).regions[0]
        self.assertEqual(casafit.to_lines(b.fit), casafit.to_lines(r.fit))
        a = self.curves_of(r)[0]
        c = self.curves_of(b)[0]
        self.assertAlmostEqual(a.residual_rms, c.residual_rms, 3)


GK_DIR = os.environ.get("XPS_ASYM_DIR", os.path.join(
    os.path.expanduser("~"), "Downloads", "For GK"))


def _max_overshoot_pct(cv, counts):
    """How far the reconstructed envelope rises above the raw data, as a
    percentage of the region's peak height (0 if it never does)."""
    env = np.array(cv.envelope, dtype=float)
    data = np.array(counts, dtype=float)
    keep = ~np.isnan(env)
    if not keep.any():
        return 0.0
    over = float((env[keep] - data[keep]).max())
    peak = float(data[keep].max())
    return 100.0 * over / peak if peak > 0 else 0.0


@unittest.skipUnless(HAVE_NP, "numpy not installed")
class TestLAAsymmetryAccuracy(unittest.TestCase):
    """Canary for the LA/LF asymmetric-kernel limitation documented in
    ``lineshapes.py``: even with the shared-width fix (``_shared_width``),
    the reconstructed peak height for a strongly asymmetric exponent pair
    (e.g. ``LA(1.2,5,8)``, CasaXPS's sharp metallic-tail cutoff) can still
    run somewhat ahead of the raw data, which ``residual_rms`` (a
    whole-curve average) does not show -- confirmed on the real titanium and
    vanadium examples. This does NOT assert the gap is zero (the shared
    Gaussian-broadening scale, ``GAUSS_K``, is still an open question -- see
    the module docstring) -- only that it does not get worse than what real
    files currently show, so a future change to ``component_curve`` is
    caught even though it passes ``residual_rms``. Skipped entirely when
    neither reference directory is on this machine."""

    CEILING = 12.0   # % of peak height; titanium's ~8.8% is the worst seen

    def _regions(self):
        for d in (REAL_DIR, GK_DIR):
            if not os.path.isdir(d):
                continue
            for name in sorted(os.listdir(d)):
                if not name.endswith(".vms"):
                    continue
                try:
                    doc = readers.load_file(os.path.join(d, name))
                except Exception:
                    continue
                for r in doc.regions:
                    if r.fit is None or not r.fit.components:
                        continue
                    if any(ls.parse_shape(c.shape)["kind"] in ("LA", "LF")
                          for c in r.fit.components):
                        yield name, r

    def test_la_lf_overshoot_does_not_get_worse(self):
        n = 0
        for name, r in self._regions():
            for cv in casafit.curves(r.fit, r.energy, r.counts,
                                     r.photon_energy, r.dwell,
                                     r.extra.get("n_scans", 1)):
                if cv.envelope is None:
                    continue
                n += 1
                pct = _max_overshoot_pct(cv, r.counts)
                self.assertLess(pct, self.CEILING,
                                f"{name} {cv.region}: {pct:.1f}% of peak")
        if n == 0:
            self.skipTest("no real LA/LF-fitted spectrum found on this "
                          "machine")


if __name__ == "__main__":
    unittest.main()
