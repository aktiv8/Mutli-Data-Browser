"""Analysis time, spot size, acquisition and analyser mode (milestone G1).

The timing rules are checked on plain objects; the reader side on small
synthetic Avantage dumps (properties as Avantage writes them), on the comment
lines CasaXPS copies into a VAMAS file (taken from a real export), and on a
VAMAS round trip.

Run:  python -m unittest discover tests
"""

import datetime as dt
import os
import struct
import sys
import tempfile
import unittest
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import methods  # noqa: E402
import metasummary  # noqa: E402
import timing  # noqa: E402
from exporters import export_vamas  # noqa: E402
from readers import load_file, Region  # noqa: E402
from readers.base import analyser_mode_name, CAE, CRR  # noqa: E402
from readers.vamas import avantage_dump, casa_block_facts  # noqa: E402
from test_thermo_kinds import dump  # noqa: E402


def region(dwell=0.05, points=251, scans=10, mode="Scan", start=None, end=None,
           sample="S", tz="UTC"):
    r = Region(name="C 1s", index=0, offset=0, dwell=dwell,
               energy=[float(i) for i in range(points)],
               counts=[1.0] * points, decodable=True, sample=sample)
    if scans is not None:
        r.extra["n_scans"] = scans
    if mode:
        r.extra["acq_mode"] = mode
    if start:
        r.extra["t_start"], r.extra["tz"] = start, tz
    if end:
        r.extra["t_end"] = end
    return r


def doc(*regions):
    return SimpleNamespace(regions=list(regions), path="x.vgd")


class TestCountingTime(unittest.TestCase):
    def test_a_scan_counts_every_point_and_scan(self):
        self.assertAlmostEqual(timing.net_seconds(region()), 125.5)

    def test_a_snapshot_records_its_channels_in_parallel(self):
        r = region(dwell=1.0, points=128, scans=5, mode="Snapshot")
        self.assertEqual(timing.net_seconds(r), 5.0)
        self.assertEqual(timing.net_seconds(
            region(dwell=1.0, points=128, scans=2, mode="SnapMap")), 2.0)

    def test_unknown_scans_or_dwell_give_no_number(self):
        self.assertIsNone(timing.net_seconds(region(scans=None)))
        self.assertIsNone(timing.net_seconds(region(dwell=None)))

    def test_a_float32_dwell_is_not_rounded_the_wrong_way(self):
        # the .vgd stores 0.05 as 0.05000000074505806 (125.50000187 s)
        self.assertEqual(timing.net_seconds(region(dwell=0.05000000074505806)),
                         timing.net_seconds(region(dwell=0.05)))


class TestRuns(unittest.TestCase):
    def test_overlapping_files_are_counted_once_and_gaps_not_at_all(self):
        a = region(start="2026-08-24 09:00:00", end="2026-08-24 10:00:00")
        b = region(start="2026-08-24 09:30:00", end="2026-08-24 10:30:00")
        c = region(start="2026-08-24 12:00:00", end="2026-08-24 12:30:00")
        s = timing.summarise([doc(a), doc(b), doc(c)])
        self.assertEqual(s.active, 2 * 3600)              # 09:00-10:30 + 12:00-12:30 = 2 h
        self.assertEqual(s.span, 3.5 * 3600)              # gap included
        self.assertEqual(s.tz, "UTC")
        self.assertAlmostEqual(s.net, 3 * 125.5)
        self.assertAlmostEqual(s.overhead, 2 * 3600 - 3 * 125.5)

    def test_points_of_one_file_share_one_window(self):
        rs = [region(start="2026-08-24 13:00:00", end="2026-08-24 17:00:00")
              for _ in range(12)]
        s = timing.summarise([doc(*rs)])
        self.assertEqual(len(s.runs), 1)
        self.assertEqual(s.active, 4 * 3600)

    def test_without_times_only_counting_time_is_stated(self):
        s = timing.summarise([doc(region(), region())])
        self.assertIsNone(s.active)
        self.assertIsNone(s.overhead)
        self.assertAlmostEqual(s.net, 251.0)
        self.assertTrue(any("not recorded" in n for n in s.notes))

    def test_a_region_without_scans_stops_the_overhead_claim(self):
        a = region(start="2026-08-24 09:00:00", end="2026-08-24 10:00:00")
        b = region(scans=None, start="2026-08-24 09:00:00",
                   end="2026-08-24 10:00:00")
        s = timing.summarise([doc(a, b)])
        self.assertIsNone(s.overhead)
        self.assertEqual(s.n_without_net, 1)
        self.assertTrue(any("scans" in n for n in s.notes))

    def test_a_run_that_ends_before_it_starts_is_ignored(self):
        r = region(start="2026-08-24 10:00:00", end="2026-08-24 09:00:00")
        self.assertIsNone(timing.interval(r))

    def test_sample_counting_time(self):
        d = doc(region(sample="A"), region(sample="A"), region(sample="B"))
        self.assertEqual(timing.sample_net(d), {"A": 251.0, "B": 125.5})

    def test_formatting(self):
        f = timing.fmt_duration
        self.assertEqual(f(45), "45 s")
        self.assertEqual(f(71), "1 min 11 s")
        self.assertEqual(f(252), "4 min 12 s")
        self.assertEqual(f(300), "5 min")
        self.assertEqual(f(3900), "1 h 05 min")
        self.assertEqual(f(2 * 86400 + 3 * 3600), "2 d 3 h")
        self.assertEqual(timing.fmt_ts(dt.datetime(2026, 8, 24, 8, 20, 50),
                                       "UTC"), "2026-08-24 08:20:50 UTC")
        self.assertIsNone(timing.parse_ts("24/8/2026"))
        self.assertEqual(timing.parse_ts("2026-08-24T08:20"),
                         dt.datetime(2026, 8, 24, 8, 20))

    def test_the_report_lines_name_only_what_is_known(self):
        s = timing.summarise([doc(region())])
        self.assertEqual(dict(timing.describe(s)), {"Counting time": "2 min 06 s"})


