"""Sputter settings: fluence and depth, parsing of instrument text, storage in
the annotations, the Depth / Fluence z axes and their notes, and the metadata
and methods text that follow.

Run:  python -m unittest discover tests
"""

import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import annotations  # noqa: E402
import methods  # noqa: E402
import sputter as sp  # noqa: E402
import viewdata  # noqa: E402
from readers import Region, SpectrumFile  # noqa: E402

FULL = {"ion": "Ar+", "energy_ev": 3000, "current": 1.0, "current_unit": "nA",
        "raster_x": 2.0, "raster_y": 2.0, "etch_rate": 0.5,
        "rate_unit": "nm/s"}


class TestMaths(unittest.TestCase):
    def test_fluence_matches_the_formula_by_hand(self):
        # 1 nA over 2 x 2 mm = 0.04 cm^2:  I/(e A) = 1e-9 / (1.602e-19 * 0.04)
        want = 1e-9 / (1.602176634e-19 * 0.04)
        self.assertAlmostEqual(sp.flux(FULL) / want, 1.0, 9)
        self.assertAlmostEqual(sp.fluence(FULL, 60) / (60 * want), 1.0, 9)
        self.assertEqual(sp.fluence(FULL, 0), 0.0)

    def test_units_convert(self):
        s = dict(FULL, current=2, current_unit="µA")
        self.assertAlmostEqual(sp.current_a(s), 2e-6)
        s = dict(FULL, current=500, current_unit="pA")
        self.assertAlmostEqual(sp.current_a(s), 5e-10)
        for unit, per_s in (("nm/s", 1.0), ("nm/min", 1 / 60),
                            ("Å/s", 0.1), ("Å/min", 0.1 / 60)):
            s = dict(FULL, etch_rate=6, rate_unit=unit)
            self.assertAlmostEqual(sp.rate_nm_s(s), 6 * per_s)
        self.assertAlmostEqual(sp.depth_nm(dict(FULL, etch_rate=30,
                                                rate_unit="nm/min"), 120), 60)

    def test_charge_state_divides_the_fluence(self):
        self.assertAlmostEqual(sp.fluence(dict(FULL, charge=2), 10)
                               / sp.fluence(FULL, 10), 0.5)

    def test_a_single_raster_size_is_a_square(self):
        s = sp.sanitise({"raster_x": 3})
        self.assertEqual((s["raster_x"], s["raster_y"]), (3.0, 3.0))
        self.assertAlmostEqual(sp.area_cm2(s), 0.09)

    def test_unknown_stays_unknown(self):
        self.assertIsNone(sp.fluence({}, 60))
        self.assertIsNone(sp.depth_nm({}, 60))
        self.assertIsNone(sp.fluence(dict(FULL, current=None), 60))
        self.assertIsNone(sp.fluence(dict(FULL, raster_x=None,
                                          raster_y=None), 60))
        self.assertIsNone(sp.fluence(FULL, None))
        self.assertIsNone(sp.flux(dict(FULL, raster_x=0, raster_y=0)))

    def test_sanitise_rejects_bad_values(self):
        s = sp.sanitise({"current": -1, "energy_ev": "abc",
                         "current_unit": "kA", "rate_unit": "m/s",
                         "charge": 0.5, "etch_rate": float("nan"),
                         "ion": 5})
        self.assertIsNone(s["current"])
        self.assertIsNone(s["energy_ev"])
        self.assertEqual((s["current_unit"], s["rate_unit"]), ("nA", "nm/min"))
        self.assertEqual(s["charge"], 1)
        self.assertIsNone(s["etch_rate"])
        self.assertEqual(s["ion"], "")
        self.assertEqual(sp.sanitise(None), sp.DEFAULTS)
        self.assertEqual(sp.sanitise("x"), sp.DEFAULTS)
        self.assertEqual(sp.sanitise(sp.sanitise(FULL)), sp.sanitise(FULL))

    def test_is_empty(self):
        self.assertTrue(sp.is_empty({}))
        self.assertTrue(sp.is_empty({"current_unit": "pA"}))
        self.assertFalse(sp.is_empty({"ion": "Ar+"}))
        self.assertFalse(sp.is_empty({"etch_rate": 1}))


