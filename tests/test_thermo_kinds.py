"""Avantage DataSpaces that are not one plain spectrum: SnapMap cubes, camera
images, value tables and depth profiles, and the binary axis-type codes.

Synthetic ``.avg`` dumps are built here; the two byte strings are real
``VGSpaceAxes`` streams captured from a ``.vgd`` (a SnapMap and a plain scan).
"""

import os
import struct
import sys
import tempfile
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from readers import load_file  # noqa: E402
from readers.imaging import encode_png, unpack_rgb  # noqa: E402
from readers.thermo_avg import (AXIS_CODES, DataSpace,  # noqa: E402
                                dataspace_kind)
from readers.thermo_vgd import parse_space_axes  # noqa: E402
import snapmap  # noqa: E402

try:
    import numpy as np
except ImportError:                                    # pragma: no cover
    np = None

HEADER = """;Dump of DataSpace 'F:\\x\\{title}.VGD'
$FORMAT=4
$PROPERTIES=SUM
DS_EXT_SUPROPID_TITLE       : VT_BSTR = '{title}'
DS_EXT_SUPROPID_CREATED     : VT_DATE = 24/8/2026   19:10:01
$PROPERTIES=STD
DS_GEPROPID_INSTRUMENT                      : VT_BSTR = 'K-Alpha+'
DS_GEPROPID_VALUE_TYPE                      : VT_I4   = {vtype}
DS_GEPROPID_VALUE_LABEL                     : VT_BSTR = '{vlabel}'
DS_GEPROPID_VALUE_UNIT                      : VT_BSTR = '{vunit}'
DS_SOPROPID_MONO                            : VT_BOOL = True
DS_SOPROPID_ENERGY                          : VT_R4   = 1486.680054
DS_STPROPID_POS_X                           : VT_I4   = 22855600
DS_STPROPID_POS_Y                           : VT_I4   = 44677100
DS_ANPROPID_PASS                            : VT_R4   = 150.000000
"""


def dump(title, axes, data_axes, blocks, vtype=11, vlabel="Counts", vunit=""):
    out = [HEADER.format(title=title, vtype=vtype, vlabel=vlabel, vunit=vunit)]
    out.append("$DATAAXES=%d,#empty#" % len(data_axes))
    for i, (s, e, n) in enumerate(data_axes):
        out.append("    %d=  %d, %d, %d" % (i, s, e, n))
    out.append("$SPACEAXES=%d" % len(axes))
    for i, (start, width, n, typ, lin, sym, unit, label) in enumerate(axes):
        out.append("    %d= %f, %f, %d, %s, %s, '%s', '%s', '%s'"
                   % (i, start, width, n, typ, lin, sym, unit, label))
    for spec, labels, values in blocks:
        out += labels
        out.append("$DATA=*" + "".join("," + str(x) for x in spec))
        for k in range(0, len(values), 4):
            out.append("LIST@ %3d= %s" % (k, ", ".join(
                "%.6f" % v for v in values[k:k + 4])))
    return "\n".join(out) + "\n"


class Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def write(self, name, text):
        p = os.path.join(self.dir.name, name)
        with open(p, "w", encoding="latin-1", newline="") as fh:
            fh.write(text)
        return p


def snapmap_text(nx=3, ny=2, ne=4):
    """Pixel (ix, iy) holds the value 100*iy + 10*ix + channel."""
    axes = [(1188.0, 0.5, ne, "ENERGY", "LINEAR", "E", "eV", "Energy"),
            (-20.0, 20.0, nx, "X", "LINEAR", "X", "\xb5m", "X"),
            (-10.0, 20.0, ny, "Y", "LINEAR", "Y", "\xb5m", "Y")]
    data_axes = [(0, ne - 1, 1), (0, nx - 1, 1), (0, ny - 1, 1)]
    blocks = []
    for iy in range(ny):
        for ix in range(nx):
            vals = [100 * iy + 10 * ix + c for c in range(ne)]
            blocks.append(((ix, iy), [], vals))
    return dump("C1s SnapMap", axes, data_axes, blocks)