PROPS = """DS_SOPROPID_VOLTAGE                         : VT_R4   = 12000.000000
DS_SOPROPID_CURRENT                         : VT_R4   = 0.002500
DS_SOPROPID_WIDTH                           : VT_R4   = 400.000000
DS_SOPROPID_LENGTH                          : VT_R4   = {length}
DS_ACPROPID_START_TIME                      : VT_DATE = 24/8/2026   08:20:50
{end}DS_ACPROPID_ACQ_TIME                        : VT_R4   = 0.050000
DS_ACPROPID_PERIODS                         : VT_I4   = {periods}
DS_ACPROPID_MODE                            : VT_I2   = {mode}
DS_ACPROPID_DIRECTION                       : VT_I2   = {direction}
DS_ANPROPID_MODE                            : VT_I2   = 1
DS_ANPROPID_WORK_FTN                        : VT_R4   = 4.200000
DS_SOURCE_FLOODGUNPROPID_CURRENT            : VT_R4   = 200.000000
DS_SOURCE_FLOODGUNPROPID_ENERGY             : VT_R4   = 0.700000
DS_SOURCE_FLOODGUNPROPID_DESCRIPTION        : VT_BSTR = 'Default FG03 mode'
"""
END = "DS_ACPROPID_END_TIME                        : VT_DATE = 24/8/2026   08:22:01\n"


class Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def write(self, name, text):
        p = os.path.join(self.dir.name, name)
        with open(p, "w", encoding="latin-1", newline="") as fh:
            fh.write(text)
        return p

    def avantage(self, name="C1s Scan.avg", periods=4, mode=2, direction=1,
                 end=END, length="400.000000", ne=4):
        text = dump(name.rsplit(".", 1)[0],
                    [(1188.0, 0.5, ne, "ENERGY", "LINEAR", "E", "eV", "Energy")],
                    [(0, ne - 1, 1)], [((), [], list(range(1, ne + 1)))])
        props = PROPS.format(periods=periods, mode=mode, direction=direction,
                             end=end, length=length)
        text = text.replace("DS_ANPROPID_PASS ", props + "DS_ANPROPID_PASS ", 1)
        return load_file(self.write(name, text))


