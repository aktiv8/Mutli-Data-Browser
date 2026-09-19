"""The generated methods text: it states what the files record, splits survey
from high-resolution settings, and leaves out what is not recorded.

Run:  python -m unittest discover tests
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import methods  # noqa: E402
from readers import Region, SpectrumFile  # noqa: E402


def row(region="C 1s", sample="S1", pe="20", step="0.100", dwell="0.100",
        be0="296.00", be1="278.00", **kw):
    md = {"Sample": sample, "Region": region, "Instrument": "Kratos Axis Supra",
          "Operator": "DM", "Anode": "Al", "Photon energy (eV)": "1486.69",
          "Source power (W)": "225", "Pass energy (eV)": pe,
          "Step (eV)": step, "Dwell (s)": dwell, "BE start (eV)": be0,
          "BE end (eV)": be1, "Lens mode": "Hybrid", "Aperture": "Slot",
          "Charge neutraliser": "Yes", "Ion gun / sputtering": "Not used",
          "Date acquired": "2026-03-02 10:00"}
    md.update(kw)
    return md


class TestHelpers(unittest.TestCase):
    def test_values_text(self):
        self.assertEqual(methods.values_text(["40"], "eV"), ("40 eV", 1))
        self.assertEqual(methods.values_text(["40", "160", "40"], "eV"),
                         ("40 and 160 eV", 2))
        self.assertEqual(methods.values_text(["20", "40", "80"], "eV"),
                         ("20, 40 and 80 eV", 3))
        self.assertEqual(methods.values_text(["10", "20", "40", "80"], "eV"),
                         ("10 to 80 eV", 4))
        self.assertEqual(methods.values_text(["", "n/a", None]), ("", 0))
        self.assertEqual(methods.values_text(["0.100", "0.1"], "s"),
                         ("0.1 s", 1))

    def test_join_and(self):
        self.assertEqual(methods.join_and([]), "")
        self.assertEqual(methods.join_and(["a"]), "a")
        self.assertEqual(methods.join_and(["a", "b"]), "a and b")
        self.assertEqual(methods.join_and(["a", "", "b", "c"]), "a, b and c")

    def test_survey_detection(self):
        self.assertTrue(methods.is_survey(row("Survey")))
        self.assertTrue(methods.is_survey(row("Wide Scan")))
        self.assertTrue(methods.is_survey(row("X", be0="1200", be1="0")))
        self.assertFalse(methods.is_survey(row("C 1s")))
        self.assertFalse(methods.is_survey({}))

    def test_effective(self):
        self.assertEqual(methods.effective("  mine ", "auto"), "mine")
        self.assertEqual(methods.effective("", "auto"), "auto")
        self.assertEqual(methods.effective("   ", "auto"), "auto")

    def test_paragraphs(self):
        self.assertEqual(methods.paragraphs("a\nb\n\n\n c \n \nd"),
                         ["a\nb", " c ", "d"])


class TestGenerate(unittest.TestCase):
    def test_nothing_to_describe(self):
        self.assertEqual(methods.generate([]), "")
        self.assertEqual(methods.generate([{}]), "")

    def test_survey_and_high_resolution_are_kept_apart(self):
        rows = [row("Survey", pe="160", step="1.000", dwell="0.050",
                    be0="1200", be1="0"),
                row("C 1s"), row("O 1s"), row("C 1s", sample="S2")]
        text = methods.generate(rows)
        self.assertIn("Kratos Axis Supra spectrometer", text)
        self.assertIn("Al X-rays (photon energy 1486.69 eV) at a source "
                      "power of 225 W", text)
        self.assertIn("Survey spectra (1) were acquired with a pass energy "
                      "of 160 eV, a step size of 1 eV and a dwell time of "
                      "0.05 s per point.", text)
        self.assertIn("High-resolution spectra (3: C 1s ×2, O 1s) used a "
                      "pass energy of 20 eV, a step size of 0.1 eV and a "
                      "dwell time of 0.1 s per point.", text)
        self.assertIn("lens mode Hybrid and aperture Slot", text)
        self.assertIn("from 2 samples (S1, S2)", text)
        self.assertIn("(operator: DM)", text)

    def test_varying_settings_become_a_list_or_range(self):
        rows = [row(pe="20"), row(pe="40"), row(pe="10", dwell="0.5")]
        text = methods.generate(rows)
        self.assertIn("pass energies of 10, 20 and 40 eV", text)
        self.assertIn("dwell times of 0.1 and 0.5 s per point", text)

    def test_unrecorded_settings_are_left_out_not_invented(self):
        rows = [{"Sample": "S1", "Region": "C 1s"}]
        text = methods.generate(rows)
        self.assertNotIn("pass energy", text)
        self.assertNotIn("X-rays", text)
        self.assertNotIn("neutralis", text.lower())
        self.assertIn("instrument recorded in the data files", text)
        self.assertIn("1 spectra", text)

    def test_unknown_instrument_is_not_named(self):
        text = methods.generate([row(Instrument="(unknown)")])
        self.assertNotIn("unknown", text)

    def test_neutraliser_and_ion_gun_wording(self):
        text = methods.generate([row()])
        self.assertIn("Charge neutralisation was used.", text)
        self.assertIn("No ion sputtering was used.", text)
        text = methods.generate([row(**{"Charge neutraliser": "off",
                                        "Ion gun / sputtering": "Used"})])
        self.assertIn("No charge neutralisation was used.", text)
        self.assertIn("The ion gun was used for sputtering.", text)
        text = methods.generate([row(**{"Charge neutraliser":
                                        "Flood gun 3 V"})])
        self.assertIn("Charge neutraliser: Flood gun 3 V.", text)

    def test_depth_profile(self):
        rows = [row(**{"Etch level": str(i), "Etch time (s)": str(i * 30)})
                for i in range(11)]
        text = methods.generate(rows)
        self.assertIn("11 levels per profile", text)
        self.assertIn("cumulative etch time of 300 s", text)
        rows = ([row(sample="A", **{"Etch level": str(i),
                                    "Etch time (s)": str(i * 10)})
                 for i in range(5)]
                + [row(sample="B", **{"Etch level": str(i),
                                      "Etch time (s)": str(i * 10)})
                   for i in range(8)])
        text = methods.generate(rows)
        self.assertIn("5–8 levels per profile on 2 samples", text)

    def test_no_depth_sentence_without_levels(self):
        self.assertNotIn("Depth profiling", methods.generate([row()]))

    def test_calibration_statement(self):
        cal = "Binding energies of S1 were shifted by +0.80 eV."
        text = methods.generate([row()], cal)
        self.assertTrue(text.endswith(cal))
        self.assertNotIn("not charge-corrected", text)
        self.assertTrue(methods.generate([row()]).endswith(
            "Binding energies are not charge-corrected."))

    def test_dates(self):
        rows = [row(**{"Date acquired": "2026-03-02"}),
                row(**{"Date acquired": "2026-03-09"})]
        self.assertIn("acquired 2026-03-02 – 2026-03-09",
                      methods.generate(rows))

    def test_paragraph_structure(self):
        text = methods.generate([row(), row("Survey", be0="1200", be1="0")])
        paras = methods.paragraphs(text)
        self.assertGreaterEqual(len(paras), 3)
        self.assertTrue(paras[0].startswith("X-ray photoelectron"))


class TestFromRealMetadata(unittest.TestCase):
    """The keys ``methods`` reads are the ones the readers really produce."""

    def test_round_trip_through_a_spectrum_file(self):
        def reg(name, lo, hi, pe):
            n = 30
            e = [hi - i * (hi - lo) / (n - 1) for i in range(n)]
            return Region(name=name, index=0, offset=0, energy=e,
                          counts=[1.0] * n, decodable=True, sample="Cu foil",
                          photon_energy=1486.6, pass_energy=pe, dwell=0.1,
                          step=(hi - lo) / (n - 1), anode="Al",
                          lens_mode="Hybrid", source="a.vms")
        f = SpectrumFile()
        f.path = "a.vms"
        f.format_name = "Test"
        f.regions = [reg("Survey", 0, 1200, 160.0), reg("Cu 2p", 925, 960, 20.0),
                     reg("C 1s", 280, 292, 20.0)]
        f.instrument = {"Instrument": "Test Spec", "Charge neutraliser": "Yes",
                        "Ion gun / sputtering": "Not used"}
        f._finish()
        text = methods.generate(f.metadata_rows())
        self.assertIn("Test Spec spectrometer", text)
        self.assertIn("Survey spectra (1) were acquired with a pass energy "
                      "of 160 eV", text)
        self.assertIn("High-resolution spectra (2: Cu 2p, C 1s) used a pass "
                      "energy of 20 eV", text)
        self.assertIn("Charge neutralisation was used.", text)
        self.assertIn("1486.6", text)


if __name__ == "__main__":
    unittest.main()
