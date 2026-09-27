"""KherveFitting .kfit reader: sheet-name splitting, shape-string mapping,
and (when h5py and the real sample corpus are available) real files.

Run:  python -m unittest discover tests
"""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import casafit  # noqa: E402
import readers  # noqa: E402
from readers import khervefitting_kfit as kf  # noqa: E402

try:
    import h5py  # noqa: F401
    HAVE_H5PY = True
except ImportError:
    HAVE_H5PY = False

CORPUS = os.environ.get("XPS_KFIT_DIR", os.path.join(
    "D:\\", "Temp", "for claude files", "temp", "KherveFitting Files",
    "Data-Examples"))

REAL_FILES = [
    os.path.join("1s B-C ... Mg", "06 - C - Carbon", "SP2 Carbon.kfit"),
    os.path.join("2p Al ... Zn", "13 - Al _Aluminium", "Al2O3.kfit"),
    os.path.join("2p Al ... Zn", "16 - S - Sulphur", "BaSO4.kfit"),
    os.path.join("2p Al ... Zn", "25 - Mn - Manganese", "Mn2O3.kfit"),
    os.path.join("2p Al ... Zn", "26 - Fe - Iron", "Fe2O3.kfit"),
    os.path.join("3d Ge ... Nd", "38 - Sr - Strontium", "STO.kfit"),
    os.path.join("3d Ge ... Nd", "38 - Sr - Strontium", "STO_Tilt.kfit"),
    os.path.join("3d Ge ... Nd", "39 - Y - Yttrium", "Y2O3_Kfitting.kfit"),
    os.path.join("zz Metals", "Metal Bi", "Metal_Bi.kfit"),
    os.path.join("zz Other Techniques", "Voigt Models", "Voigt_Model.kfit"),
]


def _real(rel):
    path = os.path.join(CORPUS, rel)
    return path if os.path.isfile(path) else None


class TestSniff(unittest.TestCase):
    def test_hdf5_signature_is_recognised(self):
        self.assertTrue(kf.sniff(b"\x89HDF\r\n\x1a\n\x00\x00", ".kfit"))
        self.assertTrue(kf.sniff(b"\x89HDF\r\n\x1a\n\x00\x00", ""))

    def test_other_content_is_not(self):
        self.assertFalse(kf.sniff(b"not hdf5 at all", ".kfit"))
        self.assertFalse(kf.sniff(b"", ".kfit"))


class TestSplitSheetName(unittest.TestCase):
    def test_plain_core_level_is_row_zero(self):
        self.assertEqual(kf._split_sheet_name("Fe2p"), ("Fe 2p", 0))
        self.assertEqual(kf._split_sheet_name("C1s"), ("C 1s", 0))

    def test_trailing_row_digit_is_stripped(self):
        self.assertEqual(kf._split_sheet_name("Fe2p1"), ("Fe 2p", 1))
        self.assertEqual(kf._split_sheet_name("Fe2p2"), ("Fe 2p", 2))
        self.assertEqual(kf._split_sheet_name("C1s4"), ("C 1s", 4))

    def test_survey_with_a_row_suffix(self):
        self.assertEqual(kf._split_sheet_name("Survey"), ("Survey", 0))
        self.assertEqual(kf._split_sheet_name("Survey1"), ("Survey", 1))
        self.assertEqual(kf._split_sheet_name("Survey2"), ("Survey", 2))

    def test_names_that_do_not_match_are_left_alone(self):
        # a real example from Metal_Bi.kfit: no element/orbital pattern to
        # recognise, trailing digits are not a sample-row suffix here
        self.assertEqual(kf._split_sheet_name("N00575~04"), ("N00575~04", 0))


