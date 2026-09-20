"""The charge correction CasaXPS records in a VAMAS block (``Calib M = .. A = ..``)
and what depends on it: which frame the stored fit positions are in (the
``Regions`` / ``Comps`` flags), the correction carried to the display, its
inheritance within a sample, the round trip through our own VAMAS export, and
the two-parameter universal Tougaard background.

Run:  python -m unittest discover tests
"""

import dataclasses
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import annotations as an  # noqa: E402
import calibration  # noqa: E402
import casafit  # noqa: E402
import exporters  # noqa: E402
import lineshapes as ls  # noqa: E402
import readers  # noqa: E402
from readers import Region  # noqa: E402
from test_casafit import CASA, fitted_region, model_data  # noqa: E402

try:
    import numpy as np
    HAVE_NP = True
except Exception:
    HAVE_NP = False

HV = 1486.71


# ------------------------------------------------------------- the Calib line
class TestCalibrationLine(unittest.TestCase):
    def test_plain_line(self):
        c = casafit.calibration(["Calib M = 281.7289 A = 282 BE ADD"])
        self.assertAlmostEqual(c.shift, 0.2711, 6)
        self.assertAlmostEqual(c.measured, 281.7289, 6)
        self.assertAlmostEqual(c.assigned, 282.0, 6)
        self.assertAlmostEqual(c.region_shift, 0.2711, 6)
        self.assertAlmostEqual(c.comp_shift, 0.2711, 6)

    def test_regions_and_comps_flags_mean_the_raw_frame(self):
        c = casafit.calibration(
            ["Calib M = 281.88 A = 284.8 Regions Comps BE ADD"])
        self.assertAlmostEqual(c.shift, 2.92, 6)
        self.assertEqual(c.region_shift, 0.0)
        self.assertEqual(c.comp_shift, 0.0)

    def test_each_flag_counts_on_its_own(self):
        c = casafit.calibration(["Calib M = 1 A = 3 Regions BE ADD"])
        self.assertEqual(c.region_shift, 0.0)
        self.assertAlmostEqual(c.comp_shift, 2.0, 6)

    def test_shorter_endings_still_parse(self):
        for tail in ("BE", "ADD", ""):
            c = casafit.calibration([f"Calib M = 282.74 A = 284.8 {tail}"])
            self.assertAlmostEqual(c.shift, 2.06, 6, tail)

    def test_lines_add_up_and_the_flag_belongs_to_its_line(self):
        c = casafit.calibration([
            "Calib M = 10 A = 11 BE ADD",
            "Calib M = 20 A = 22 Regions Comps BE ADD"])
        self.assertAlmostEqual(c.shift, 3.0, 6)
        self.assertAlmostEqual(c.region_shift, 1.0, 6)   # only the first
        self.assertAlmostEqual(c.measured, 10.0, 6)
        self.assertAlmostEqual(c.assigned, 13.0, 6)

    def test_none_without_a_line(self):
        self.assertIsNone(casafit.calibration(["Casa Info Follows", "0"]))
        self.assertIsNone(casafit.calibration([]))
        self.assertIsNone(casafit.calibration(None))

    def test_a_block_without_a_fit_still_has_it(self):
        lines = ["Casa Info Follows", "1", "Calib M = 1 A = 2 BE ADD", "0"]
        self.assertIsNone(casafit.parse(lines))
        self.assertAlmostEqual(casafit.calibration(lines).shift, 1.0, 6)

    def test_the_fit_carries_the_frames(self):
        lines = [l.replace("BE ADD", "Regions Comps BE ADD") for l in CASA]
        fit = casafit.parse(lines)
        self.assertAlmostEqual(fit.calib_shift, 3.01, 6)
        self.assertEqual(fit.shift_of_regions(), 0.0)
        self.assertEqual(fit.shift_of_comps(), 0.0)
        plain = casafit.parse(CASA)
        self.assertAlmostEqual(plain.shift_of_regions(), 3.01, 6)
        self.assertAlmostEqual(plain.shift_of_comps(), 3.01, 6)
        self.assertEqual(casafit.to_lines(fit), lines[:len(
            casafit.to_lines(fit))])                   # written back verbatim

    def test_calib_line_writer_reads_back_in_the_raw_frame(self):
        c = casafit.calibration([casafit.calib_line(281.88, 284.8)])
        self.assertAlmostEqual(c.shift, 2.92, 6)
        self.assertEqual((c.region_shift, c.comp_shift), (0.0, 0.0))