class TestSnapMap(Tmp):
    def load(self):
        return load_file(self.write("C1s SnapMap.avg", snapmap_text()))

    def test_is_one_summed_region_with_a_cube(self):
        f = self.load()
        self.assertEqual(f.kind, "map")
        self.assertEqual(len(f.regions), 1)
        r = f.regions[0]
        self.assertEqual(r.name, "C 1s")
        self.assertIn("SnapMap", r.note)
        cube = r.extra["cube"]
        self.assertEqual((cube.nx, cube.ny, cube.n_energy), (3, 2, 4))
        self.assertEqual(r.counts, cube.total())
        # channel 0: sum over 6 pixels of (100*iy + 10*ix)
        self.assertEqual(r.counts[0], sum(100 * iy + 10 * ix
                                          for iy in range(2) for ix in range(3)))
        self.assertAlmostEqual(cube.stage_x_mm, 22.8556)
        self.assertAlmostEqual(cube.stage_y_mm, 44.6771)

    def test_pixel_spectra_and_geometry(self):
        cube = self.load().regions[0].extra["cube"]
        self.assertEqual(cube.spectrum_at(2, 1), [120.0, 121.0, 122.0, 123.0])
        self.assertEqual((cube.x_of(0), cube.x_of(2)), (-20.0, 20.0))
        self.assertEqual((cube.y_of(0), cube.y_of(1)), (-10.0, 10.0))
        self.assertEqual(cube.pixel_at(20.0, 10.0), (2, 1))
        self.assertEqual(cube.pixel_at(-19.0, -9.0), (0, 0))
        self.assertIsNone(cube.pixel_at(80.0, 0.0))
        left, right, bottom, top = cube.extent()
        self.assertEqual((left, right, bottom, top), (-30.0, 30.0, 20.0, -20.0))

    @unittest.skipUnless(np, "numpy needed for map images")
    def test_image_window_and_roi(self):
        cube = self.load().regions[0].extra["cube"]
        whole = cube.image()
        self.assertEqual(whole.shape, (2, 3))
        self.assertEqual(whole[1, 2], 4 * 120 + (0 + 1 + 2 + 3))
        e = cube.energy
        one = cube.image(e[1], e[1])                    # a single channel
        self.assertEqual(one[1, 2], 121.0)
        mask = cube.rect_mask(-25, -15, 0, 0)           # pixels (0..1, 0)
        self.assertEqual(mask.sum(), 2)
        self.assertEqual(cube.roi_spectrum(mask),
                         [sum(x) for x in zip(cube.spectrum_at(0, 0),
                                              cube.spectrum_at(1, 0))])
        with self.assertRaises(ValueError):
            cube.roi_spectrum(np.zeros((3, 3), bool))

    @unittest.skipUnless(np, "numpy needed for map images")
    def test_background_removes_a_sloping_baseline(self):
        ne = 16
        data = snapmap.build(list(range(ne)), 2, 2, 0.0, 1.0, 0.0, 1.0,
                             [(((ix, iy), [3.0 * c + 7 for c in range(ne)]))
                              for ix in range(2) for iy in range(2)])
        self.assertGreater(data.image()[0, 0], 100)
        self.assertAlmostEqual(data.image(background=True)[0, 0], 0.0, places=6)