class TestShapeString(unittest.TestCase):
    def test_gl_sgl_use_the_lg_fraction(self):
        self.assertEqual(kf._shape_string(
            {"Fitting Model": "GL (Area)", "L/G": 44.0}), "GL(44)")
        self.assertEqual(kf._shape_string(
            {"Fitting Model": "SGL (Area)", "L/G": 24.86}), "SGL(24.86)")

    def test_voigt_uses_the_lg_fraction_too(self):
        self.assertEqual(kf._shape_string(
            {"Fitting Model": "Voigt (Area, L/G, \u03c3)", "L/G": 30.0}),
            "VOIGT(30)")

    def test_la_uses_sigma_then_gamma(self):
        # branch direction checked against KherveFitting's own LA() source
        # (see the module docstring); Sigma is lineshapes.py's "a"
        self.assertEqual(kf._shape_string(
            {"Fitting Model": "LA (Area, \u03c3, \u03b3)", "Sigma": 1.35,
             "Gamma": 1.8}), "LA(1.35,1.8,0)")

    def test_unrecognised_model_returns_empty(self):
        self.assertEqual(kf._shape_string(
            {"Fitting Model": "Skewed Voigt (Area, L/G, sigma, S)"}), "")
        self.assertEqual(kf._shape_string({}), "")

    def test_unrecognised_model_is_flagged_not_exact_by_the_reader(self):
        import lineshapes as ls
        self.assertFalse(ls.is_exact("KFUnknown(0)"))


class TestRsfCrossReference(unittest.TestCase):
    """_components_from_peaks / _rsf_of: matching a fit peak against a
    "Results TableN" entry by Position/Area/FWHM, not by name (see the
    module docstring -- real files rename peaks, drift slightly after a
    Results Table was computed, or drop it altogether)."""

    HV = 1486.6

    def _rsf(self, peaks, results_row, sheet_name, region_name="R"):
        comps = kf._components_from_peaks(
            peaks, self.HV, 1.0, region_name, results_row, sheet_name)
        return {c.name: c.rsf for c in comps}

    def test_exact_match_is_used(self):
        # a real case, Al2O3.kfit's O1s O-Al
        results_row = {"Peak": {"Peak_0": {
            "Position": 709.83, "Area": 15868.91, "FWHM": 1.0,
            "RSF": 2.88, "Sheetname": "O1s"}}}
        peaks = {"O1s O-Al": {"Position": 709.83, "Area": 15868.91,
                              "FWHM": 1.0, "Fitting Model": "GL (Area)"}}
        self.assertEqual(self._rsf(peaks, results_row, "O1s"),
                         {"O1s O-Al": 2.88})

    def test_a_peak_renamed_since_the_table_was_computed_still_matches(self):
        # Al2O3.kfit's real case: "Al2p3/2 Al2O3" in Fitting.Peaks reads
        # "Al2p3/2 Al-O" in the Results Table -- same Position/Area/FWHM
        results_row = {"Peak": {"Peak_0": {
            "Position": 74.8, "Area": 111265.21, "FWHM": 1.36,
            "RSF": 0.37, "Sheetname": "Al2p"}}}
        peaks = {"Al2p3/2 Al2O3": {"Position": 74.8, "Area": 111265.21,
                                   "FWHM": 1.36,
                                   "Fitting Model": "SGL (Area)"}}
        self.assertEqual(self._rsf(peaks, results_row, "Al2p"),
                         {"Al2p3/2 Al2O3": 0.37})

    def test_a_small_drift_since_the_table_was_computed_still_matches(self):
        # STO_Tilt.kfit's real case: 0.67% area drift, same position/FWHM
        results_row = {"Peak": {"Peak_0": {
            "Position": 132.49, "Area": 117111.24, "FWHM": 0.98,
            "RSF": 4.25, "Sheetname": "Sr3d"}}}
        peaks = {"Sr3d5/2 p1": {"Position": 132.49, "Area": 117904.72,
                                "FWHM": 0.98, "Fitting Model": "GL (Area)"}}
        self.assertEqual(self._rsf(peaks, results_row, "Sr3d"),
                         {"Sr3d5/2 p1": 4.25})

    def test_a_large_drift_is_treated_as_a_stale_table_not_trusted(self):
        # STO.kfit's Y2O3 C1s real case: ~3.5% area drift
        results_row = {"Peak": {"Peak_0": {
            "Position": 284.8, "Area": 1364.52, "FWHM": 1.51,
            "RSF": 1.0, "Sheetname": "C1s"}}}
        peaks = {"C1s C-C": {"Position": 284.82, "Area": 1411.83,
                             "FWHM": 1.53, "Fitting Model": "GL (Area)"}}
        self.assertEqual(self._rsf(peaks, results_row, "C1s"),
                         {"C1s C-C": 0.0})

    def test_a_doublet_partner_missing_from_the_table_stays_unrsfed(self):
        # Y2O3_Kfitting.kfit's real case: only the independent 5/2 peak of
        # each doublet has its own Results Table row
        results_row = {"Peak": {"Peak_0": {
            "Position": 156.61, "Area": 24168.0, "FWHM": 1.17,
            "RSF": 3.98, "Sheetname": "Y3d"}}}
        peaks = {
            "Y3d5/2 Y2O3": {"Position": 156.61, "Area": 24168.0,
                           "FWHM": 1.17, "Fitting Model": "GL (Area)"},
            "Y3d3/2_p2": {"Position": 158.67, "Area": 16122.0,
                         "FWHM": 1.17, "Fitting Model": "GL (Area)"},
        }
        self.assertEqual(self._rsf(peaks, results_row, "Y3d"),
                         {"Y3d5/2 Y2O3": 3.98, "Y3d3/2_p2": 0.0})

    def test_the_nearer_candidate_wins_when_two_are_in_tolerance(self):
        results_row = {"Peak": {
            "Peak_0": {"Position": 285.00, "Area": 1000.0, "FWHM": 1.0,
                      "RSF": 1.0, "Sheetname": "C1s"},
            "Peak_1": {"Position": 285.02, "Area": 1000.0, "FWHM": 1.0,
                      "RSF": 9.0, "Sheetname": "C1s"}}}
        peaks = {"C1s C-C": {"Position": 285.005, "Area": 1000.0,
                             "FWHM": 1.0, "Fitting Model": "GL (Area)"}}
        self.assertEqual(self._rsf(peaks, results_row, "C1s"),
                         {"C1s C-C": 1.0})

    def test_a_results_row_is_claimed_by_only_one_component(self):
        results_row = {"Peak": {"Peak_0": {
            "Position": 285.0, "Area": 1000.0, "FWHM": 1.0,
            "RSF": 1.0, "Sheetname": "C1s"}}}
        peaks = {
            "first": {"Position": 285.0, "Area": 1000.0, "FWHM": 1.0,
                     "Fitting Model": "GL (Area)"},
            "second": {"Position": 285.02, "Area": 1000.0, "FWHM": 1.0,
                      "Fitting Model": "GL (Area)"},
        }
        rsf = self._rsf(peaks, results_row, "C1s")
        self.assertEqual(sorted(rsf.values()), [0.0, 1.0])

    def test_a_row_naming_a_different_sheet_is_ignored(self):
        results_row = {"Peak": {"Peak_0": {
            "Position": 285.0, "Area": 1000.0, "FWHM": 1.0,
            "RSF": 1.0, "Sheetname": "O1s"}}}
        peaks = {"C1s C-C": {"Position": 285.0, "Area": 1000.0,
                             "FWHM": 1.0, "Fitting Model": "GL (Area)"}}
        self.assertEqual(self._rsf(peaks, results_row, "C1s"),
                         {"C1s C-C": 0.0})

    def test_no_results_row_leaves_rsf_at_zero(self):
        peaks = {"C1s C-C": {"Position": 285.0, "Area": 1000.0,
                             "FWHM": 1.0, "Fitting Model": "GL (Area)"}}
        comps = kf._components_from_peaks(peaks, self.HV, 1.0, "R")
        self.assertEqual(comps[0].rsf, 0.0)


