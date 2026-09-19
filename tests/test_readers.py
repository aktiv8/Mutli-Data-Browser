"""Reader regression tests. Run:  python -m unittest discover tests

Each format is exercised with a small synthetic file built here, so the tests
need no instrument data. (``test_corpus.py`` checks real files if you point
XPS_CORPUS at a folder of them.)
"""

import math
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from readers import load_file, reader_for, UnsupportedFormat, Region  # noqa: E402
from readers.base import (canon_region_name, guess_region_name,  # noqa: E402
                          kv_from_lines, clean_text)
from exporters import export_vamas  # noqa: E402


def peak(n, lo, hi, centre, amp=1000.0):
    e = [hi - i * (hi - lo) / (n - 1) for i in range(n)]      # descending BE
    y = [50 + amp * math.exp(-((x - centre) ** 2) / 2) for x in e]
    return e, y


class Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def path(self, name):
        return os.path.join(self.dir.name, name)

    def write(self, name, data):
        mode = "wb" if isinstance(data, bytes) else "w"
        with open(self.path(name), mode, **({} if mode == "wb" else
                                            {"newline": "", "encoding": "latin-1"})) as fh:
            fh.write(data)
        return self.path(name)


class TestNames(unittest.TestCase):
    def test_canonical_region_names(self):
        self.assertEqual(canon_region_name("C1s"), "C 1s")
        self.assertEqual(canon_region_name("Cu2p3/2"), "Cu 2p3/2")
        self.assertEqual(canon_region_name("Fe 2p"), "Fe 2p")
        for s in ("XPS Survey", "wide/1", "SUR", "Survey"):
            self.assertEqual(canon_region_name(s), "Survey")
        self.assertEqual(canon_region_name("Not Specified"), "")

    def test_wide_core_level_is_a_survey(self):
        wide = [0.0, 1300.0]
        self.assertEqual(guess_region_name("C 1s", wide), "Survey")
        self.assertEqual(guess_region_name("C 1s", [280.0, 295.0]), "C 1s")

    def test_kv_from_lines(self):
        kv = kv_from_lines(["Step(meV): 700.0    Dwell(ms): 76   Sweeps: 2",
                            "Lens Mode:Hybrid", "no colon here"])
        self.assertEqual(kv["dwell(ms)"], "76")
        self.assertEqual(kv["lens mode"], "Hybrid")
        self.assertEqual(clean_text(" Not Specified "), "")


class TestVamas(Tmp):
    def _regions(self):
        out = []
        for s, c in (("S1", 285.0), ("S2", 286.0)):
            e, y = peak(101, 280, 295, c)
            out.append(Region(name="C 1s", index=len(out), offset=0, energy=e,
                              counts=y, decodable=True, sample=s,
                              photon_energy=1486.6, pass_energy=20.0,
                              dwell=0.1, step=0.15, anode="Al Ka"))
        e, y = peak(61, 525, 540, 532)
        out.append(Region(name="O 1s", index=2, offset=0, energy=e, counts=y,
                          decodable=True, sample="S1", photon_energy=1486.6,
                          pass_energy=20.0, dwell=0.1, step=0.25))
        return out

    def test_round_trip_through_our_exporter(self):
        regs = self._regions()
        p = self.path("out.vms")
        export_vamas(regs, p, include_transmission=False)
        back = load_file(p)
        self.assertEqual(back.format_name, "VAMAS (ISO 14976)")
        self.assertEqual(len(back.regions), 3)
        for a, b in zip(regs, back.regions):
            self.assertEqual(a.n_points, b.n_points)
            self.assertEqual(b.name, a.name)
            self.assertEqual(b.energy_label, "Binding Energy")
            self.assertAlmostEqual(b.photon_energy, 1486.6, places=3)
            self.assertAlmostEqual(b.pass_energy, 20.0)
            self.assertLess(max(abs(x - y) for x, y in zip(a.energy, b.energy)), 1e-3)
            self.assertLess(max(abs(x - y) for x, y in zip(a.counts, b.counts)), 1e-3)

    def test_transmission_is_read_as_second_variable(self):
        regs = self._regions()[:1]
        r = regs[0]
        ke = [r.photon_energy - x for x in r.energy]
        r.tf_ke = [min(ke) - 5, max(ke) + 5]
        r.tf_values = [1.0, 0.5]
        p = self.path("tf.vms")
        export_vamas(regs, p, include_transmission=True)
        back = load_file(p).regions[0]
        self.assertIsNotNone(back.transmission())
        self.assertEqual(len(back.transmission()), back.n_points)

    def test_truncated_file_keeps_the_good_blocks(self):
        regs = self._regions()
        p = self.path("cut.vms")
        export_vamas(regs, p, include_transmission=False)
        with open(p, encoding="latin-1", newline="") as fh:
            text = fh.read()
        cut = text[:int(len(text) * 0.75)]
        self.write("cut2.vms", cut)
        back = load_file(self.path("cut2.vms"))
        self.assertGreaterEqual(len(back.regions), 1)
        self.assertTrue(back.warnings)

    def test_not_vamas(self):
        p = self.write("junk.vms", "hello\nworld\n")
        with self.assertRaises(Exception):
            load_file(p)