class TestKinds(Tmp):
    def test_image_is_a_png_blob_not_a_spectrum(self):
        w, h = 4, 3
        px = [(x * 20) | ((y * 30) << 8) | ((10 * (x + y)) << 16)   # B<<16|G<<8|R
              for y in range(h) for x in range(w)]
        axes = [(0.0, 4.5, w, "X", "LINEAR", "X", "\xb5m", "X"),
                (0.0, 4.0, h, "Y", "LINEAR", "Y", "\xb5m", "Y")]
        blocks = [((y,), [], px[y * w:(y + 1) * w]) for y in range(h)]
        text = dump("Pt #001a", axes, [(0, w - 1, 1), (0, h - 1, 1)], blocks,
                    vtype=13, vlabel="RGB")
        f = load_file(self.write("Pt 001a.avg", text))
        self.assertEqual(f.kind, "image")
        self.assertEqual(f.regions, [])
        blob = f.images[0]
        self.assertEqual(blob.fmt, "png")
        self.assertEqual(blob.calib["width"], 4)
        self.assertAlmostEqual(blob.calib["um_per_px_x"], 4.5)
        self.assertAlmostEqual(blob.calib["um_per_px_y"], 4.0)
        self.assertAlmostEqual(blob.calib["x_mm"], 22.8556)
        png = f.extract_jpeg(blob)
        self.assertTrue(png.startswith(b"\x89PNG"))
        # decode it again by hand: filter byte + RGB per row
        idat = b""
        pos = 8
        while pos < len(png):
            n = struct.unpack(">I", png[pos:pos + 4])[0]
            if png[pos + 4:pos + 8] == b"IDAT":
                idat += png[pos + 8:pos + 8 + n]
            pos += 12 + n
        raw = zlib.decompress(idat)
        self.assertEqual(len(raw), h * (1 + 3 * w))
        r0 = raw[1:1 + 3 * w]
        for x in range(w):
            self.assertEqual(tuple(r0[3 * x:3 * x + 3]), (x * 20, 0, 10 * x))

    def test_value_table_keeps_its_values(self):
        axes = [(1.0, 1.0, 3, "POSITION", "LINEAR", "Pos", "", "Position"),
                (5000.0, 0.0, 3, "X", "NON-LINEAR", "X", "\xb5m", "X"),
                (6000.0, 0.0, 3, "Y", "NON-LINEAR", "Y", "\xb5m", "Y")]
        text = dump("AutoHeight Values", axes, [(0, 2, 3)],
                    [((), [], [31.0, 32.5, 33.0])],
                    vtype=21, vlabel="Z Height", vunit="nm")
        f = load_file(self.write("AutoPos.avg", text))
        self.assertEqual(f.kind, "table")
        self.assertEqual(f.regions, [])
        self.assertEqual(f.value_table["label"], "Z Height")
        self.assertEqual(f.value_table["unit"], "nm")
        self.assertEqual([r[3] for r in f.value_table["rows"]],
                         [31.0, 32.5, 33.0])

    def test_depth_profile_takes_etch_time_from_the_time_axis(self):
        ne = 4
        axes = [(1188.0, 0.5, ne, "ENERGY", "LINEAR", "E", "eV", "Energy"),
                (0.0, 5.0, 3, "ETCHTIME", "NON-LINEAR", "EtchTime", "s",
                 "Etch Time"),
                (0.0, 1.0, 3, "ETCHLEVEL", "LINEAR", "EtchLevel", "",
                 "Etch Level")]
        times, blocks = [0.0, 5.0, 12.5], []
        for k, t in enumerate(times):
            labels = ["$AXISVALUE= DATAXIS=1 SPACEAXIS=1 LABEL='Etch Time' "
                      "POINT=%d VALUE=%f;" % (k, t),
                      "$AXISVALUE= DATAXIS=1 SPACEAXIS=2 LABEL='Etch Level' "
                      "POINT=%d VALUE=%f;" % (k, k)]
            blocks.append(((k,), labels, [10.0 * k + c for c in range(ne)]))
        f = load_file(self.write("Al2p Snap.avg", dump(
            "Al2p Snap", axes, [(0, ne - 1, 1), (0, 2, 2)], blocks)))
        self.assertEqual(f.kind, "levels")
        self.assertEqual([r.etch_level for r in f.regions], [0, 1, 2])
        self.assertEqual([r.etch_time for r in f.regions], times)
        self.assertEqual(f.depth_profile["total_etch_time"], 12.5)

    def test_single_scan_takes_the_stage_position(self):
        axes = [(1188.0, 0.5, 4, "ENERGY", "LINEAR", "E", "eV", "Energy")]
        f = load_file(self.write("C1s Scan.avg", dump(
            "C1s Scan", axes, [(0, 3, 1)], [((), [], [1, 2, 3, 4])])))
        self.assertEqual(f.kind, "spectrum")
        r = f.regions[0]
        self.assertAlmostEqual(r.pos_x, 22.8556)
        self.assertAlmostEqual(r.pos_y, 44.6771)
        self.assertEqual(f.sample_positions(), {})       # no stage-map tab

    def test_an_empty_dataspace_is_reported_not_crashed_on(self):
        text = HEADER.format(title="AutoPos", vtype=21, vlabel="Z Height",
                             vunit="nm") + "$DATAAXES=0,#empty#\n"
        with self.assertRaisesRegex(ValueError, "empty"):
            load_file(self.write("empty.avg", text))

    def test_kind_of_a_bare_dataspace(self):
        ds = DataSpace()
        self.assertEqual(dataspace_kind(ds), "other")