class TestNotesAndText(unittest.TestCase):
    def test_missing_says_what_to_enter(self):
        self.assertEqual(sp.missing("Depth", {}), "enter the etch rate")
        self.assertEqual(sp.missing("Depth", FULL), "")
        self.assertEqual(sp.missing("Fluence", {}),
                         "enter the ion current and the raster size")
        self.assertEqual(sp.missing("Fluence", {"current": 1}),
                         "enter the raster size")
        self.assertEqual(sp.missing("Fluence", FULL), "")
        self.assertEqual(sp.missing("Etch time", {}), "")

    def test_describe(self):
        self.assertEqual(sp.describe(FULL),
                         "3 keV Ar+, 1 nA, 2 × 2 mm raster, "
                         "etch rate 0.5 nm/s")
        self.assertEqual(sp.describe({"energy_ev": 500, "ion": "He+"}),
                         "500 eV He+")
        self.assertEqual(sp.describe({}), "")

    def test_metadata_rows(self):
        md = sp.metadata_rows(FULL, 60)
        self.assertEqual(md["Sputter ion"], "Ar+")
        self.assertEqual(md["Sputter energy (eV)"], "3000")
        self.assertEqual(md["Sputter current"], "1 nA")
        self.assertEqual(md["Depth (nm)"], "30")
        self.assertIn("Fluence (ions/cm²)", md)
        self.assertNotIn("Depth (nm)", sp.metadata_rows(
            dict(FULL, etch_rate=None), 60))
        self.assertEqual(sp.metadata_rows({}, 60), {})

    def test_from_text(self):
        self.assertEqual(sp.from_text("5 keV Ar+")["energy_ev"], 5000)
        self.assertEqual(sp.from_text("5 keV Ar+")["ion"], "Ar+")
        s = sp.from_text("Ar+ 3 kV 1.0 uA 2x2 mm")
        self.assertEqual((s["energy_ev"], s["current"], s["current_unit"]),
                         (3000, 1.0, "µA"))
        self.assertEqual((s["raster_x"], s["raster_y"]), (2.0, 2.0))
        s = sp.from_text("500 eV Ar1000+")
        self.assertEqual((s["ion"], s["energy_ev"]), ("Ar1000+", 500))
        s = sp.from_text("1500 x 1500 um")
        self.assertEqual((s["raster_x"], s["raster_y"]), (1.5, 1.5))
        self.assertEqual(sp.from_text("Used"), {})
        self.assertEqual(sp.from_text(""), {})
        self.assertEqual(sp.from_text(None), {})
        self.assertEqual(sp.from_text("Gauge 5 eV")["ion"], "")

    def test_from_properties_never_guesses_units(self):
        props = {"DS_X_DEPTHPROFILEIONGUN_ENERGY": 3000,
                 "DS_X_DEPTHPROFILEIONGUN_CURRENT": 2.5,
                 "DS_X_DEPTHPROFILEIONGUN_SPECIES": "Ar+",
                 "DS_UNRELATED": "5 keV Xe+"}
        s = sp.from_properties(props)
        self.assertEqual(s["ion"], "Ar+")
        self.assertIsNone(s["energy_ev"])         # a bare number: unit unknown
        self.assertIsNone(s["current"])
        s = sp.from_properties({"DS_ION_GUN_ENERGY_EV": 2000.0,
                                "DS_IONGUN_TEXT": "1 uA"})
        self.assertEqual(s["energy_ev"], 2000.0)
        self.assertEqual(s["current"], 1.0)
        self.assertEqual(sp.from_properties({"DS_OTHER": 5}), {})
        self.assertEqual(sp.from_properties(None), {})

    def test_merge_prefill_earlier_wins(self):
        m = sp.merge_prefill({"ion": "Ar+", "energy_ev": 5000},
                             {"ion": "He+", "current": 2.0}, {})
        self.assertEqual((m["ion"], m["energy_ev"], m["current"]),
                         ("Ar+", 5000, 2.0))
        self.assertEqual(sp.merge_prefill({}, None), {})