AVG_TEMPLATE = """;================
;Dump of DataSpace 'F:\\x\\{title}.VGD'
; on 12/5/2008 at 14:26:48
;================
$FORMAT=3
$PROPERTIES=SUM
DS_EXT_SUPROPID_TITLE       : VT_BSTR = '{title}'
DS_EXT_SUPROPID_CREATED     : VT_DATE = 12/5/2008   17:34:00
$PROPERTIES=STD
DS_GEPROPID_INSTRUMENT                      : VT_BSTR = 'Alpha'
DS_GEPROPID_VALUE_LABEL                     : VT_BSTR = 'Counts'
DS_SOPROPID_MONO                            : VT_BOOL = True
DS_SOPROPID_ENERGY                          : VT_R4   = 1486.680054
DS_SOPROPID_VOLTAGE                         : VT_R4   = 12000.000000
DS_SOPROPID_CURRENT                         : VT_R4   = 0.002100
DS_ACPROPID_ACQ_TIME                        : VT_R4   = 0.050000
DS_ACPROPID_EV_SCALE                        : VT_I2   = 1
DS_ANPROPID_PASS                            : VT_R4   = 50.000000
DS_ANPROPID_LENS_MODE_NAME                  : VT_BSTR = 'Standard'
$DATAAXES=1,#empty#
    0=        0,        7,          1
$SPACEAXES=1
    0=    1188.600000,       0.100000,        8,  ENERGY,   LINEAR,  'E',   'eV',    'Energy'
$DATA=*
{rows}
"""


class TestThermoAvg(Tmp):
    def test_energy_axis_is_kinetic_and_converted(self):
        vals = [100 + i for i in range(8)]
        rows = "\n".join(
            "LIST@ %3d=  %s" % (k, ",  ".join("%.6f" % v for v in vals[k:k + 4]))
            for k in (0, 4))
        p = self.write("C1s Scan.avg", AVG_TEMPLATE.format(title="C1s Scan",
                                                          rows=rows))
        f = load_file(p)
        r = f.regions[0]
        self.assertEqual(r.name, "C 1s")
        self.assertEqual(r.energy_label, "Binding Energy")
        self.assertAlmostEqual(r.photon_energy, 1486.68, places=3)
        self.assertAlmostEqual(r.energy[0], 1486.68 - 1188.6, places=6)
        self.assertAlmostEqual(r.energy[-1], 1486.68 - 1189.3, places=6)
        self.assertEqual(r.counts, [float(v) for v in vals])
        self.assertEqual(r.pass_energy, 50.0)
        self.assertEqual(r.date, "2008-05-12 17:34:00")            # D/M/Y
        self.assertAlmostEqual(float(r.conditions["X-ray Power"].split()[0]), 25.2, 1)

    def test_header_only_dump_is_no_data_not_an_error(self):
        rows = "\n".join("LIST@ %3d=  #empty#,  #empty#,  #empty#,  #empty#"
                         % k for k in (0, 4))
        f = load_file(self.write("Empty.avg", AVG_TEMPLATE.format(
            title="O1s Scan", rows=rows)))
        self.assertFalse(f.regions[0].decodable)
        self.assertIn("Header only", f.regions[0].note)


class TestPhiSpe(Tmp):
    def test_multi_region_layout(self):
        defs = [("C1s", 6, 5, -0.5, 290.0, 1.5, 23.5),
                ("Si2p", 14, 4, -0.5, 104.0, 0.5, 23.5)]
        head = ["SOFH", "Technique: XPS", "FileDesc: test",
                "XraySource: Al 1486.6 mono", "XrayPower: 25.3W",
                "AnalyserWorkFcn: 4.2 eV", "NoSpectralReg: %d" % len(defs)]
        for i, (n, z, npts, step, start, dwell, pe) in enumerate(defs, 1):
            head.append("SpectralRegDef: %d 1 %s %d %d %.3f %.3f %.3f %.3f "
                        "%.3f %.3f %.2f none" % (i, n, z, npts, step, start,
                                                 start + step * (npts - 1), start,
                                                 start + step * (npts - 1), dwell, pe))
        head += ["NoSpatialArea: 1", "EOFH"]
        blob = "\r\n".join(head).encode("latin-1") + b"\r\n"
        data = [[10.0 + i + 100 * k for i in range(d[2])]
                for k, d in enumerate(defs)]
        blob += struct.pack("<4i", 1, len(defs), 96 * len(defs), 16)
        blob += b"\0" * (96 * len(defs))
        for col in data:
            blob += struct.pack("<%dd" % len(col), *col)
        f = load_file(self.write("t.SPE", blob))
        self.assertEqual([r.name for r in f.regions], ["C 1s", "Si 2p"])
        self.assertEqual(f.regions[1].counts, data[1])
        self.assertAlmostEqual(f.regions[0].energy[0], 290.0)
        self.assertAlmostEqual(f.regions[0].energy[-1], 288.0)
        self.assertEqual(f.regions[0].photon_energy, 1486.6)
        self.assertEqual(f.regions[1].dwell, 0.5)
        self.assertEqual(f.regions[0].count_units, "counts/s")

    def test_wrong_length_is_rejected(self):
        blob = b"SOFH\r\nNoSpectralReg: 1\r\nSpectralRegDef: 1 1 C1s 6 50 -0.1 " \
               b"290 285 290 285 1.0 20 none\r\nEOFH\r\n" + b"\0" * 40
        with self.assertRaises(ValueError):
            load_file(self.write("bad.spe", blob))