class TestViewerHelpers(unittest.TestCase):
    def cube(self, peak_at=20, ne=40):
        e = [300.0 - 0.25 * i for i in range(ne)]           # descending BE
        spec = [5.0 + 100.0 * max(0.0, 1 - abs(i - peak_at) / 4.0)
                for i in range(ne)]
        blocks = [(((ix, iy), spec)) for ix in range(2) for iy in range(2)]
        return snapmap.build(e, 2, 2, 0.0, 10.0, 0.0, 10.0, blocks)

    @unittest.skipUnless(np, "numpy needed")
    def test_default_window_brackets_the_strongest_peak(self):
        cube = self.cube()
        lo, hi = snapmap.default_window(cube)
        centre = cube.energy[20]
        self.assertLess(lo, centre)
        self.assertGreater(hi, centre)
        self.assertLess(hi - lo, 4.0)              # the peak, not the whole scan
        self.assertGreaterEqual(hi - lo, 2.0 - 1e-9)   # but never a sliver

    @unittest.skipUnless(np, "numpy needed")
    def test_a_rising_background_is_not_taken_for_the_peak(self):
        ne = 60
        e = [950.0 - 0.5 * i for i in range(ne)]
        # the background climbs towards the high-BE end (channel 0) and is
        # higher there than the peak at channel 40 ever gets
        spec = [40.0 + 0.9 * (ne - i) + (25.0 * max(0.0, 1 - abs(i - 40) / 3.0))
                for i in range(ne)]
        spec = list(reversed(sorted(spec[:10]))) + spec[10:]      # keep the edge high
        cube = snapmap.build(e, 2, 2, 0.0, 1.0, 0.0, 1.0,
                             [((ix, iy), spec) for ix in range(2)
                              for iy in range(2)])
        self.assertGreater(max(spec[:10]), max(spec[35:45]))       # the trap
        lo, hi = snapmap.default_window(cube)
        self.assertLess(lo, e[40])
        self.assertGreater(hi, e[40])
        self.assertLess(hi - lo, 5.0)

    @unittest.skipUnless(np, "numpy needed")
    def test_no_peak_means_the_whole_range(self):
        ne = 40
        e = [300.0 - 0.25 * i for i in range(ne)]
        flat = [10.0] * ne
        cube = snapmap.build(e, 2, 2, 0.0, 1.0, 0.0, 1.0,
                             [((ix, iy), flat) for ix in range(2)
                              for iy in range(2)])
        self.assertEqual(snapmap.default_window(cube), (min(e), max(e)))

    @unittest.skipUnless(np, "numpy needed")
    def test_colour_range_ignores_a_hot_pixel(self):
        img = np.full((20, 20), 10.0)
        img[0, 0] = 1e6
        lo, hi = snapmap.colour_range(img)
        # nearly all pixels identical: fall back to the full span, which is
        # the only place the sparse feature shows
        self.assertEqual((lo, hi), (10.0, 1e6))
        self.assertEqual(snapmap.colour_range(np.full((4, 4), 7.0)), (7.0, 8.0))
        img += np.arange(400).reshape(20, 20) * 0.01
        lo, hi = snapmap.colour_range(img)
        self.assertLess(hi, 100.0)
        self.assertGreater(hi, lo)
        self.assertEqual(snapmap.colour_range(np.array([np.nan])), (0.0, 1.0))

    @unittest.skipUnless(np, "numpy needed")
    def test_csv_grid_has_axes_and_values(self):
        cube = self.cube()
        text = snapmap.to_csv_grid(cube, cube.image())
        lines = text.strip().splitlines()
        self.assertEqual(lines[0], "Y/X (um),0,10")
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[1].startswith("0,"))