class TestBEcorrection(unittest.TestCase):
    """_becorrection_of: which of a file's BEcorrection (file-wide) /
    BEcorrections (per sample row) values, if any, describes a given row --
    never applied to a position (see the module docstring: real files prove
    it is already baked in), only surfaced as metadata."""

    def test_a_rows_own_entry_is_used(self):
        # BaSO4.kfit's real case
        self.assertEqual(
            kf._becorrection_of(0, {0: 1.83, 1: 0.0}, 1.83), 1.83)

    def test_a_zero_entry_is_not_shown(self):
        self.assertIsNone(kf._becorrection_of(1, {0: 1.83, 1: 0.0}, 1.83))

    def test_a_rows_own_zero_wins_over_a_nonzero_file_wide_value(self):
        # Y2O3_Kfitting.kfit's real case: file-wide 0.4, row 0's own 0.0
        self.assertIsNone(kf._becorrection_of(0, {0: 0.0}, 0.4))

    def test_falls_back_to_the_file_wide_value_when_the_row_has_none(self):
        self.assertEqual(kf._becorrection_of(2, {0: 1.83}, 0.4), 0.4)

    def test_nothing_recorded_at_all_gives_none(self):
        # SP2 Carbon.kfit / Metal_Bi.kfit's real case
        self.assertIsNone(kf._becorrection_of(0, {}, None))