def level(i, t, sample="P"):
    return Region(name="C 1s", index=0, offset=0, energy=[1.0, 2.0],
                  counts=[1.0, 2.0], decodable=True, sample=sample,
                  etch_level=i, etch_time=t)


class TestZAxes(unittest.TestCase):
    regs = [level(i, 30.0 * i) for i in range(4)]

    def test_depth_and_fluence_axes(self):
        f = lambda r: FULL                                   # noqa: E731
        z = viewdata.resolve_z(self.regs, "Depth", None, f)
        self.assertEqual((z.mode, z.label), ("Depth", "Depth (nm)"))
        self.assertEqual(z.values, [0.0, 15.0, 30.0, 45.0])
        z = viewdata.resolve_z(self.regs, "Fluence", None, f)
        self.assertEqual(z.mode, "Fluence")
        self.assertIn("ions/cm", z.label)
        self.assertEqual(z.values[0], 0.0)
        self.assertAlmostEqual(z.values[3] / z.values[1], 3.0)

    def test_without_settings_it_falls_back(self):
        z = viewdata.resolve_z(self.regs, "Depth", None, lambda r: None)
        self.assertEqual(z.mode, "Etch time")
        z = viewdata.resolve_z(self.regs, "Depth")               # no lookup
        self.assertEqual(z.mode, "Etch time")

    def test_auto_stays_on_etch_time(self):
        z = viewdata.resolve_z(self.regs, "Auto", None, lambda r: FULL)
        self.assertEqual(z.mode, "Etch time")

    def test_per_sample_settings_apply_per_region(self):
        regs = [level(1, 60.0, "A"), level(1, 60.0, "B")]
        sets = {"A": dict(FULL, etch_rate=1.0), "B": dict(FULL, etch_rate=2.0)}
        z = viewdata.resolve_z(regs, "Depth", None, lambda r: sets[r.sample])
        self.assertEqual(z.values, [60.0, 120.0])

    def test_sorted_keeps_working_and_stays_increasing(self):
        order, z = viewdata.z_sorted(self.regs[::-1], "Depth", None,
                                     lambda r: FULL)
        self.assertEqual(z.mode, "Depth")
        self.assertEqual(z.values, sorted(z.values))
        self.assertEqual(order, [3, 2, 1, 0])

    def test_notes_say_what_to_enter(self):
        note = viewdata.z_unavailable("Depth", "Etch time", self.regs,
                                      lambda r: None)
        self.assertIn("enter the etch rate", note)
        self.assertIn("Sputter settings", note)
        note = viewdata.z_unavailable(
            "Fluence", "Etch time", self.regs,
            lambda r: {"current": 1, "current_unit": "nA"})
        self.assertIn("raster size", note)
        no_times = [level(i, None) for i in range(3)]
        note = viewdata.z_unavailable("Depth", "Etch level", no_times,
                                      lambda r: FULL)
        self.assertIn("need", note)
        self.assertIn("etch times", note)
        self.assertEqual(viewdata.z_unavailable("Depth", "Depth", self.regs,
                                                lambda r: FULL), "")
        self.assertEqual(viewdata.z_unavailable("Auto", "Etch time",
                                                self.regs), "")
        self.assertIn("not usable",
                      viewdata.z_unavailable("Acquisition time", "Trace order",
                                             self.regs))

    def test_modes_are_offered(self):
        self.assertIn("Depth", viewdata.Z_MODES)
        self.assertIn("Fluence", viewdata.Z_MODES)