# ---------------------------------------------------------------- the frames
@unittest.skipUnless(HAVE_NP, "numpy not installed")
class TestFrames(unittest.TestCase):
    def test_a_raw_frame_fit_draws_the_same_curves(self):
        """The same fit stored with the Regions/Comps flags (positions in
        raw KE) and without (calibrated KE) reconstructs identically."""
        fit = casafit.parse(CASA)
        s = fit.calib_shift
        raw = dataclasses.replace(
            fit, region_shift=0.0, comp_shift=0.0,
            regions=[dataclasses.replace(g, start_ke=g.start_ke + s,
                                         end_ke=g.end_ke + s)
                     for g in fit.regions],
            components=[dataclasses.replace(c, pos_ke=c.pos_ke + s)
                        for c in fit.components])
        be, counts = model_data(fit, HV, 0.27, 25)
        a = casafit.curves(fit, be, counts, HV, 0.27, 25)[0]
        b = casafit.curves(raw, be, counts, HV, 0.27, 25)[0]
        np.testing.assert_allclose(np.nan_to_num(a.envelope),
                                   np.nan_to_num(b.envelope), atol=1e-9)
        self.assertLess(a.residual_rms, 0.01)

    def test_reading_a_raw_frame_fit_as_calibrated_misplaces_it(self):
        """What the old code did with the Regions/Comps flags: the fit lands
        ``calib_shift`` eV away from the data."""
        fit = casafit.parse(CASA)
        s = fit.calib_shift
        raw = dataclasses.replace(
            fit, region_shift=0.0, comp_shift=0.0,
            regions=[dataclasses.replace(g, start_ke=g.start_ke + s,
                                         end_ke=g.end_ke + s)
                     for g in fit.regions],
            components=[dataclasses.replace(c, pos_ke=c.pos_ke + s)
                        for c in fit.components])
        be, counts = model_data(fit, HV, 0.27, 25)
        wrong = dataclasses.replace(raw, region_shift=None, comp_shift=None)
        cv = casafit.curves(wrong, be, counts, HV, 0.27, 25)[0]
        self.assertGreater(cv.residual_rms, 0.05)

    def test_component_binding_energy_is_the_calibrated_one(self):
        fit = casafit.parse(CASA)
        comp = fit.components[0]
        self.assertAlmostEqual(casafit.component_be(comp, HV),
                               HV - comp.pos_ke, 9)
        raw = dataclasses.replace(fit, comp_shift=0.0)
        self.assertAlmostEqual(casafit.component_be(comp, HV, raw),
                               HV - comp.pos_ke + fit.calib_shift, 9)


@unittest.skipUnless(HAVE_NP, "numpy not installed")
class TestOverlappingRegions(unittest.TestCase):
    def reg(self, name, a, b):
        return casafit.FitRegion(name=name, start_ke=a, end_ke=b)

    def test_only_the_widest_of_overlapping_same_name_regions(self):
        narrow, wide = self.reg("C 1s", 10, 20), self.reg("C 1s", 8, 24)
        self.assertEqual(casafit.distinct_regions([narrow, wide]), [wide])
        self.assertEqual(casafit.distinct_regions([wide, narrow]), [wide])

    def test_different_names_or_apart_are_all_kept(self):
        a, b = self.reg("C 1s", 10, 20), self.reg("O 1s", 12, 18)
        c, d = self.reg("C 1s", 30, 40), self.reg("C 1s", 50, 60)
        self.assertEqual(casafit.distinct_regions([a, b]), [a, b])
        self.assertEqual(casafit.distinct_regions([a, c, d]), [a, c, d])

    def test_curves_draw_one_envelope_for_a_duplicated_region(self):
        lines = list(CASA)
        i = next(k for k, l in enumerate(lines) if l.startswith("CASA region"))
        wide = lines[i].replace("1019.0251", "1017.0251").replace(
            "1034.8837", "1036.8837")
        lines[i:i + 1] = [lines[i], wide]
        lines[i - 1] = "2"                       # the region count line
        fit = casafit.parse(lines)
        self.assertEqual(len(fit.regions), 2)
        be, counts = model_data(fit, HV, 0.27, 25)
        self.assertEqual(len(casafit.curves(fit, be, counts, HV, 0.27, 25)), 1)


