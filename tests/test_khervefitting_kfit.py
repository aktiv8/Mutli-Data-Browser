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