class TestAvantageFacts(Tmp):
    def test_a_scan_carries_its_run_scans_and_source_facts(self):
        f = self.avantage()
        r = f.regions[0]
        md = f.region_metadata(r)
        self.assertEqual(r.extra["n_scans"], 4)
        self.assertEqual(md["Scans"], "4")
        self.assertEqual(md["Acquisition mode"], "Scan")
        self.assertEqual(md["Analyser mode"], CAE)
        self.assertEqual(md["Run started"], "2026-08-24 08:20:50 UTC")
        self.assertEqual(md["Run finished"], "2026-08-24 08:22:01 UTC")
        self.assertEqual(md["X-ray spot (µm)"], "400")
        self.assertEqual(md["Anode voltage (kV)"], "12")
        self.assertEqual(md["Emission current (mA)"], "2.5")
        self.assertEqual(md["Acquisition software"], "Thermo Avantage")
        self.assertEqual(md["Work function (eV)"], "4.2")
        self.assertEqual(md["Charge neutraliser"],
                         "Default FG03 mode, 200 µA, 0.7 eV")
        # 0.05 s x 4 points x 4 scans
        self.assertEqual(md["Counting time"], "1 s")

    def test_a_rectangular_spot_shows_both_sides(self):
        md = self.avantage(length="100.000000")
        self.assertEqual(md.region_metadata(md.regions[0])["X-ray spot (µm)"],
                         "400 × 100")

    def test_direction_zero_is_a_snapshot_and_counts_no_points(self):
        f = self.avantage("Al2p Snap.avg", periods=5, mode=3, direction=0,
                          ne=128)
        r = f.regions[0]
        self.assertEqual(r.extra["acq_mode"], "Snapshot")
        self.assertEqual(r.extra["acq_code"], 3)
        self.assertEqual(timing.net_seconds(r), 0.05 * 5)

    def test_no_end_time_means_no_run_window(self):
        f = self.avantage("C1s Snap.avg", periods=1, mode=7, direction=0,
                          end="")
        r = f.regions[0]
        self.assertEqual(r.extra["t_start"], "2026-08-24 08:20:50")
        self.assertNotIn("t_end", r.extra)
        md = f.region_metadata(r)
        self.assertIn("Run started", md)
        self.assertNotIn("Run finished", md)
        self.assertIsNone(timing.interval(r))

    def test_the_facts_reach_the_report_layout(self):
        f = self.avantage()
        lay = metasummary.layout_file(f.samples_metadata())
        common = dict(lay.common)
        for key in ("X-ray spot (µm)", "Analyser mode", "Acquisition mode",
                    "Scans", "Anode voltage (kV)", "Acquisition software"):
            self.assertIn(key, common, key)

    def test_a_file_with_no_periods_states_no_scans(self):
        f = self.avantage()
        r = f.regions[0]
        r.extra.pop("n_scans")
        self.assertNotIn("Scans", f.region_metadata(r))
        self.assertNotIn("Counting time", f.region_metadata(r))


CASA_BLOCK = [
    "Casa Info Follows", "1", "Calib M = 285.1 A = 284.8 BE ADD", "1",
    "Pt #002a X Y [22855.6 , 44677.1]",
    "X-ray spot-size: 200 um by 200 um",
    "20260824",
    "LENS_MODE_NAME : Standard:  24/8/2026   10:53:23",
    "Default FG03 mode",
    "F/G Current:  200.000000 F/G Energy:  0.700000",
]
CASA_HEADER = [
    "Casa Info Follows CasaXPS Version 2.3.27PR7.0", "0",
    ";Dump of DataSpace 'E:\\data\\C1s Scan.VGD'",
    "DS_EXT_SUPROPID_AUTHOR      : VT_BSTR = 'engineer'",
    "DS_GEPROPID_INSTRUMENT                      : VT_BSTR = 'K-Alpha+'",
    "DS_ACPROPID_PERIODS                         : VT_I4   = 10",
]


class TestCasaVamas(unittest.TestCase):
    def test_block_comments_give_spot_lens_and_neutraliser(self):
        got = casa_block_facts(CASA_BLOCK)
        self.assertEqual(got["spot"], "200")
        self.assertEqual(got["lens"], "Standard")
        self.assertEqual(got["neutraliser"], "Default FG03 mode, 200 µA, 0.7 eV")

    def test_a_rectangular_spot_and_a_missing_description(self):
        got = casa_block_facts(["X-ray spot-size: 200 um by 100 um",
                                "F/G Current: 100.0 F/G Energy: 3.0"])
        self.assertEqual(got["spot"], "200 × 100")
        self.assertEqual(got["neutraliser"], "100 µA, 3 eV")

    def test_a_number_line_above_is_not_taken_for_the_description(self):
        got = casa_block_facts(["20260824",
                                "F/G Current: 200.0 F/G Energy: 0.7"])
        self.assertEqual(got["neutraliser"], "200 µA, 0.7 eV")

    def test_the_avantage_dump_in_the_header_is_read_as_properties(self):
        p = avantage_dump(CASA_HEADER)
        self.assertEqual(p["DS_EXT_SUPROPID_AUTHOR"], "engineer")
        self.assertEqual(p["DS_GEPROPID_INSTRUMENT"], "K-Alpha+")
        self.assertEqual(p["DS_ACPROPID_PERIODS"], 10)
        self.assertEqual(avantage_dump(["just a comment", "Sweeps: 2"]), {})

    def test_analyser_mode_words(self):
        self.assertEqual(analyser_mode_name("FAT"), CAE)
        self.assertEqual(analyser_mode_name("cae"), CAE)
        self.assertEqual(analyser_mode_name("FRR"), CRR)
        self.assertEqual(analyser_mode_name("Not Specified"), "")
        self.assertEqual(analyser_mode_name("something"), "something")