# ----------------------------------------------------------------- Tougaard
@unittest.skipUnless(HAVE_NP, "numpy not installed")
class TestTougaard(unittest.TestCase):
    x = np.linspace(1000.0, 1030.0, 301)

    def peak(self, height=100.0, base=20.0):
        return base + height * np.exp(-0.5 * ((self.x - 1015.0) / 1.2) ** 2)

    def test_flat_data_give_a_flat_background(self):
        y = np.full(len(self.x), 37.0)
        np.testing.assert_allclose(ls.tougaard_u2(self.x, y, 2000.0, 650.0, 6),
                                   37.0)

    def test_starts_at_the_high_ke_level_and_rises_below_the_peak(self):
        y = self.peak()
        bg = ls.tougaard_u2(self.x, y, 2000.0, 650.0, 6)
        self.assertAlmostEqual(bg[-1], y[-6:].mean(), 6)
        self.assertGreater(bg[0], bg[-1])          # low-KE side sits higher
        self.assertTrue(np.all(bg >= y[-6:].mean() - 1e-9))
        self.assertGreater(bg[:150].max(), bg[-1] + 1.0)

    def test_the_rise_is_proportional_to_B(self):
        y = self.peak()
        b1 = ls.tougaard_u2(self.x, y, 1000.0, 650.0, 6)
        b2 = ls.tougaard_u2(self.x, y, 2000.0, 650.0, 6)
        np.testing.assert_allclose(b2 - b2[-1], 2 * (b1 - b1[-1]),
                                   atol=1e-9)

    def test_background_routes_the_region_line_numbers(self):
        y = self.peak()
        params = (0.0, 0.0, 2000.0, -650.0, 0.0, 0.0)
        got = ls.background("U 2 Tougaard", y, 6, x=self.x, params=params)
        np.testing.assert_allclose(
            got, ls.tougaard_u2(self.x, y, 2000.0, 650.0, 6))
        self.assertIsNone(ls.background("U 2 Tougaard", y, 6))   # no x
        self.assertIsNone(ls.background("U 3 Tougaard", y, 6, x=self.x,
                                        params=params))

    def test_the_region_line_is_parsed_and_reconstructed(self):
        lines = [
            "Casa Info Follows", "1", "Calib M = 281.7289 A = 282 BE ADD",
            "0", "1",
            "CASA region (*C 1s*) (*U 2 Tougaard*) 8958.7242 8973.2348 1 6 0 "
            "0 1788.5478 -650 0 0 (*C 1s*) 12.011 0 1",
            "1",
            "CASA comp (*AdC*) (*GL(30)*) Area 114.08312 1e-020 23910.791 -1 "
            "1 MFWHM 1.8107113 0.36 9 -1 1 Position 8966.3888 8963.8533 "
            "8974.5627 -1 1 RSF 1 MASS 12.011 INDEX -1 (*C 1s*)"]
        fit = casafit.parse(lines)
        reg = fit.regions[0]
        self.assertEqual(reg.avg, 6)
        self.assertEqual(reg.params[2:4], (1788.5478, -650.0))
        hv = 9251.74
        ke = np.arange(8950.0, 8980.0, 0.1)
        be = (hv - ke)[::-1] - fit.calib_shift          # raw BE, descending
        y = (15.0 + 40.0 * np.exp(-0.5 * (((hv - be) - 8966.66) / 0.8) ** 2))
        cv = casafit.curves(fit, be.tolist(), (y * 0.286 * 25).tolist(), hv,
                            0.286, 25)[0]
        self.assertTrue(cv.background_known)
        self.assertIsNotNone(cv.envelope)
        ok = ~np.isnan(np.array(cv.background))
        self.assertGreater(ok.sum(), 100)