class TestSampleAxis(unittest.TestCase):
    """_sample_axis_value: no real sample file has SampleAxis switched on
    with real values (see the module docstring), so this is checked only
    against the schema its one real (disabled, empty) example still shows,
    plus a hand-built enabled/populated case."""

    def test_disabled_gives_none(self):
        # STO_Tilt.kfit's real (only) example
        self.assertIsNone(kf._sample_axis_value(
            {"enabled": 0, "name": "Time", "format": "auto",
            "decimals": 2, "anchors": {}, "values": {}}, 0))

    def test_no_sample_axis_at_all_gives_none(self):
        # every other real sample file
        self.assertIsNone(kf._sample_axis_value(None, 0))

    def test_enabled_with_a_numeric_value_is_formatted_by_decimals(self):
        sa = {"enabled": 1, "name": "Depth (nm)", "decimals": 1,
             "values": {"0": 12.345, "1": 25.0}}
        self.assertEqual(kf._sample_axis_value(sa, 0), "Depth (nm): 12.3")
        self.assertEqual(kf._sample_axis_value(sa, 1), "Depth (nm): 25.0")

    def test_a_row_with_no_value_of_its_own_gives_none(self):
        sa = {"enabled": 1, "name": "Depth (nm)", "values": {"0": 12.0}}
        self.assertIsNone(kf._sample_axis_value(sa, 1))

    def test_enabled_but_no_values_dict_gives_none(self):
        self.assertIsNone(kf._sample_axis_value(
            {"enabled": 1, "name": "Depth (nm)"}, 0))

    def test_a_non_numeric_value_is_shown_as_text(self):
        sa = {"enabled": 1, "name": "Note", "values": {"0": "surface"}}
        self.assertEqual(kf._sample_axis_value(sa, 0), "Note: surface")

    def test_a_blank_name_falls_back_to_a_generic_label(self):
        sa = {"enabled": 1, "name": "", "values": {"0": 1.0}}
        self.assertEqual(kf._sample_axis_value(sa, 0), "Sample axis: 1.00")