class TestAnnotations(unittest.TestCase):
    def test_store_round_trip_and_empty(self):
        a = annotations.Annotations()
        self.assertTrue(a.is_empty())
        a.set_sputter("f1", "P", FULL)
        self.assertFalse(a.is_empty())
        self.assertEqual(a.sputter_for("f1", "P")["energy_ev"], 3000)
        self.assertIsNone(a.sputter_for("f1", "Q"))
        b = annotations.Annotations.from_json(a.to_json())
        self.assertEqual(b.sputter_for("f1", "P"), a.sputter_for("f1", "P"))
        a.set_sputter("f1", "P", {})                 # empty settings remove
        self.assertTrue(a.is_empty())

    def test_loading_is_tolerant(self):
        b = annotations.Annotations.from_json(
            {"sputter": {"f1|P": {"current": "x", "ion": "Ar+"},
                         "f1|Q": "junk", "f1|R": {}}})
        self.assertEqual(list(b.sputter), ["f1|P"])
        self.assertIsNone(b.sputter_for("f1", "P")["current"])
        self.assertEqual(annotations.Annotations.from_json(
            {"sputter": [1]}).sputter, {})

    def test_metadata_gets_ion_depth_and_fluence_per_level(self):
        a = annotations.Annotations()
        a.set_sputter("f1", "P", FULL)
        r = level(2, 60.0)
        md = a.apply_metadata("f1", 0, r, {"Sample": "P", "Region": "C 1s"})
        self.assertEqual(md["Sputter ion"], "Ar+")
        self.assertEqual(md["Depth (nm)"], "30")
        self.assertIn("Fluence (ions/cm²)", md)
        flat = Region(name="C 1s", index=0, offset=0, sample="P")
        self.assertNotIn("Sputter ion", a.apply_metadata(
            "f1", 0, flat, {"Sample": "P"}))                # not a depth level
        other = level(2, 60.0, "Other")
        self.assertNotIn("Sputter ion", a.apply_metadata(
            "f1", 0, other, {"Sample": "Other"}))


class TestReadersPrefill(unittest.TestCase):
    def test_hint_and_instrument_text_are_combined(self):
        f = SpectrumFile()
        f.instrument = {"Ion gun / sputtering": "Ar+ 3 kV 1 uA"}
        f.sputter_hint = {"ion": "Ar+", "energy_ev": 5000.0}
        s = f.sputter_prefill()
        self.assertEqual(s["energy_ev"], 5000.0)         # the hint wins
        self.assertEqual(s["current"], 1.0)
        self.assertEqual(SpectrumFile().sputter_prefill(), {})
        f = SpectrumFile()
        f.instrument = {"Ion gun / sputtering": "Used"}
        self.assertEqual(f.sputter_prefill(), {})


class TestMethods(unittest.TestCase):
    def rows(self, sset):
        a = annotations.Annotations()
        if sset:
            a.set_sputter("f1", "P", sset)
        out = []
        for i in range(5):
            r = level(i, 60.0 * i)
            md = {"Sample": "P", "Region": "C 1s", "Etch level": str(i),
                  "Etch time (s)": f"{60.0 * i:g}"}
            out.append(a.apply_metadata("f1", 0, r, md))
        return out

    def test_beam_sentence(self):
        text = methods.generate(self.rows(FULL))
        self.assertIn("Etching used a 3000 eV Ar+ beam at 1 nA, rastered "
                      "over 2 × 2 mm, with an etch rate of 0.5 nm/s.",
                      text)
        self.assertIn("The deepest level corresponds to an ion fluence of",
                      text)
        self.assertIn("a depth of 120 nm", text)

    def test_partial_settings_state_only_what_is_known(self):
        text = methods.generate(self.rows({"ion": "Ar+"}))
        self.assertIn("Etching used a Ar+ beam.", text)
        self.assertNotIn("fluence", text)

    def test_no_settings_no_beam_sentence(self):
        text = methods.generate(self.rows(None))
        self.assertIn("Depth profiling was performed", text)
        self.assertNotIn("Etching used", text)


if __name__ == "__main__":
    unittest.main()