# --------------------------------------------- the file's shift on the region
def vregion(name="C 1s", sample="S", shift=0.0, measured=None, assigned=None,
            fit=False):
    r = fitted_region() if fit else Region(
        name=name, index=0, offset=0, decodable=True, sample=sample,
        photon_energy=HV, dwell=0.27, pass_energy=20.0, step=0.1,
        count_units="counts", source="a.vms",
        energy=[290.0 - 0.1 * i for i in range(101)],
        counts=[100.0 + (i % 7) for i in range(101)])
    r.name, r.sample = name, sample
    r.extra["n_scans"] = 25
    if shift:
        r.calibration_shift = shift
        r.extra["casa_calib"] = {
            "measured": measured, "assigned": assigned, "shift": shift,
            "inherited": False}
    return r


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def roundtrip(self, regions, name="x.vms", edit=None):
        path = os.path.join(self.dir, name)
        exporters.export_vamas(regions, path)
        if edit:
            with open(path, encoding="latin-1") as fh:
                text = fh.read()
            with open(path, "w", encoding="latin-1", newline="") as fh:
                fh.write(edit(text))
        return readers.load_file(path).regions


class TestReaderCalibration(Base):
    def test_a_block_keeps_its_own_correction_without_a_fit(self):
        got = self.roundtrip([vregion(shift=2.92, measured=281.88,
                                      assigned=284.8)])
        self.assertAlmostEqual(got[0].calibration_shift, 2.92, 6)
        cc = got[0].extra["casa_calib"]
        self.assertFalse(cc["inherited"])
        self.assertAlmostEqual(cc["measured"], 281.88, 6)

    def test_blocks_without_a_line_inherit_the_samples_correction(self):
        got = self.roundtrip([
            vregion("V 2p", shift=2.92, measured=281.88, assigned=284.8),
            vregion("C 1s", shift=2.92, measured=281.88, assigned=284.8),
            vregion("Survey")])
        self.assertAlmostEqual(got[2].calibration_shift, 2.92, 6)
        self.assertTrue(got[2].extra["casa_calib"]["inherited"])
        self.assertIn("BE calibration (CasaXPS)", readers.SpectrumFile
                      .region_metadata(self._file(got), got[2]))

    def _file(self, regions):
        from readers import SpectrumFile
        f = SpectrumFile()
        f.path = "a.vms"
        f.regions = regions
        f._finish()
        return f

    def test_another_sample_does_not_inherit(self):
        got = self.roundtrip([
            vregion("C 1s", "A", shift=2.92, measured=281.88, assigned=284.8),
            vregion("C 1s", "B")])
        self.assertAlmostEqual(got[0].calibration_shift, 2.92, 6)
        self.assertEqual(got[1].calibration_shift, 0.0)
        self.assertNotIn("casa_calib", got[1].extra)

    def test_disagreeing_corrections_are_not_shared(self):
        """Depth-profile levels are each calibrated on their own; a block
        with no line stays as measured rather than guessing a level."""
        got = self.roundtrip([
            vregion("C 1s", shift=2.92, measured=281.88, assigned=284.8),
            vregion("C 1s", shift=1.0, measured=283.8, assigned=284.8),
            vregion("O 1s")])
        self.assertAlmostEqual(got[0].calibration_shift, 2.92, 6)
        self.assertAlmostEqual(got[1].calibration_shift, 1.0, 6)
        self.assertEqual(got[2].calibration_shift, 0.0)

    def test_a_kinetic_energy_region_is_not_shifted(self):
        got = self.roundtrip(
            [vregion("Cu LMM", shift=2.92, measured=281.88, assigned=284.8)],
            edit=lambda t: t.replace("\nXPS\n", "\nAES\n"))
        self.assertIn("kinetic", got[0].energy_label.lower())
        self.assertEqual(got[0].calibration_shift, 0.0)
        self.assertIn("casa_calib", got[0].extra)      # still recorded

    def test_a_fit_in_raw_frame_stays_aligned_with_its_spectrum(self):
        """A block whose own correction carries the Regions/Comps flags
        keeps its fit where the data are, however the axis is displayed."""
        r = fitted_region()
        fit = r.fit
        lines = [l.replace("BE ADD", "Regions Comps BE ADD") for l in CASA]
        s = fit.calib_shift
        raw = casafit.parse(lines)
        raw = dataclasses.replace(
            raw, regions=[dataclasses.replace(g, start_ke=g.start_ke + s,
                                              end_ke=g.end_ke + s)
                          for g in raw.regions],
            components=[dataclasses.replace(c, pos_ke=c.pos_ke + s)
                        for c in raw.components])
        r.fit = raw
        cv = casafit.curves(raw, r.energy, r.counts, r.photon_energy,
                            r.dwell, 25)[0]
        self.assertLess(cv.residual_rms, 0.01)