class TestVamasRoundTrip(Tmp):
    def test_the_real_scan_count_is_written_and_read_back(self):
        r = region(dwell=0.05, points=21, scans=10)
        r.energy = [280.0 + 0.5 * i for i in range(21)]
        r.photon_energy, r.pass_energy, r.step = 1486.68, 50.0, 0.5
        p = os.path.join(self.dir.name, "o.vms")
        export_vamas([r], p, include_transmission=False)
        back = load_file(p)
        b = back.regions[0]
        self.assertEqual(b.extra["n_scans"], 10)
        md = back.region_metadata(b)
        self.assertEqual(md["Scans"], "10")
        self.assertEqual(md["Analyser mode"], CAE)       # written as FAT
        self.assertEqual(md["Counting time"], "10 s")    # 0.05 x 21 x 10 = 10.5


class TestOtherFormats(Tmp):
    def test_kal_sweeps_become_the_scan_count(self):
        from test_readers import KAL
        text = KAL.replace(
            "  42 Pass energy", " 130 # Sweeps completed     = 3\n  42 Pass energy")
        f = load_file(self.write("t.kal", text))
        r = f.regions[0]
        self.assertEqual(r.extra["n_scans"], 3)
        md = f.region_metadata(r)
        self.assertEqual(md["Scans"], "3")
        self.assertEqual(md["Acquisition software"], "Kratos Vision")
        self.assertEqual(md["Counting time"], "12 s")     # 1 s x 4 points x 3
        self.assertNotIn("ESCApe", " ".join(md.values()))  # Kratos Vision

    def test_newer_kal_files_give_power_analyser_aperture_and_neutraliser(self):
        # keys as a real NICPU-era file writes them: no plain "Xray Gun
        # current", so power used to be missing altogether
        from test_readers import KAL
        text = KAL.replace(
            "  42 Pass energy",
            " 200 NICPU X-ray Gun Emission Current = 0.012 A\n"
            " 201 NICPU X-ray Gun Anode HT Voltage = 12000 V\n"
            " 202 Analyser Scan Mode = F_FAT\n"
            " 203 Descriptor for aperture size used in acquisition = Slot\n"
            " 204 Descriptor for iris position used in acquisition = slot\n"
            " 205 Neutraliser Switch State = F_NEUTRALISER_MANUAL_SETTINGS\n"
            " 206 Charge Neutraliser Filament Current = 0.168\n"
            " 207 Charge Neutraliser Filament Bias = 0.28\n"
            " 208 Charge Neutraliser Charge Balance = 0.84\n"
            "  42 Pass energy")
        f = load_file(self.write("n.kal", text))
        md = f.region_metadata(f.regions[0])
        self.assertEqual(md["Source power (W)"], "144")
        self.assertEqual(md["Anode voltage (kV)"], "12")
        self.assertEqual(md["Emission current (mA)"], "12")
        self.assertEqual(md["Analyser mode"], CAE)
        self.assertEqual(md["Aperture"], "Slot")           # iris agrees: no repeat
        self.assertEqual(md["Charge neutraliser"],
                         "manual settings: filament current 0.168, bias 0.28, "
                         "balance 0.84")

    def test_a_neutraliser_that_is_off_is_not_described(self):
        from readers.kratos_kal import KratosKalFile
        self.assertEqual(KratosKalFile._neutraliser(
            {"Neutraliser Switch State": "F_NEUTRALISER_OFF"}), "")
        self.assertEqual(KratosKalFile._neutraliser({}), "")

    def test_scienta_sweeps_become_the_scan_count(self):
        e = [545.0 - 0.5 * i for i in range(6)]
        txt = ["[Info]", "Number of Regions=1", "", "[Region 1]",
               "Region Name=O1s", "Dimension 1 name=Binding Energy [eV]",
               "Dimension 1 size=6",
               "Dimension 1 scale=" + " ".join("%.5f" % x for x in e), "",
               "[Info 1]", "Excitation Energy=700.0", "Step Time=200",
               "Number of Sweeps=20", "", "[Data 1]"]
        txt += [" %.6E  %.6E" % (a, 1.0) for a in e]
        f = load_file(self.write("s.txt", "\n".join(txt) + "\n"))
        md = f.region_metadata(f.regions[0])
        self.assertEqual(md["Scans"], "20")
        self.assertEqual(md["Acquisition software"], "Scienta SES")

    def test_only_a_kratos_experiment_is_said_to_come_from_escape(self):
        from readers.kratos_experiment import EscapeParser
        p = EscapeParser()
        p.raw, p.strings = b"..MI-XPS-12 AxisChargeNeutraliser..", []
        p._parse_instrument()
        self.assertEqual(p.instrument["Acquisition software"], "Kratos ESCApe")


