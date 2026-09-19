"""Metadata carried in VAMAS comments: the block format, and that exporting
and re-reading a file loses none of what VAMAS has no field for.

Run:  python -m unittest discover tests
"""

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import appinfo  # noqa: E402
import exporters  # noqa: E402
import readers  # noqa: E402
import vamasmeta as vm  # noqa: E402
from readers import Region, SpectrumFile  # noqa: E402


class TestBlock(unittest.TestCase):
    def test_marker_names_the_application(self):
        self.assertEqual(vm.START, "=== eXPoSe SpectraDeck metadata ===")
        self.assertIn(appinfo.NAME, vm.END)

    def test_round_trip_of_plain_values(self):
        md = {"Lens mode": "Hybrid", "Pass energy (eV)": "20",
              "Date acquired": "2026-03-02 10:11:12", "Empty": "", "None": None}
        lines = vm.encode(md)
        self.assertEqual(lines[0], vm.START)
        self.assertEqual(lines[-1], vm.END)
        self.assertEqual(vm.decode(lines),
                         {"Lens mode": "Hybrid", "Pass energy (eV)": "20",
                          "Date acquired": "2026-03-02 10:11:12"})

    def test_nothing_to_write_writes_nothing(self):
        self.assertEqual(vm.encode({}), [])
        self.assertEqual(vm.encode({"a": "", "b": "  "}), [])
        self.assertEqual(vm.decode([]), {})
        self.assertEqual(vm.decode(None), {})
        self.assertEqual(vm.decode(["Lens mode: Hybrid"]), {})   # no block

    def test_awkward_text_survives(self):
        md = {"X-ray source": "Al K\u03b1, monochromated \u2013 \u00b5A",
              "Sputter": "value with: colon", "Path": "C:\\dir\\u00e9x",
              "Note": "line one\nline two", "Key: odd": "v",
              "Fluence (ions/cm\u00b2)": "1.5e13"}
        back = vm.decode(vm.encode(md))
        self.assertEqual(back["X-ray source"], md["X-ray source"])
        self.assertEqual(back["Sputter"], "value with: colon")
        self.assertEqual(back["Path"], "C:\\dir\\u00e9x")     # literal \u kept
        self.assertEqual(back["Note"], "line one / line two")
        self.assertEqual(back["Key - odd"], "v")
        self.assertEqual(back["Fluence (ions/cm\u00b2)"], "1.5e13")

    def test_lines_are_latin1_safe(self):
        for line in vm.encode({"X": "Al K\u03b1 \u2192 \u65e5"}):
            line.encode("latin-1")

    def test_blocks_amid_other_comment_lines(self):
        lines = ["Casa Info Follows", "0", vm.START, "A: 1", vm.END,
                 "B: 2", "some text"]
        self.assertEqual(vm.decode(lines), {"A": "1"})

    def test_two_blocks_first_value_wins_and_unclosed_block_reads(self):
        lines = [vm.START, "A: 1", vm.END, vm.START, "A: 9", "B: 2"]
        self.assertEqual(vm.decode(lines), {"A": "1", "B": "2"})

    def test_the_former_application_name_is_still_read(self):
        old = vm._OLD_NAME
        lines = [f"=== {old} metadata ===", "A: 1",
                 f"=== end of {old} metadata ==="]
        self.assertEqual(vm.decode(lines), {"A": "1"})

    def test_keys_restricts_and_orders(self):
        lines = vm.encode({"a": "1", "b": "2", "c": "3"}, keys=["c", "a"])
        self.assertEqual(lines[1:-1], ["c: 3", "a: 1"])

    def test_split_and_common_experiment(self):
        exp, rest = vm.split({"Instrument": "I", "Lens mode": "H", "X": "1"})
        self.assertEqual(exp, {"Instrument": "I", "Lens mode": "H"})
        self.assertEqual(rest, {"X": "1"})
        self.assertEqual(vm.common_experiment(
            [{"Instrument": "", "Operator": "A"}, {"Instrument": "I"}]),
            {"Operator": "A", "Instrument": "I"})


def reg(name="C 1s", sample="S1", n=41, **kw):
    e = [292.0 - i * 0.3 for i in range(n)]
    c = [100.0 + 900 * 2.718 ** (-((x - 286) / 1.0) ** 2) for x in e]
    base = dict(name=name, index=0, offset=0, energy=e, counts=c,
                decodable=True, sample=sample, photon_energy=1486.6,
                pass_energy=20.0, dwell=0.1, step=0.3, source="a.vms",
                count_units="counts/s", anode="Al K-alpha (monochromated)",
                lens_mode="Hybrid", aperture="Slot", date="2026-03-02 10:11:12",
                pos_x=1.5, pos_y=-2.25)
    base.update(kw)
    r = Region(**base)
    r.conditions["X-ray Power"] = "225.00 W"
    return r


def doc(regions, instrument=None):
    f = SpectrumFile()
    f.path = "a.vms"
    f.format_name = "Test"
    f.regions = regions
    f.instrument = instrument or {
        "Instrument": "Test Spec", "Operator": "DM",
        "Acquisition computer": "PC-1", "X-ray source": "Al K\u03b1 (1486.6 eV)",
        "Charge neutraliser": "Yes", "Ion gun / sputtering": "5 keV Ar+"}
    f._finish()
    return f