# ------------------------------------------- shift precedence and the export
class TestShiftPrecedence(unittest.TestCase):
    def test_default_applies_until_the_user_sets_one(self):
        a = an.Annotations()
        self.assertAlmostEqual(a.shift_for("f1", "S", "C 1s", 0.27), 0.27)
        self.assertIsNone(a.shift_for("f1", "S", "C 1s", None))
        a.set_shift(an.sample_key("f1", "S"), 0.5)
        self.assertAlmostEqual(a.shift_for("f1", "S", "C 1s", 0.27), 0.5)
        self.assertEqual(a.shift_for("f1", "S", "C 1s"), 0.5)
        self.assertEqual(a.shift_for("f2", "S", "C 1s"), 0.0)

    def test_metadata_shows_the_file_correction_as_the_shift(self):
        a = an.Annotations()
        r = vregion(shift=0.2711, measured=281.7289, assigned=282.0)
        out = a.apply_metadata("f1", 0, r, {"Sample": "S", "Region": "C 1s"})
        self.assertEqual(out["BE shift (eV)"], "+0.271")
        a.set_shift(an.sample_key("f1", "S"), -0.4)
        out = a.apply_metadata("f1", 0, r, {"Sample": "S", "Region": "C 1s"})
        self.assertEqual(out["BE shift (eV)"], "-0.400")


def display_copy(r, total):
    """What ``Workspace._display`` makes of a region for a total shift."""
    import copy
    q = copy.copy(r)
    q.energy = [e + total for e in r.energy]
    q.photon_energy = r.photon_energy + total
    q.shift_applied = total
    return q


class TestExportRoundTrip(Base):
    def total_after(self, back, user=None):
        """The shift the app would apply to a re-read region."""
        a = an.Annotations()
        if user is not None:
            a.set_shift(an.sample_key("f1", back.sample), user)
        return a.shift_for("f1", back.sample, back.name,
                           back.calibration_shift)

    def test_the_file_correction_is_not_applied_twice(self):
        r = vregion(shift=0.2711, measured=281.7289, assigned=282.0)
        back = self.roundtrip([display_copy(r, 0.2711)])[0]
        self.assertAlmostEqual(back.calibration_shift, 0.2711, 6)
        # the axis holds the raw energies, the Calib line the correction
        for got, want in zip(back.energy, r.energy):
            self.assertAlmostEqual(got, want, 6)
        self.assertAlmostEqual(self.total_after(back), 0.2711, 6)

    def test_a_user_shift_on_top_survives(self):
        r = vregion(shift=0.2711, measured=281.7289, assigned=282.0)
        back = self.roundtrip([display_copy(r, -0.4)])[0]      # user: -0.4
        self.assertAlmostEqual(back.calibration_shift, 0.2711, 6)
        shown = [e + 0.2711 for e in back.energy]   # read energy + Calib
        for got, want in zip(shown, r.energy):
            self.assertAlmostEqual(got, want - 0.4 + 0.0, 6)

    def test_a_raw_export_keeps_the_axis_and_the_line(self):
        r = vregion(shift=0.2711, measured=281.7289, assigned=282.0)
        back = self.roundtrip([r])[0]
        self.assertAlmostEqual(back.calibration_shift, 0.2711, 6)
        for got, want in zip(back.energy, r.energy):
            self.assertAlmostEqual(got, want, 6)

    def test_no_correction_no_line(self):
        r = vregion()
        path = os.path.join(self.dir, "n.vms")
        exporters.export_vamas([display_copy(r, 0.3)], path)
        with open(path, encoding="latin-1") as fh:
            self.assertNotIn("Calib", fh.read())
        back = readers.load_file(path).regions[0]
        self.assertEqual(back.calibration_shift, 0.0)
        for got, want in zip(back.energy, r.energy):
            self.assertAlmostEqual(got, want + 0.3, 6)

    def test_a_fitted_block_keeps_its_own_line_only_once(self):
        r = fitted_region()
        r.calibration_shift = 3.01
        r.extra["casa_calib"] = {"measured": 455.59, "assigned": 458.6,
                                 "shift": 3.01, "inherited": False}
        path = os.path.join(self.dir, "f.vms")
        exporters.export_vamas([display_copy(r, 3.01)], path)
        with open(path, encoding="latin-1") as fh:
            self.assertEqual(fh.read().count("Calib M"), 1)
        back = readers.load_file(path).regions[0]
        self.assertAlmostEqual(back.calibration_shift, 3.01, 6)
        for got, want in zip(back.energy, r.energy):
            self.assertAlmostEqual(got, want, 6)