@unittest.skipUnless(HAVE_H5PY, "h5py not installed")
class TestRealFiles(unittest.TestCase):
    """Every sample .kfit file loads cleanly; every reconstructed fit's
    residual stays within a tolerance measured on the real files (mirrors
    TestRealCasaFits in test_casafit.py)."""

    RESIDUAL_CEILING = 0.10   # 10% of the region's data range

    def test_every_sample_file_loads(self):
        n = 0
        for rel in REAL_FILES:
            path = _real(rel)
            if not path:
                continue
            n += 1
            doc = readers.load_file(path)
            self.assertGreater(len(doc.regions), 0, rel)
            for r in doc.regions:
                self.assertTrue(r.decodable, rel)
                self.assertGreater(r.n_points, 0, rel)
        if n == 0:
            self.skipTest("KherveFitting sample corpus not present")

    def test_reconstructed_fits_reproduce_the_real_data(self):
        n = 0
        for rel in REAL_FILES:
            path = _real(rel)
            if not path:
                continue
            doc = readers.load_file(path)
            for r in doc.regions:
                if r.fit is None:
                    continue
                cvs = casafit.curves(r.fit, r.energy, r.counts,
                                     r.photon_energy, r.dwell,
                                     r.extra.get("n_scans", 1))
                for cv in cvs:
                    if cv.residual_rms is None:
                        continue
                    n += 1
                    self.assertLess(
                        cv.residual_rms, self.RESIDUAL_CEILING,
                        f"{rel} {r.name} [{r.sample}]: "
                        f"{cv.residual_rms:.3f}")
        if n == 0:
            self.skipTest("no fitted region found in the available corpus")

    def test_becorrection_is_shown_as_metadata_even_without_a_fit(self):
        # BaSO4.kfit: BEcorrection/BEcorrections both 1.83 eV for row 0, but
        # this file has no photon energy anywhere so there is no fit to
        # touch -- the metadata still surfaces on its own.
        path = _real(REAL_FILES[2])
        if not path:
            self.skipTest("KherveFitting sample corpus not present")
        doc = readers.load_file(path)
        c1s = next(r for r in doc.regions if r.name == "C 1s")
        self.assertAlmostEqual(c1s.extra["kf_becorrection"], 1.83)
        md = doc.region_metadata(c1s)
        self.assertIn("BE calibration (KherveFitting)", md)
        self.assertIn("1.83", md["BE calibration (KherveFitting)"])

    def test_becorrection_is_not_reapplied_to_a_real_fits_positions(self):
        # STO_Tilt.kfit row 0: a real per-row correction (0.2 eV) beside a
        # real, fitted Sr3d sheet. Reapplying it (as a CasaXPS-style shift
        # would need) makes the residual 13-27x worse by hand (see the
        # module docstring); this checks the shipped reader stays well
        # clear of that.
        path = _real(REAL_FILES[6])
        if not path:
            self.skipTest("KherveFitting sample corpus not present")
        doc = readers.load_file(path)
        sr3d = next((r for r in doc.regions if r.name == "Sr 3d"
                    and r.extra.get("kf_becorrection")), None)
        if sr3d is None:
            self.skipTest("no Sr 3d row with its own BEcorrections entry")
        self.assertAlmostEqual(sr3d.extra["kf_becorrection"], 0.2)
        self.assertIsNotNone(sr3d.fit)
        cvs = casafit.curves(sr3d.fit, sr3d.energy, sr3d.counts,
                             sr3d.photon_energy, sr3d.dwell,
                             sr3d.extra.get("n_scans", 1))
        self.assertTrue(cvs)
        for cv in cvs:
            if cv.residual_rms is not None:
                self.assertLess(cv.residual_rms, 0.02)

    def test_a_zero_row_correction_is_not_reported(self):
        # Al2O3.kfit: BEcorrection/BEcorrections are all 0.0
        path = _real(REAL_FILES[1])
        if not path:
            self.skipTest("KherveFitting sample corpus not present")
        doc = readers.load_file(path)
        for r in doc.regions:
            self.assertNotIn("kf_becorrection", r.extra, r.name)
            self.assertNotIn("BE calibration (KherveFitting)",
                             doc.region_metadata(r), r.name)

    def test_a_disabled_sample_axis_produces_no_metadata(self):
        # STO_Tilt.kfit is the only real sample file with a SampleAxis dict
        # at all, and it is disabled and empty -- see the module docstring
        n = 0
        for rel in REAL_FILES:
            path = _real(rel)
            if not path:
                continue
            n += 1
            doc = readers.load_file(path)
            for r in doc.regions:
                self.assertNotIn("kf_sample_axis", r.extra, f"{rel} {r.name}")
                self.assertNotIn("Sample axis (KherveFitting)",
                                 doc.region_metadata(r), f"{rel} {r.name}")
        if n == 0:
            self.skipTest("KherveFitting sample corpus not present")

    def test_al2o3_gets_its_real_rsf_cross_referenced(self):
        # Al2O3.kfit: Results Table0 is fully in step with the live fit for
        # both its sheets, including a peak renamed since (Al2p3/2) -- see
        # TestRsfCrossReference for the isolated cases this covers.
        path = _real(REAL_FILES[1])
        if not path:
            self.skipTest("KherveFitting sample corpus not present")
        doc = readers.load_file(path)
        rsf = {}
        for r in doc.regions:
            if r.fit:
                for c in r.fit.components:
                    rsf[c.name] = c.rsf
        self.assertEqual(rsf.get("O1s O-Al"), 2.88)
        self.assertEqual(rsf.get("O1s CO, OH"), 2.88)
        self.assertEqual(rsf.get("Al2p3/2 Al2O3"), 0.37)
        self.assertEqual(rsf.get("Al2p1/2_Al2O3"), 0.19)

    def test_files_with_no_photon_energy_still_load_and_say_why(self):
        path = _real(REAL_FILES[0])   # SP2 Carbon.kfit: known to have none
        if not path:
            self.skipTest("KherveFitting sample corpus not present")
        doc = readers.load_file(path)
        self.assertGreater(len(doc.regions), 0)
        self.assertTrue(all(r.fit is None for r in doc.regions))
        self.assertTrue(any("photon energy" in w for w in doc.warnings))