# Real VGSpaceAxes streams (Avantage's MFC serialisation): a 128 x 100 x 100
# SnapMap, and a 301-point scan.
CUBE_AXES = bytes.fromhex(
    "00 00 02 00 03 00 00 00 02 00 00 00 00 00 02 00 00 00 00 00 02 00 00 00 "
    "00 00 80 00 00 00 dc a0 93 31 b1 90 92 40 d4 2b 65 19 e2 70 c4 3f 01 01 "
    "00 00 00 02 00 00 00 00 00 02 00 00 00 00 00 02 00 00 00 00 00 64 00 00 "
    "00 00 00 00 00 00 f0 8e c0 00 00 00 00 00 00 34 40 01 03 00 00 00 02 00 "
    "00 00 00 00 02 00 00 00 00 00 02 00 00 00 00 00 64 00 00 00 00 00 00 00 "
    "00 f0 8e c0 00 00 00 00 00 00 34 40 01 04 00 00 00")
SINGLE_AXES = bytes.fromhex(
    "00 00 02 00 01 00 00 00 02 00 00 00 00 00 02 00 00 00 00 00 02 00 00 00 "
    "00 00 2d 01 00 00 66 66 66 66 66 8a 92 40 9a 99 99 99 99 99 b9 3f 01 01 "
    "00 00 00")


class TestAxisCodes(unittest.TestCase):
    def test_types_come_from_the_stream(self):
        axes = parse_space_axes(CUBE_AXES, [128, 100, 100])
        self.assertEqual([AXIS_CODES[a["code"]] for a in axes],
                         ["ENERGY", "X", "Y"])
        self.assertEqual([a["n"] for a in axes], [128, 100, 100])
        self.assertAlmostEqual(axes[0]["start"], 1188.173041, places=5)
        self.assertEqual(axes[1]["start"], -990.0)
        self.assertEqual(axes[1]["width"], 20.0)
        self.assertTrue(all(a["linear"] for a in axes))

    def test_single_axis(self):
        (a,) = parse_space_axes(SINGLE_AXES, [301])
        self.assertEqual(AXIS_CODES[a["code"]], "ENERGY")
        self.assertEqual(a["n"], 301)


class TestImaging(unittest.TestCase):
    def test_png_round_trip_of_packed_pixels(self):
        px = [0x0000FF, 0x00FF00, 0xFF0000, 0x123456]      # BGR-packed
        rgb = unpack_rgb(px)
        self.assertEqual(rgb, bytes([255, 0, 0, 0, 255, 0, 0, 0, 255,
                                     0x56, 0x34, 0x12]))
        png = encode_png(2, 2, rgb)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        with self.assertRaises(ValueError):
            encode_png(3, 3, rgb)


if __name__ == "__main__":
    unittest.main()