def escape_block(sweeps, dwell, n=5):
    """The bytes of one Kratos spectrum block the reader decodes: the sweep
    count 88 bytes before the end of the "Uninitialized" tag, then hv, the
    kinetic-energy range and the dwell, a transmission table (empty) and the
    ordinates."""
    tag = b"Uninitialized"
    head = struct.pack("<i", sweeps) + b"\x00" * (88 - len(tag) - 4) + tag
    body = struct.pack("<4d", 1486.69, 200.0, 220.0, dwell)
    tf = b"TransFunc.Core.VisionTf" + b"\x00" * 4 + struct.pack("<i", 0)
    return (head + body + tf + struct.pack("<i", n)
            + struct.pack(f"<{n}d", *range(1, n + 1)))


class TestKratosExperiment(unittest.TestCase):
    """The reader of Kratos .experiment files (validated on four real files
    and against HarwellXPS's export of one: sweeps and start times equal in
    144 of 144 regions)."""

    def parser(self, raw):
        from readers.kratos_experiment import EscapeParser
        p = EscapeParser()
        p.raw = raw
        return p

    def test_sweeps_and_a_total_dwell_are_read_from_the_block(self):
        from readers.kratos_experiment import EscapeParser  # noqa: F401
        raw = escape_block(sweeps=8, dwell=0.6, n=800)
        p = self.parser(raw)
        r = Region(name="O KLL", index=0, offset=0)
        self.assertTrue(p._decode_structured(r, 0, len(raw)))
        self.assertEqual(r.extra["n_scans"], 8)
        self.assertTrue(r.extra["dwell_total"])
        # 0.6 s x 800 points is the whole 8 minutes: the dwell is not per sweep
        self.assertAlmostEqual(timing.net_seconds(r), 480.0)
        per_sweep, scans = r.dwell_and_scans()
        self.assertAlmostEqual(per_sweep * scans * r.n_points, 480.0)
        self.assertAlmostEqual(per_sweep, 0.075)

    def test_an_absurd_sweep_count_is_not_believed(self):
        raw = escape_block(sweeps=-3, dwell=0.6)
        r = Region(name="x", index=0, offset=0)
        self.parser(raw)._decode_structured(r, 0, len(raw))
        self.assertNotIn("n_scans", r.extra)

    def test_a_region_takes_the_start_of_its_group(self):
        def stamp(y, mo, d, h, mi, s):
            return struct.pack("<6i", y, mo, d, h, mi, s)
        raw = (b"\x00" * 10 + stamp(2026, 9, 12, 9, 46, 19) + b"\x01" * 40
               + stamp(2026, 9, 12, 9, 48, 53) + b"\x02" * 40)
        p = self.parser(raw)
        self.assertEqual([w for _k, w in p._stamps()],
                         ["2026-09-12 09:46:19", "2026-09-12 09:48:53"])
        self.assertEqual(p._start_for(30), "2026-09-12 09:46:19")
        self.assertEqual(p._start_for(len(raw)), "2026-09-12 09:48:53")
        self.assertEqual(p._start_for(5), "")          # before any record

    def test_a_year_like_number_that_is_not_a_date_is_ignored(self):
        junk = struct.pack("<6i", 2026, 13, 40, 25, 61, 99)   # not a date
        self.assertEqual(self.parser(b"\x00" * 8 + junk)._stamps(), [])

    def test_the_date_shown_carries_the_time_when_it_is_known(self):
        p = self.parser(b"")
        r = Region(name="x", index=0, offset=0)
        r.extra["t_start"] = "2026-09-12 09:48:53"
        self.assertEqual(p.date_for_region(r), "2026-09-12 09:48:53")

    def test_only_starts_are_recorded_so_no_overhead_is_claimed(self):
        a = region(dwell=0.6, points=800, scans=8, mode="",
                   start="2026-09-12 09:48:53", tz="")
        a.extra["dwell_total"] = True
        b = region(dwell=0.6, points=800, scans=8, mode="",
                   start="2026-09-13 16:41:00", tz="")
        b.extra["dwell_total"] = True
        s = timing.summarise([doc(a, b)])
        self.assertEqual(s.net, 960.0)
        self.assertEqual(s.start, dt.datetime(2026, 9, 12, 9, 48, 53))
        self.assertEqual(s.last_start, dt.datetime(2026, 9, 13, 16, 41, 0))
        self.assertIsNone(s.end)
        self.assertIsNone(s.active)
        self.assertIsNone(s.overhead)
        self.assertTrue(any("started" in n for n in s.notes))
        rows = dict(timing.describe(s))
        self.assertEqual(list(rows), ["First start", "Last start",
                                      "Counting time"])
        self.assertNotIn("Last finish", rows)

    def test_a_total_dwell_needs_no_scan_count(self):
        r = region(dwell=0.6, points=800, scans=None, mode="")
        r.extra["dwell_total"] = True
        self.assertAlmostEqual(timing.net_seconds(r), 480.0)