class TestScienta(Tmp):
    def test_regions_and_units(self):
        e = [545.0 - 0.5 * i for i in range(6)]
        y = [100.0 + i for i in range(6)]
        txt = ["[Info]", "Number of Regions=1", "Version=1.3.1", "",
               "[Region 1]", "Region Name=O1s",
               "Dimension 1 name=Binding Energy [eV]", "Dimension 1 size=6",
               "Dimension 1 scale=" + " ".join("%.5f" % x for x in e), "",
               "[Info 1]", "Excitation Energy=700.0", "Pass Energy=100",
               "Step Time=200", "Number of Sweeps=20", "Lens Mode=Transmission",
               "Date=2011-08-23", "Time=22:22:44", "", "[Data 1]"]
        txt += [" %.6E  %.6E" % (a, b) for a, b in zip(e, y)]
        f = load_file(self.write("s.txt", "\n".join(txt) + "\n"))
        r = f.regions[0]
        self.assertEqual(r.name, "O 1s")
        self.assertEqual(r.energy, e)
        self.assertEqual(r.counts, y)
        self.assertEqual(r.photon_energy, 700.0)
        self.assertAlmostEqual(r.dwell, 0.2)
        self.assertEqual(r.date, "2011-08-23 22:22:44")

    def test_detector_columns_are_summed(self):
        txt = ["[Info]", "Number of Regions=1", "", "[Region 1]",
               "Region Name=Au4f", "Dimension 1 name=Binding Energy [eV]",
               "Dimension 1 size=3", "Dimension 1 scale=90 89 88", "",
               "[Info 1]", "Excitation Energy=700", "", "[Data 1]",
               "90 1 2 3", "89 4 5 6", "88 7 8 9"]
        r = load_file(self.write("d.txt", "\n".join(txt))).regions[0]
        self.assertEqual(r.counts, [6.0, 15.0, 24.0])
        self.assertIn("summed", r.note)


KAL = """Dataset filename          = t.dset
Object name               = hy160/1
   1 Technique                 = F_XPS
   2 Scan type                 = F_SPECTRUM
   3 Spectrum scan start       = 100 eV
   4 Spectrum scan step size   = 2 eV
   5 Abscissa label            = Kinetic Energy
   7 Dwell time                = 1 seconds
   9 Ordinate units            = Counts
  12 Ordinate values           = {10, 11,
12, 13}
  42 Pass energy               = 160 eV
 151 Date Acquired             = 98/07/07 19:11:35
3053 Xray Gun Anode            = F_MONO_ANODE
3080 Xray Reference Energy     = F_REFER_TO_XRAY_AG
3113 Chemical symbol or formula = Mo
3114 Transition or charge state = 3d
5587 Transmission Function Object (ke,t) = {
    5615 Transmission Function Kinetic Energy = {100, 110}
    5616 Transmission Function Value = {1.0, 0.5}
}
"""


class TestKratosKal(Tmp):
    def test_object_fields(self):
        f = load_file(self.write("t.kal", KAL))
        r = f.regions[0]
        self.assertEqual(r.name, "Mo 3d")
        self.assertEqual(r.counts, [10.0, 11.0, 12.0, 13.0])          # multi-line list
        self.assertAlmostEqual(r.photon_energy, 2984.2)
        self.assertAlmostEqual(r.energy[0], 2984.2 - 100)
        self.assertEqual(r.date, "1998-07-07 19:11:35")
        self.assertEqual(r.tf_ke, [100.0, 110.0])
        self.assertEqual(r.pass_energy, 160.0)


class TestRegistry(Tmp):
    def test_content_sniffing_beats_extension(self):
        e, y = peak(21, 280, 290, 285)
        p = self.path("real.vms")
        export_vamas([Region(name="C 1s", index=0, offset=0, energy=e, counts=y,
                             decodable=True, photon_energy=1486.6, step=0.5,
                             pass_energy=20, dwell=0.1)], p,
                     include_transmission=False)
        q = self.path("renamed.dat")
        os.replace(p, q)
        self.assertEqual(reader_for(q).format_name, "VAMAS (ISO 14976)")

    def test_unknown_file(self):
        with self.assertRaises(UnsupportedFormat):
            reader_for(self.write("x.bin", b"\x00\x01\x02"))


if __name__ == "__main__":
    unittest.main()