class TestRoundTrip(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def trip(self, d, **kw):
        regs = [r for r in d.regions if r.decodable]
        metas = [d.region_metadata(r) for r in regs]
        path = os.path.join(self.dir, "out.vms")
        exporters.export_vamas(regs, path, metadata=metas, **kw)
        back = readers.load_file(path)
        return metas, [back.region_metadata(r) for r in back.regions], back

    def test_every_metadata_entry_comes_back(self):
        d = doc([reg("C 1s", "S1"), reg("O 1s", "S1"),
                 reg("C 1s", "S2", pos_x=3.0, pos_y=4.0)])
        before, after, back = self.trip(
            d, instrument="Test Spec", operator="DM")
        skip = {"Source file", "File format"}
        for a, b in zip(before, after):
            for k, v in a.items():
                if k in skip:
                    continue
                self.assertEqual(str(b.get(k, "")), str(v), k)

    def test_instrument_wide_entries_come_back(self):
        d = doc([reg()])
        _b, _a, back = self.trip(d, instrument="Test Spec", operator="DM")
        for k, v in d.instrument.items():
            self.assertEqual(back.instrument.get(k), v, k)

    def test_values_vamas_stores_exactly_are_not_overridden(self):
        d = doc([reg(photon_energy=1486.7143, pass_energy=0.5)])
        _b, _a, back = self.trip(d)
        r = back.regions[0]
        self.assertAlmostEqual(r.photon_energy, 1486.7143, 4)
        self.assertEqual(r.pass_energy, 0.5)      # the text says "0" or "0.5"

    def test_region_name_survives_canonicalisation(self):
        d = doc([reg("wide", "S1", n=41)])
        _b, after, back = self.trip(d)
        self.assertEqual(back.regions[0].name, "wide")

    def test_depth_levels_and_times_come_back(self):
        regs = [reg("C 1s", "P", etch_level=i, etch_time=30.0 * i)
                for i in range(5)]
        before, after, back = self.trip(doc(regs))
        self.assertEqual([r.etch_level for r in back.regions], list(range(5)))
        self.assertEqual([r.etch_time for r in back.regions],
                         [30.0 * i for i in range(5)])
        self.assertEqual(back.depth_profile["total_etch_time"], 120.0)
        self.assertEqual(after[3]["Etch time (s)"], "90")

    def test_entries_without_a_home_are_kept(self):
        import annotations
        d = doc([reg("C 1s", "S1")])
        ann = annotations.Annotations()
        d.annotations, d.file_id = ann, "f1"
        ann.set_note("sample_notes", annotations.sample_key("f1", "S1"),
                     "Sputter cleaned \u00b5-beam")
        ann.set_sputter("f1", "S1", {"ion": "Ar+", "energy_ev": 3000})
        ann.set_shift(annotations.sample_key("f1", "S1"), 0.8)
        regs = [r for r in d.regions]
        r0 = regs[0]
        r0.etch_level, r0.etch_time = 0, 0.0
        before, after, _back = self.trip(d)
        self.assertEqual(after[0]["Notes"], "Sputter cleaned \u00b5-beam")
        self.assertEqual(after[0]["BE shift (eV)"], "+0.800")
        self.assertEqual(after[0]["Sputter ion"], "Ar+")

    def test_sputter_settings_become_the_prefill_again(self):
        import annotations
        regs = [reg("C 1s", "P", etch_level=i, etch_time=30.0 * i)
                for i in range(4)]
        d = doc(regs)
        ann = annotations.Annotations()
        d.annotations, d.file_id = ann, "f1"
        ann.set_sputter("f1", "P", {
            "ion": "Ar+", "energy_ev": 3000, "current": 1.0,
            "current_unit": "nA", "raster_x": 2.0, "raster_y": 2.0,
            "etch_rate": 30, "rate_unit": "nm/min"})
        _b, _a, back = self.trip(d)
        s = back.sputter_prefill()
        self.assertEqual((s["ion"], s["energy_ev"], s["current"]),
                         ("Ar+", 3000.0, 1.0))
        self.assertEqual((s["raster_x"], s["raster_y"]), (2.0, 2.0))
        self.assertEqual((s["etch_rate"], s["rate_unit"]), (30.0, "nm/min"))

    def test_the_file_still_reads_without_the_block(self):
        d = doc([reg()])
        regs = list(d.regions)
        path = os.path.join(self.dir, "plain.vms")
        exporters.export_vamas(regs, path)             # no metadata given
        back = readers.load_file(path)
        self.assertEqual(len(back.regions), 1)
        with open(path, encoding="latin-1") as fh:
            self.assertNotIn(vm.START, fh.read())

    def test_block_is_plain_text_in_the_file(self):
        d = doc([reg()])
        _b, _a, _back = self.trip(d)
        with open(os.path.join(self.dir, "out.vms"), encoding="latin-1") as fh:
            text = fh.read()
        self.assertEqual(text.count(vm.START), 2)      # header + one block
        self.assertIn("Lens mode: Hybrid", text)
        self.assertIn("K\\u03b1", text)                 # escaped, not lost
        text.encode("ascii", errors="strict") if False else None

    def test_metadata_list_may_be_shorter_or_partly_empty(self):
        regs = [reg("C 1s", "A"), reg("O 1s", "A")]
        d = doc(regs)
        path = os.path.join(self.dir, "p.vms")
        exporters.export_vamas(regs, path,
                               metadata=[d.region_metadata(regs[0])])
        back = readers.load_file(path)
        self.assertEqual(len(back.regions), 2)

    def test_regions_without_data_are_skipped_consistently(self):
        bad = Region(name="X", index=0, offset=0, decodable=False, sample="S")
        good = reg("C 1s", "S")
        d = doc([good])
        path = os.path.join(self.dir, "s.vms")
        exporters.export_vamas([bad, good], path,
                               metadata=[{"Lens mode": "WRONG"},
                                         d.region_metadata(good)])
        back = readers.load_file(path)
        self.assertEqual(len(back.regions), 1)
        self.assertEqual(back.region_metadata(back.regions[0])["Lens mode"],
                         "Hybrid")                     # not the skipped one's


if __name__ == "__main__":
    unittest.main()