class TestHarwellVamasOfAKratosFile(Tmp):
    """HarwellXPS writes a Kratos file's summed dwell next to the sweeps."""

    def test_the_comment_marks_the_dwell_as_a_total(self):
        r = region(dwell=0.6, points=21, scans=8, mode="")
        r.energy = [280.0 + 0.5 * i for i in range(21)]
        r.photon_energy, r.pass_energy, r.step = 1486.69, 40.0, 0.5
        p = os.path.join(self.dir.name, "k.vms")
        export_vamas([r], p, include_transmission=False)
        with open(p, encoding="latin-1", newline="") as fh:
            lines = fh.read().splitlines()
        i = lines.index("XPS")               # technique: after the comment
        self.assertEqual(lines[i - 1], "0")  # an empty comment block
        lines[i - 1:i] = ["2", "Vendor format : Kratos ESCApe .experiment",
                          "Acquired : 2026-09-12 09:48:53"]
        q = os.path.join(self.dir.name, "harwell.vms")
        with open(q, "w", encoding="latin-1", newline="\r\n") as fh:
            fh.write("\n".join(lines) + "\n")
        back = load_file(q).regions[0]
        self.assertTrue(back.extra.get("dwell_total"))
        self.assertEqual(back.extra["t_start"], "2026-09-12 09:48:53")


class TestExportKeepsTheTotal(Tmp):
    def test_a_total_dwell_is_written_per_sweep(self):
        r = region(dwell=0.6, points=21, scans=8, mode="")
        r.energy = [280.0 + 0.5 * i for i in range(21)]
        r.photon_energy, r.pass_energy, r.step = 1486.69, 40.0, 0.5
        r.extra["dwell_total"] = True
        p = os.path.join(self.dir.name, "t.vms")
        export_vamas([r], p, include_transmission=False)
        back = load_file(p).regions[0]
        self.assertAlmostEqual(back.dwell, 0.075)         # per sweep, as VAMAS
        self.assertEqual(back.extra["n_scans"], 8)
        self.assertNotIn("dwell_total", back.extra)
        self.assertAlmostEqual(timing.net_seconds(back),
                               timing.net_seconds(r))     # same 12.6 s

    def test_a_per_sweep_dwell_is_written_as_it_is(self):
        r = region(dwell=0.05, points=21, scans=10, mode="")
        r.energy = [280.0 + 0.5 * i for i in range(21)]
        r.photon_energy, r.pass_energy, r.step = 1486.68, 50.0, 0.5
        self.assertEqual(r.dwell_and_scans(), (0.05, 10))
        p = os.path.join(self.dir.name, "s.vms")
        export_vamas([r], p, include_transmission=False)
        self.assertAlmostEqual(load_file(p).regions[0].dwell, 0.05)