# ---------------------------------------------------------------- statement
class TestStatement(unittest.TestCase):
    def test_one_sentence_per_sample(self):
        text = calibration.casa_statement([
            ("HAXPES", 281.7289, 282.0), ("HAXPES", 281.7289, 282.0),
            ("XPS", 280.8149, 282.0)])
        self.assertEqual(text.count("CasaXPS"), 2)
        self.assertIn("HAXPES", text)
        self.assertIn("+0.27 eV", text)
        self.assertIn("+1.19 eV", text)
        self.assertIn("281.73", text)

    def test_a_sample_with_several_corrections_gets_a_range(self):
        text = calibration.casa_statement([("Ti", 285.1, 284.8),
                                           ("Ti", 284.5, 284.8)])
        self.assertIn("-0.30 to +0.30 eV", text)

    def test_nothing_to_say(self):
        self.assertEqual(calibration.casa_statement([]), "")


# ------------------------------------------------------------------ legend
try:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure
    import plots
    HAVE_MPL = True
except Exception:
    HAVE_MPL = False


@unittest.skipUnless(HAVE_NP and HAVE_MPL, "numpy / matplotlib not installed")
class TestFitLegend(unittest.TestCase):
    def labels(self, lines):
        fit = casafit.parse(lines)
        be, counts = model_data(fit, HV, 0.27, 25)
        cvs = casafit.curves(fit, be, counts, HV, 0.27, 25)
        ax = Figure().add_subplot()
        plots.draw_fit(ax, be, {"curves": cvs, "colours": ["#aa0000"],
                                "show": {"components": True}}, 1.0, "grey",
                       "red")
        return [t.get_text() for t in ax.get_legend().get_texts()]

    def test_a_named_group_labels_its_components(self):
        self.assertEqual(self.labels(CASA), ["Ti 2p3/2 Ti(IV)", "Ti(IV)"])

    def test_a_group_tagged_with_the_region_name_uses_the_component(self):
        lines = [l.replace("INDEX 3 (*Ti(IV)*)", "INDEX 3 (*Ti 2p*)")
                 for l in CASA]
        self.assertEqual(self.labels(lines),
                         ["Ti 2p3/2 Ti(IV)", "Ti 2p1/2 Ti(IV)"])


# ------------------------------------------------------- real CasaXPS files
@unittest.skipUnless(HAVE_NP, "numpy not installed")
class TestRealFiles(unittest.TestCase):
    """Set XPS_CASA_TOUGAARD to a CasaXPS VAMAS file with U 2 Tougaard fits
    and XPS_CASA_RAWFRAME to one saved with ``Regions Comps`` calibrations."""

    def rms(self, path):
        d = readers.load_file(path)
        out = []
        for r in d.regions:
            if not r.fit or not r.fit.components:
                continue
            for c in casafit.curves(r.fit, r.energy, r.counts,
                                    r.photon_energy, r.dwell,
                                    r.extra.get("n_scans", 1)):
                if c.residual_rms is not None:
                    out.append((r.sample, r.name, c.residual_rms))
        return d, out

    def test_tougaard_fits_reproduce(self):
        path = os.environ.get("XPS_CASA_TOUGAARD")
        if not path or not os.path.exists(path):
            self.skipTest("XPS_CASA_TOUGAARD not set")
        _d, rows = self.rms(path)
        self.assertTrue(rows)
        for sample, name, rms in rows:
            self.assertLess(rms, 0.06, f"{sample} {name}")

    def test_raw_frame_fits_reproduce(self):
        path = os.environ.get("XPS_CASA_RAWFRAME")
        if not path or not os.path.exists(path):
            self.skipTest("XPS_CASA_RAWFRAME not set")
        d, rows = self.rms(path)
        self.assertTrue(rows)
        for sample, name, rms in rows:
            self.assertLess(rms, 0.06, f"{sample} {name}")
        self.assertTrue(all(r.calibration_shift for r in d.regions
                            if r.extra.get("casa_calib")))


if __name__ == "__main__":
    unittest.main()
