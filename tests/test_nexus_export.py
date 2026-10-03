"""NeXus (.nxs) export: the NXxps layout, units and axis type, the recorded
metadata, the charge correction, the fit group and the honesty rule (nothing
that is not recorded is written).

Run:  python -m unittest discover tests
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nexus_export  # noqa: E402
from readers import Region  # noqa: E402

try:
    import h5py
    import numpy as np
    HAVE_H5PY = True
except Exception:
    HAVE_H5PY = False


def text(ds):
    v = ds[()]
    return v.decode("utf-8") if isinstance(v, bytes) else str(v)


def region(**kw):
    n = 21
    be = [290.0 - 0.1 * i for i in range(n)]
    d = dict(name="C 1s", index=0, offset=0, energy=be,
             counts=[100.0 + i for i in range(n)], decodable=True,
             sample="Cu foil", photon_energy=1486.71, pass_energy=20.0,
             dwell=0.1, step=0.1, lens_mode="Hybrid", anode="Al Kα",
             source="a.vms")
    d.update(kw)
    r = Region(**d)
    r.extra["n_scans"] = 5
    r.extra["analyser_mode"] = "Constant analyser energy (CAE)"
    r.extra["t_start"] = "2026-08-24 08:20:50"
    r.extra["tz"] = "UTC"
    r.conditions = {"X-ray Power": "150 W", "Anode voltage (kV)": "15",
                    "X-ray spot (µm)": "400", "Sample tilt (°)": "30"}
    return r


class TestHelpers(unittest.TestCase):
    def test_numbers_are_read_from_recorded_text(self):
        self.assertEqual(nexus_export.number("150 W"), 150.0)
        self.assertEqual(nexus_export.number("4.5"), 4.5)
        self.assertIsNone(nexus_export.number("n/a"))
        self.assertIsNone(nexus_export.number(None))
        self.assertIsNone(nexus_export.number(True))

    def test_group_names_are_safe_and_unique(self):
        self.assertEqual(nexus_export.nx_name("Cu foil/C 1s"), "Cu_foil_C_1s")
        self.assertEqual(nexus_export.nx_name("  "), "spectrum")
        taken = set()
        self.assertEqual(nexus_export.unique("a", taken), "a")
        self.assertEqual(nexus_export.unique("a", taken), "a_2")

    def test_shape_and_background_names(self):
        f = nexus_export.peak_function
        self.assertEqual(f("GL(30)"), "Gaussian-Lorentzian Product")
        self.assertEqual(f("SGL(40)"), "Gaussian-Lorentzian Sum")
        self.assertEqual(f("LA(1.2,2.5,5)"), "Asymmetric Lorentzian")
        self.assertEqual(f("VOIGT(0.3)"), "Voigt")
        self.assertIsNone(f("A(0.2,0.1,10)GL(30)"))     # no NXxps counterpart
        b = nexus_export.background_function
        self.assertEqual(b("Shirley"), "Shirley")
        self.assertEqual(b("U 2 Tougaard"), "Tougaard")
        self.assertIsNone(b("Spline"))

    def test_start_time_keeps_only_what_is_known(self):
        r = region()
        self.assertEqual(nexus_export.start_time(r), "2026-08-24T08:20:50+00:00")
        r.extra["tz"] = ""
        self.assertEqual(nexus_export.start_time(r), "2026-08-24T08:20:50")
        r.extra.pop("t_start")
        self.assertEqual(nexus_export.start_time(r), "")


@unittest.skipUnless(HAVE_H5PY, "h5py not installed")
class TestExport(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, "x.nxs")

    def write(self, regions, **kw):
        return nexus_export.export_nexus(regions, self.path, **kw)

    def test_one_entry_per_spectrum_with_the_nxxps_layout(self):
        n = self.write([region(), region(name="O 1s")])
        self.assertEqual(n, 2)
        with h5py.File(self.path) as f:
            self.assertEqual(list(f), ["Cu_foil_C_1s", "Cu_foil_O_1s"])
            self.assertEqual(f.attrs["default"], "Cu_foil_C_1s")
            e = f["Cu_foil_C_1s"]
            self.assertEqual(e.attrs["NX_class"], "NXentry")
            self.assertEqual(text(e["definition"]), "NXxps")
            self.assertEqual(text(e["method"]), "XPS")
            self.assertEqual(text(e["title"]), "Cu foil C 1s")
            self.assertEqual(text(e["start_time"]), "2026-08-24T08:20:50+00:00")
            for g, cls in (("instrument", "NXinstrument"),
                           ("sample", "NXsample"), ("data", "NXdata"),
                           ("instrument/electronanalyzer",
                            "NXelectronanalyzer"),
                           ("instrument/source_probe", "NXsource"),
                           ("instrument/beam_probe", "NXbeam")):
                self.assertEqual(e[g].attrs["NX_class"], cls, g)

    def test_what_the_nxxps_validator_asks_for_and_we_know(self):
        self.write([region()], instrument={"Operator": "DJM",
                                           "Institution": "Uni X"})
        with h5py.File(self.path) as f:
            e = f["Cu_foil_C_1s"]
            self.assertEqual(e["definition"].attrs["version"],
                             nexus_export.NXDL_VERSION)
            self.assertEqual(text(e["instrument/source_probe/associated_beam"]),
                             "/Cu_foil_C_1s/instrument/beam_probe")
            self.assertIn("instrument/beam_probe", e)      # it points at one
            self.assertEqual(text(e["user/affiliation"]), "Uni X")
            note = e["metadata/data"][()]
            self.assertIsInstance(note, bytes)             # NX_BINARY
            json.loads(note.decode("utf-8"))

    def test_the_spectrum_axis_units_and_type(self):
        self.write([region()])
        with h5py.File(self.path) as f:
            d = f["Cu_foil_C_1s/data"]
            self.assertEqual(d.attrs["signal"], "data")
            self.assertEqual(d.attrs["axes"], "energy")
            self.assertEqual(d.attrs["energy_indices"], 0)
            self.assertEqual(d["energy"].attrs["type"], "binding")
            self.assertEqual(d["energy"].attrs["units"], "eV")
            self.assertEqual(d["data"].attrs["units"], "counts")
            np.testing.assert_allclose(d["energy"][()], region().energy)
            np.testing.assert_allclose(d["data"][()], region().counts)

    def test_a_kinetic_axis_says_so(self):
        self.write([region(energy_label="Kinetic Energy")])
        with h5py.File(self.path) as f:
            self.assertEqual(
                f["Cu_foil_C_1s/data/energy"].attrs["type"], "kinetic")

    def test_acquisition_settings(self):
        self.write([region()], instrument={"Instrument": "Axis Supra",
                                           "Operator": "DJM",
                                           "Work function (eV)": "4.31"})
        with h5py.File(self.path) as f:
            e = f["Cu_foil_C_1s"]
            a = e["instrument/electronanalyzer"]
            self.assertEqual(a["energydispersion/pass_energy"][()], 20.0)
            self.assertEqual(text(a["energydispersion/energy_scan_mode"]),
                             "fixed_analyzer_transmission")
            self.assertEqual(text(a["collectioncolumn/lens_mode"]), "Hybrid")
            self.assertAlmostEqual(a["work_function"][()], 4.31)
            self.assertEqual(a["number_of_scans"][()], 5)
            self.assertEqual(a["dwell_time"][()], 0.1)
            s = e["instrument/source_probe"]
            self.assertEqual(text(s["name"]), "Al Kα")      # not mangled
            self.assertEqual(s["power"][()], 150.0)
            self.assertEqual(s["voltage"][()], 15000.0)
            self.assertEqual(
                e["instrument/beam_probe/incident_energy"][()], 1486.71)
            self.assertEqual(e["instrument/beam_probe/extent"].attrs["units"],
                             "µm")
            self.assertEqual(text(e["user/name"]), "DJM")
            self.assertEqual(text(
                e["instrument/device_information/model"]), "Axis Supra")
            self.assertEqual(
                e["sample/transformations/"
                  "sample_normal_polar_angle_of_tilt"][()], 30.0)

    def test_nothing_unrecorded_is_invented(self):
        r = region(pass_energy=None, lens_mode="", anode="",
                   photon_energy=None, dwell=None, step=None)
        r.conditions = {}
        r.extra.clear()
        self.write([r])
        with h5py.File(self.path) as f:
            e = f["Cu_foil_C_1s"]
            self.assertNotIn("start_time", e)
            self.assertNotIn("user", e)
            self.assertNotIn("energy_referencing", e)
            self.assertNotIn("type", e["instrument/source_probe"])
            self.assertNotIn("probe", e["instrument/source_probe"])
            self.assertNotIn("work_function", e["instrument/electronanalyzer"])
            ed = e["instrument/electronanalyzer/energydispersion"]
            self.assertNotIn("pass_energy", ed)
            self.assertNotIn("energy_scan_mode", ed)
            self.assertNotIn("scheme", ed)
            self.assertNotIn("incident_energy", e["instrument/beam_probe"])
            self.assertNotIn("transmission_function",
                             e["instrument/electronanalyzer"])

    def test_the_charge_correction_is_recorded(self):
        r = region(calibration_shift=1.5, shift_applied=1.5)
        r.extra["casa_calib"] = {"measured": 283.3, "assigned": 284.8}
        self.write([r])
        with h5py.File(self.path) as f:
            c = f["Cu_foil_C_1s/energy_referencing"]
            self.assertEqual(c.attrs["NX_class"], "NXcalibration")
            self.assertTrue(c["applied"][()])
            self.assertEqual(c["offset"][()], 1.5)
            self.assertEqual(c["measured"][()], 283.3)
            self.assertEqual(c["assigned"][()], 284.8)

    def test_a_shift_not_yet_applied_says_so(self):
        self.write([region(calibration_shift=0.7)])
        with h5py.File(self.path) as f:
            c = f["Cu_foil_C_1s/energy_referencing"]
            self.assertFalse(c["applied"][()])
            self.assertEqual(c["offset"][()], 0.7)

    def test_the_transmission_function_travels(self):
        r = region(tf_ke=[1100.0, 1300.0], tf_values=[1.0, 0.8])
        self.write([r])
        with h5py.File(self.path) as f:
            t = f["Cu_foil_C_1s/instrument/electronanalyzer/"
                  "transmission_function"]
            self.assertEqual(t.attrs["signal"], "relative_intensity")
            self.assertEqual(list(t.attrs["axes"]), ["kinetic_energy"])
            self.assertEqual(len(t["kinetic_energy"]), r.n_points)

    def test_all_the_metadata_is_kept_as_json(self):
        r = region()
        md = {"Operator": "DJM", "Source": "Al Kα (1486.7 eV)"}
        self.write([r], metadata=[md], experiment_metadata={"Project": "P1"})
        with h5py.File(self.path) as f:
            n = f["Cu_foil_C_1s/metadata"]
            self.assertEqual(n.attrs["NX_class"], "NXnote")
            doc = json.loads(text(n["data"]))
            self.assertEqual(doc["region"], md)
            self.assertEqual(doc["experiment"], {"Project": "P1"})
            self.assertEqual(text(n["source_file"]), "a.vms")

    def test_regions_without_data_are_skipped_and_none_raises(self):
        bad = region(decodable=False)
        self.assertEqual(self.write([bad, region()]), 1)
        with h5py.File(self.path) as f:
            self.assertEqual(len(f), 1)
        with self.assertRaises(ValueError):
            self.write([bad])
        self.assertFalse(os.path.exists(self.path + ".part"))

    def test_same_names_get_distinct_entries(self):
        self.write([region(), region()])
        with h5py.File(self.path) as f:
            self.assertEqual(list(f), ["Cu_foil_C_1s", "Cu_foil_C_1s_2"])

    def test_the_file_names_its_creator(self):
        self.write([region()])
        with h5py.File(self.path) as f:
            self.assertIn("SpectraDeck", f.attrs["creator"])
            self.assertEqual(f.attrs["file_name"], "x.nxs")


@unittest.skipUnless(HAVE_H5PY, "h5py not installed")
class TestFit(unittest.TestCase):
    def setUp(self):
        import test_casafit
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, "fit.nxs")
        self.r = test_casafit.fitted_region()

    def test_the_fit_becomes_an_nxfit_group(self):
        nexus_export.export_nexus([self.r], self.path)
        with h5py.File(self.path) as f:
            e = f["S_Ti_2p"]
            fits = [k for k in e if k.startswith("fit_")]
            self.assertEqual(fits, ["fit_Ti_2p"])
            fit = e[fits[0]]
            self.assertEqual(fit.attrs["NX_class"], "NXfit")
            self.assertEqual(text(fit["label"]), "Ti 2p")
            peaks = [k for k in fit if k.startswith("peak")]
            self.assertEqual(len(peaks), 2)
            p = fit["peak1"]
            self.assertEqual(p.attrs["NX_class"], "NXpeak")
            self.assertEqual(text(p["label"]), "Ti 2p3/2 Ti(IV)")
            self.assertEqual(text(p["function/function_type"]),
                             "Gaussian-Lorentzian Product")
            self.assertEqual(text(p["function/shape"]), "GL(30)")
            self.assertEqual(p["fit_parameters/area"][()], 3394.1269)
            self.assertAlmostEqual(p["fit_parameters/width"][()], 1.2737472)
            self.assertEqual(p["fit_parameters/area"].attrs["units"],
                             "counts/s eV")
            self.assertEqual(fit["background1"].attrs["NX_class"], "NXpeak")
            self.assertEqual(text(fit["background1/function/function_type"]),
                             "Shirley")

    def test_the_fit_peaks_are_in_the_frame_of_the_axis(self):
        import quant
        nexus_export.export_nexus([self.r], self.path)
        rows = quant.fit_rows(self.r, curves=True)
        with h5py.File(self.path) as f:
            fit = f["S_Ti_2p/fit_Ti_2p"]
            for k, comp in enumerate(rows[0]["components"]):
                self.assertAlmostEqual(
                    fit[f"peak{k + 1}/fit_parameters/position"][()],
                    comp["be"], 9)

    def test_envelope_and_residual_match_the_data(self):
        nexus_export.export_nexus([self.r], self.path)
        with h5py.File(self.path) as f:
            d = f["S_Ti_2p/fit_Ti_2p/data"]
            self.assertEqual(d.attrs["signal"], "input_dependent")
            x = d["input_independent"][()]
            y = d["input_dependent"][()]
            env = d["fit_sum"][()]
            res = d["residual"][()]
            self.assertEqual(len(x), len(y))
            ok = ~np.isnan(env)
            np.testing.assert_allclose(res[ok], y[ok] - env[ok])
            self.assertLess(np.sqrt(np.mean(res[ok] ** 2)),
                            0.05 * (y.max() - y.min()))
            np.testing.assert_allclose(
                y, np.asarray(self.r.counts)[
                    np.isin(np.asarray(self.r.energy), x)])

    def test_a_background_without_peaks_is_not_written_as_a_fit(self):
        self.r.fit.components = []              # CasaXPS: background only
        nexus_export.export_nexus([self.r], self.path)
        with h5py.File(self.path) as f:
            self.assertFalse([k for k in f["S_Ti_2p"] if k.startswith("fit_")])
            self.assertIn("data", f["S_Ti_2p"])

    def test_fits_can_be_left_out_and_a_plain_spectrum_has_none(self):
        nexus_export.export_nexus([self.r], self.path, include_fits=False)
        with h5py.File(self.path) as f:
            self.assertFalse([k for k in f["S_Ti_2p"] if k.startswith("fit_")])
        self.r.fit = None
        nexus_export.export_nexus([self.r], self.path)
        with h5py.File(self.path) as f:
            self.assertFalse([k for k in f["S_Ti_2p"] if k.startswith("fit_")])


class TestWithoutH5py(unittest.TestCase):
    def test_the_message_says_what_to_install(self):
        import builtins
        real = builtins.__import__

        def no_h5py(name, *a, **k):
            if name == "h5py":
                raise ImportError(name)
            return real(name, *a, **k)

        builtins.__import__ = no_h5py
        try:
            with self.assertRaises(ValueError) as cm:
                nexus_export.export_nexus(
                    [region()], os.path.join(tempfile.gettempdir(), "n.nxs"))
        finally:
            builtins.__import__ = real
        self.assertIn("h5py", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