PEAKS_LIBRARY_DIR = os.environ.get("XPS_KFIT_PEAKS_DIR", os.path.join(
    "D:\\", "Temp", "for claude files", "temp", "KherveFitting Files",
    "Peaks Library"))

# a real two-peak entry (alpha-Fe2O3's Fe2p3/2 satellite pair), trimmed from
# MnNiFeCoCr_Biesinger_Applied SurfaceScience_257_2011_2717/
# Fe2p_alpha-Fe2O3_GL.json
_FE2P_FIXTURE = {
    "Core levels": {
        "Fe2p": {
            "Fitting": {
                "Model": "GL (Area)",
                "Peaks": {
                    "Fe2p3/2 aFe2O3 peak 1": {
                        "Position": 709.83, "Height": 14907.85, "FWHM": 1.0,
                        "L/G": 30.0, "Area": 15868.91, "Sigma": 0.0,
                        "Gamma": 0.0, "Skew": 0.0, "Fitting Model": "GL (Area)",
                    },
                    "Fe2p3/2 aFe2O3 peak 2": {
                        "Position": 710.73, "Height": 10472.76, "FWHM": 1.2,
                        "L/G": 30.0, "Area": 13377.49, "Sigma": 0.0,
                        "Gamma": 0.0, "Skew": 0.0, "Fitting Model": "GL (Area)",
                    },
                },
            },
        },
    },
}


class TestPeakLibrary(unittest.TestCase):
    """D4: a standalone Peaks Library .json opened on its own, with no
    associated spectrum."""

    def _load(self, data):
        fd, path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
            return kf.import_peak_library(path)
        finally:
            os.remove(path)

    def test_one_region_per_core_level_with_its_fit(self):
        doc = self._load(_FE2P_FIXTURE)
        self.assertEqual(len(doc.regions), 1)
        r = doc.regions[0]
        self.assertEqual(r.name, "Fe 2p")
        self.assertTrue(r.decodable)
        self.assertGreater(r.n_points, 100)
        self.assertIsNotNone(r.fit)
        self.assertEqual(len(r.fit.components), 2)
        self.assertEqual(r.fit.regions[0].background, "None")

    def test_the_synthesised_axis_covers_every_peak_with_margin(self):
        r = self._load(_FE2P_FIXTURE).regions[0]
        self.assertLess(min(r.energy), 709.83 - 1.0)
        self.assertGreater(max(r.energy), 710.73 + 1.0)

    def test_the_regions_own_curve_is_the_models_curve(self):
        # the "data" is synthesised from the same components casafit.curves
        # will reconstruct, so the residual against itself is ~0 -- this
        # is not a validation of the model, just of self-consistency
        r = self._load(_FE2P_FIXTURE).regions[0]
        cvs = casafit.curves(r.fit, r.energy, r.counts, r.photon_energy)
        self.assertEqual(len(cvs), 1)
        self.assertIsNotNone(cvs[0].residual_rms)
        self.assertLess(cvs[0].residual_rms, 1e-6)
        self.assertIsNone(cvs[0].chi2_red)   # no dwell/scans: honestly None

    def test_a_file_with_no_core_levels_is_rejected(self):
        with self.assertRaises(ValueError):
            self._load({"Core levels": {}})

    def test_not_json_is_rejected(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("not json at all")
            with self.assertRaises(ValueError):
                kf.import_peak_library(path)
        finally:
            os.remove(path)


class TestPeakLibraryRealFiles(unittest.TestCase):
    def test_every_real_file_loads_and_reproduces_its_own_model(self):
        if not os.path.isdir(PEAKS_LIBRARY_DIR):
            self.skipTest("KherveFitting Peaks Library corpus not present")
        n = 0
        for dirpath, _dirs, names in os.walk(PEAKS_LIBRARY_DIR):
            for fn in names:
                if not fn.lower().endswith(".json"):
                    continue
                path = os.path.join(dirpath, fn)
                n += 1
                doc = kf.import_peak_library(path)
                self.assertGreater(len(doc.regions), 0, path)
                for r in doc.regions:
                    self.assertIsNotNone(r.fit, path)
                    cvs = casafit.curves(r.fit, r.energy, r.counts,
                                         r.photon_energy)
                    self.assertEqual(len(cvs), 1, path)
                    self.assertLess(cvs[0].residual_rms, 1e-6, path)
        self.assertGreater(n, 0)


if __name__ == "__main__":
    unittest.main()