class TestMethodsText(unittest.TestCase):
    ROWS = [{"Sample": "S", "Region": "C 1s", "Instrument": "K-Alpha+",
             "Anode": "Al Kα (mono)", "Photon energy (eV)": "1486.68",
             "Source power (W)": "72", "Anode voltage (kV)": "12",
             "Emission current (mA)": "6", "X-ray spot (µm)": "400",
             "Pass energy (eV)": "50", "Analyser mode": CAE,
             "Acquisition mode": "Scan", "Scans": "10",
             "BE start (eV)": "290", "BE end (eV)": "280"}]

    def summary(self):
        a = region(start="2026-08-24 08:00:00", end="2026-08-24 10:00:00")
        return timing.summarise([doc(a)])

    def test_source_analyser_and_scans_are_stated(self):
        text = methods.generate(self.ROWS)
        self.assertIn("at a source power of 72 W (12 kV and 6 mA emission).",
                      text)
        self.assertIn("The X-ray spot size was 400 µm.", text)
        self.assertIn("The analyser used constant analyser energy (CAE) mode.",
                      text)
        self.assertIn("Spectra were recorded in scan mode (1).", text)
        self.assertIn("Each spectrum accumulated 10 scans.", text)

    def test_the_timing_sentence(self):
        text = methods.generate(self.ROWS, timing_summary=self.summary())
        self.assertIn("Data were acquired on 2026-08-24 between 08:00 and "
                      "10:00 UTC.", text)
        self.assertIn("The instrument was in use for 2 h 00 min, of which "
                      "2 min 06 s was counting time.", text)

    def test_no_times_no_claim(self):
        s = timing.summarise([doc(region())])
        text = methods.generate(self.ROWS, timing_summary=s)
        self.assertNotIn("Data were acquired on", text)
        self.assertIn("The total counting time was 2 min 06 s.", text)

    def test_unrecorded_facts_are_left_out(self):
        text = methods.generate([{"Sample": "S", "Region": "C 1s"}])
        for word in ("spot", "scans", "analyser used", "in use"):
            self.assertNotIn(word, text)


try:
    import tkinter as tk
    import spectradeck as ee
    from readers.base import SpectrumFile
    HAVE_APP = ee.HAVE_MPL
except Exception:                                   # pragma: no cover
    HAVE_APP = False


@unittest.skipUnless(HAVE_APP, "matplotlib / Tk not available")
class TestInTheApp(unittest.TestCase):
    """The Details panel and the methods text of a real Workspace."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError:
            raise unittest.SkipTest("no display")
        cls.root.withdraw()
        cls.dir = tempfile.mkdtemp()
        cls.path = os.path.join(cls.dir, "a.vgd")
        with open(cls.path, "wb") as fh:
            fh.write(b"stand-in")
        r = region(start="2026-08-24 08:00:00", end="2026-08-24 10:00:00")
        r.photon_energy, r.pass_energy, r.sample = 1486.68, 50.0, "S1"
        r.conditions.update({"X-ray spot (µm)": "400",
                             "Anode voltage (kV)": "12"})
        r.extra["analyser_mode"] = CAE
        f = SpectrumFile()
        f.path, f.format_name, f.regions = cls.path, "Test", [r]
        f.instrument = {"Instrument": "K-Alpha+",
                        "Acquisition software": "Thermo Avantage"}
        f._finish()
        cls.doc, cls._load = f, ee.load_file
        ee.load_file = lambda p: cls.doc
        cls.ws = ee.Workspace(cls.root)
        cls.ws._add_file(cls.path)

    @classmethod
    def tearDownClass(cls):
        ee.load_file = cls._load
        cls.root.destroy()
        import shutil
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_the_details_panel_shows_the_new_facts(self):
        self.ws.sel_regions = list(self.doc.regions)
        self.ws._update_metadata()
        text = self.ws.meta.get("1.0", "end")
        for want in ("X-ray spot (µm)", "400", "Analyser mode", "Scans",
                     "Counting time", "Acquisition software",
                     "Thermo Avantage", "Run started"):
            self.assertIn(want, text)

    def test_the_methods_text_says_when_and_how_long(self):
        text = self.ws.methods_generated()
        self.assertIn("The X-ray spot size was 400 µm.", text)
        self.assertIn("The instrument was in use for 2 h 00 min", text)


if __name__ == "__main__":
    unittest.main()
