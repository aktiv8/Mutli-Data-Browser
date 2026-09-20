"""The offline HTML data browser: payload building, encoding, the page it is
written into, and (with Node installed) the JavaScript against Python results.

Run:  python -m unittest discover tests
"""

import base64
import copy
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zlib

ROOT =os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import annotations  # noqa: E402
import exporters  # noqa: E402
import holder  # noqa: E402
import htmlbrowser as hb  # noqa: E402
import plots  # noqa: E402
import themes  # noqa: E402
from readers import ImageBlob, Region, SpectrumFile  # noqa: E402

try:
    from PIL import Image
    HAVE_PIL = True
except Exception:
    HAVE_PIL = False

sys.path.insert(0, os.path.join(ROOT, "tests"))
try:
    from test_casafit import fitted_region
    HAVE_FIT = True
except Exception:
    HAVE_FIT = False


def region(name="C 1s", sample="S1", n=41, lo=280.0, hi=292.0, peak=286.0,
           level=None, etch=None, scale=1.0, hv=1486.6, regular=True):
    e = [hi - i * (hi - lo) / (n - 1) for i in range(n)]
    if not regular:
        e = [x + (0.013 if i % 3 == 0 else 0.0) for i, x in enumerate(e)]
    c = [scale * (100 + 900 * 2.718 ** (-((x - peak) / 1.0) ** 2))
         for x in e]
    return Region(name=name, index=0, offset=0, energy=e, counts=c,
                  decodable=True, sample=sample, photon_energy=hv,
                  pass_energy=20.0, dwell=0.1, step=(hi - lo) / (n - 1),
                  etch_level=level, etch_time=etch, source="a.vms",
                  count_units="counts/s")


def doc(path, regions, positions=None, images=None, instrument=None):
    f = SpectrumFile()
    f.path = path
    f.format_name = "Test"
    f.regions = regions
    f.instrument = instrument or {"Instrument": "Test Spec"}
    f.images = images or []
    f._sample_pos = positions or {}
    f._finish()
    return f


def jpeg(w=64, h=48):
    import io
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (120, 90, 60)).save(buf, "JPEG")
    return buf.getvalue()


class TestNumbers(unittest.TestCase):
    def test_round_sig(self):
        self.assertEqual(hb.round_sig(1234.56789012), 1234.568)
        self.assertEqual(hb.round_sig(0), 0)
        self.assertEqual(hb.round_sig(-0.000123456789), -0.0001234568)
        self.assertIsNone(hb.round_sig(float("nan")))

    def test_regular_axis_is_packed_as_start_step_count(self):
        xs = [292.0 - i * 0.3 for i in range(41)]
        ax = hb.pack_axis(xs)
        self.assertEqual(set(ax), {"x0", "dx", "n"})
        self.assertEqual(ax["n"], 41)
        back = [ax["x0"] + ax["dx"] * i for i in range(ax["n"])]
        for a, b in zip(xs, back):
            self.assertAlmostEqual(a, b, 5)

    def test_irregular_axis_is_kept_as_a_list(self):
        xs = [1.0, 2.0, 2.5, 4.0, 4.1]
        self.assertEqual(hb.pack_axis(xs), xs)
        self.assertEqual(hb.pack_axis([1.0, 2.0]), [1.0, 2.0])

    def test_jpeg_size(self):
        if not HAVE_PIL:
            self.skipTest("Pillow not installed")
        self.assertEqual(hb.jpeg_size(jpeg(64, 48)), (64, 48))
        self.assertEqual(hb.jpeg_size(jpeg(301, 17)), (301, 17))
        self.assertIsNone(hb.jpeg_size(b"not a jpeg"))
        self.assertIsNone(hb.jpeg_size(b"\xff\xd8\xff\xe0\x00"))


def survey(n=1101, hv=1486.6):
    """A wide scan with a strong C 1s (285 eV) and O 1s (532 eV)."""
    e = [1100.0 - i * 1100.0 / (n - 1) for i in range(n)]
    c = [50 + 900 * 2.718 ** (-((x - 285.0) / 2.0) ** 2)
         + 1500 * 2.718 ** (-((x - 532.0) / 2.0) ** 2) for x in e]
    return Region(name="Survey", index=0, offset=0, energy=e, counts=c,
                  decodable=True, sample="S1", photon_energy=hv,
                  pass_energy=160.0, dwell=0.1, step=1.0, source="a.vms",
                  count_units="counts/s")


class TestElementIdentification(unittest.TestCase):
    def test_line_table_is_shipped(self):
        el = hb.build_payload([doc("a.vms", [region()])])["elements"]
        import xpslines
        self.assertEqual(len(el["lines"]), len(xpslines.load_lines()))
        self.assertEqual(el["lines"][0][:2], ["Li", "1s"])
        self.assertIn("C", el["common"])
        self.assertEqual(el["hv"], xpslines.DEFAULT_HV)
        # an Auger line has a kinetic energy and no binding energy
        auger = [x for x in el["lines"] if x[2] is None]
        self.assertTrue(auger and all(x[3] is not None for x in auger))

    def test_no_lines_no_table_rows(self):
        p = hb.build_payload([doc("a.vms", [survey()])], lines=[])
        self.assertEqual(p["elements"]["lines"], [])
        self.assertNotIn("auto", p["samples"][0]["regions"][0])

    def test_surveys_get_automatic_labels(self):
        reg = hb.build_payload([doc("a.vms", [survey()])])["samples"][0]["regions"][0]
        labels = {a["label"]: a["be"] for a in reg["auto"]}
        self.assertAlmostEqual(labels["C 1s"], 285.0, delta=1.0)
        self.assertAlmostEqual(labels["O 1s"], 532.0, delta=1.0)

    def test_narrow_scans_get_none(self):
        p = hb.build_payload([doc("a.vms", [region("C 1s")])])
        self.assertNotIn("auto", p["samples"][0]["regions"][0])

    def test_labels_follow_the_shifted_axis(self):
        r = survey()
        shifted = hb.build_payload(
            [doc("a.vms", [r])],
            display=lambda x: __import__("dataclasses").replace(
                x, energy=[e + 1.0 for e in x.energy]))
        labels = {a["label"]: a["be"]
                  for a in shifted["samples"][0]["regions"][0]["auto"]}
        self.assertAlmostEqual(labels["C 1s"], 286.0, delta=1.0)


class TestPayload(unittest.TestCase):
    def test_structure(self):
        d = doc("dir/a.vms", [region("C 1s", "A"), region("O 1s", "A", lo=525,
                                                        hi=540, peak=532),
                              region("C 1s", "B")])
        p = hb.build_payload([d], details={"title": "T", "summary": "S",
                                           "customer": "ACME"},
                             methods_text="How.", calibration="Shifted.")
        self.assertEqual(p["v"], hb.FORMAT_VERSION)
        self.assertEqual([s["name"] for s in p["samples"]], ["A", "B"])
        self.assertEqual([len(s["regions"]) for s in p["samples"]], [2, 1])
        self.assertEqual(p["files"], [{"name": "a.vms", "format": "Test"}])
        self.assertEqual(p["details"]["customer"], "ACME")
        self.assertEqual((p["methods"], p["calibration"]), ("How.", "Shifted."))
        ids = [r["id"] for s in p["samples"] for r in s["regions"]]
        self.assertEqual(ids, ["s0r0", "s0r1", "s1r0"])
        r = p["samples"][0]["regions"][0]
        self.assertTrue(r["binding"])
        self.assertEqual(r["hv"], 1486.6)
        self.assertEqual(r["yunits"], "counts/s")
        self.assertEqual(r["meta"]["Pass energy (eV)"], "20")
        self.assertNotIn("Aperture", r["meta"])          # empty values dropped
        self.assertEqual(p["palette"]["light"], list(themes.PALETTES["Light"]["cycle"]))
        self.assertEqual(len(p["palette"]["dark"]), len(themes.PALETTES["Dark"]["cycle"]))

    def test_no_spectra_is_an_error(self):
        bad = Region(name="X", index=0, offset=0, decodable=False, sample="S")
        with self.assertRaises(hb.ViewerError):
            hb.build_payload([doc("a.vms", [bad])])
        with self.assertRaises(hb.ViewerError):
            hb.build_payload([])

    def test_depth_profile_levels(self):
        regs = [region("C 1s", "P", level=i, etch=30.0 * i) for i in range(4)]
        p = hb.build_payload([doc("a.vms", regs)])
        rs = p["samples"][0]["regions"]
        self.assertEqual([r["level"] for r in rs], [0, 1, 2, 3])
        self.assertEqual(rs[3]["etch"], 90.0)
        self.assertEqual(rs[3]["meta"]["Etch level"], "3")

    def test_display_hook_renames_and_shifts(self):
        d = doc("a.vms", [region("C 1s", "raw")])

        def display(r):
            q = copy.copy(r)
            q.sample, q.name = "Renamed", "Carbon"
            q.energy = [e + 0.5 for e in r.energy]
            return q
        p = hb.build_payload([d], display)
        s = p["samples"][0]
        self.assertEqual((s["name"], s["regions"][0]["name"]),
                         ("Renamed", "Carbon"))
        ax = s["regions"][0]["e"]
        self.assertAlmostEqual(ax["x0"], 292.5, 4)

    def test_notes_and_markers_come_from_the_annotations(self):
        d = doc("a.vms", [region("C 1s", "S1")])
        ann = annotations.Annotations()
        d.annotations, d.file_id = ann, "f1"
        ann.set_note("sample_notes", annotations.sample_key("f1", "S1"),
                     "sample note")
        ann.set_note("region_notes", annotations.region_key("f1", "S1", "C 1s"),
                     "region note")
        ann.add_marker("f1", "S1", "C 1s", 285.0, "C 1s")
        ann.set_shift(annotations.sample_key("f1", "S1"), 0.8)
        p = hb.build_payload([d])
        s = p["samples"][0]
        self.assertEqual(s["note"], "sample note")
        self.assertEqual(s["regions"][0]["note"], "region note")
        self.assertEqual(s["regions"][0]["markers"],
                         [{"be": 285.8, "label": "C 1s"}])

    def test_unregular_axis_survives(self):
        p = hb.build_payload([doc("a.vms", [region(regular=False)])])
        e = p["samples"][0]["regions"][0]["e"]
        self.assertIsInstance(e, list)
        self.assertEqual(len(e), 41)

    def test_figures(self):
        d = doc("a.vms", [region()])
        p = hb.build_payload([d], figures=[
            {"name": "Fig", "caption": "cap", "pages": [b"\x89PNGdata"]},
            {"name": "Empty", "caption": "", "pages": []}])
        self.assertEqual(len(p["figures"]), 1)
        self.assertTrue(p["figures"][0]["pages"][0].startswith(
            "data:image/png;base64,"))
        self.assertEqual(p["figures"][0]["caption"], "cap")

    def test_several_files_and_samples_keep_their_file(self):
        a = doc("a.vms", [region("C 1s", "S1")])
        b = doc("b.vms", [region("C 1s", "S1")])
        p = hb.build_payload([a, b])
        self.assertEqual([s["file"] for s in p["samples"]], [0, 1])
        self.assertEqual([f["name"] for f in p["files"]], ["a.vms", "b.vms"])

    @unittest.skipUnless(HAVE_PIL, "Pillow not installed")
    def test_holder_photo_with_calibrated_positions(self):
        blob = ImageBlob(name="Holder", offset=0, data=jpeg(200, 100),
                         is_jpeg_intact=True)
        d = doc("a.vms", [region("C 1s", "S1"), region("C 1s", "S2")],
                positions={"S1": (0.0, 0.0), "S2": (10.0, 0.0)}, images=[blob])
        calib = dict(holder.DEFAULT, mm_per_px=0.5)
        p = hb.build_payload([d], calib=calib)
        self.assertEqual(len(p["holders"]), 1)
        hd = p["holders"][0]
        self.assertEqual((hd["w"], hd["h"]), (200, 100))
        self.assertTrue(hd["photo"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(hd["points"]["S1"], [100.0, 50.0])
        self.assertEqual(hd["points"]["S2"], [120.0, 50.0])
        # without a calibration the photo is kept but no markers are placed
        p = hb.build_payload([d])
        self.assertEqual(p["holders"][0]["points"], {})


try:
    import numpy as np
    HAVE_NP = True
except Exception:
    HAVE_NP = False

CAMERA_CAL = {"width": 64, "height": 48, "um_per_px_x": 50.0,
              "um_per_px_y": 50.0, "x_mm": 10.0, "y_mm": 20.0}


def eighths(v):
    """A value the page stores exactly (multiples of 1/8)."""
    return round(v * 8) / 8


def map_cube(nx=6, ny=4, ne=40, seed=1):
    """A small SnapMap: a peak on a sloping baseline, brighter to one side,
    with reproducible noise; every value a multiple of 1/8."""
    import snapmap
    energy = [300.0 - 0.25 * i for i in range(ne)]
    rng = np.random.RandomState(seed)
    blocks = []
    for iy in range(ny):
        for ix in range(nx):
            f = 1.0 + 0.1 * ix + 0.05 * iy
            y = [eighths(20 + 0.5 * c + 60 * f * 2.718 ** (-((c - 18) / 3.0) ** 2)
                         + rng.uniform(-3, 3)) for c in range(ne)]
            blocks.append(((ix, iy), y))
    cube = snapmap.build(energy, nx, ny, -25.0, 10.0, -15.0, 10.0, blocks)
    cube.stage_x_mm, cube.stage_y_mm = 10.0, 20.0
    return cube


def cube_region(cube, name="C 1s", sample="S1"):
    r = region(name, sample, n=cube.n_energy)
    r.energy = list(cube.energy)
    r.counts = cube.total()
    r.extra["cube"] = cube
    return r


def camera_blob(name="S1 Pt #001a  10:00"):
    from readers.imaging import encode_png
    px = bytes((x * 4) % 256 if c == 0 else (y * 5) % 256 if c == 1 else 90
               for y in range(48) for x in range(64) for c in range(3))
    return ImageBlob(name=name, offset=0, data=encode_png(64, 48, px),
                     is_jpeg_intact=False, fmt="png", sample="S1",
                     calib=dict(CAMERA_CAL))


@unittest.skipUnless(HAVE_NP and HAVE_PIL, "numpy and Pillow needed")
class TestCamerasAndMaps(unittest.TestCase):
    def payload(self, **kw):
        cube = map_cube()
        d = doc("a.vgd", [region("C 1s", "S2"), cube_region(cube)],
                positions={"S1": (10.0, 20.0), "S2": (10.1, 20.1)},
                images=[camera_blob()])
        return hb.build_payload([d], **kw), cube

    def test_the_picture_is_shrunk_and_carries_its_points(self):
        p, _cube = self.payload()
        (cam,) = p["cameras"]
        self.assertTrue(cam["img"].startswith("data:image/jpeg;base64,"))
        self.assertEqual((cam["w"], cam["h"]), (64, 48))
        self.assertEqual(cam["fov"], [3.2, 2.4])
        self.assertEqual(cam["sample"], "S1")
        self.assertEqual(cam["bar_px"], 20.0)               # 1 mm at 50 um/px
        # image x runs against stage X, y with stage Y (snapshot.py)
        self.assertEqual(cam["points"]["S1"], [32.0, 24.0])
        self.assertEqual(cam["points"]["S2"], [30.0, 26.0])
        (out,) = cam["maps"]
        self.assertEqual(out["sample"], "S1")
        left, top, w, h = out["rect"]
        self.assertAlmostEqual(left + w / 2, 32.0, places=1)
        self.assertAlmostEqual(top + h / 2, 24.0, places=1)
        self.assertAlmostEqual(w, 6 * 10 / 50, places=1)       # 60 um at 50 um/px

    def test_a_large_picture_is_scaled_down_and_points_follow(self):
        from readers.imaging import encode_png
        w, h = 1600, 1200
        blob = ImageBlob("big", 0, encode_png(w, h, bytes(w * h * 3)), False,
                         fmt="png", sample="S1",
                         calib=dict(CAMERA_CAL, width=w, height=h,
                                    um_per_px_x=5.0, um_per_px_y=5.0))
        d = doc("a.vgd", [region("C 1s", "S1")], positions={"S1": (10.0, 20.0)},
                images=[blob])
        (cam,) = hb.build_payload([d])["cameras"]
        self.assertEqual((cam["w"], cam["h"]), (800, 600))
        self.assertEqual(cam["points"]["S1"], [400.0, 300.0])     # centre, halved
        self.assertEqual(cam["bar_px"], 100.0)                    # 1 mm = 200 px, halved

    def test_map_pixels_survive_the_round_trip(self):
        p, cube = self.payload()
        (m,) = p["maps"]
        self.assertEqual((m["nx"], m["ny"], m["n"]), (6, 4, 40))
        raw = np.frombuffer(zlib.decompress(base64.b64decode(m["z"])), "<u2")
        got = raw.reshape(4, 6, 40).astype(float) * m["q"]
        self.assertEqual(m["q"], hb.MAP_STEP)
        self.assertLessEqual(np.abs(got - cube.array3d()).max(), m["q"] / 2)
        self.assertTrue(np.array_equal(got, cube.array3d()))     # eighths: exact
        self.assertEqual(hb.pack_axis(list(cube.energy)), m["e"])
        self.assertEqual((m["x0"], m["dx"], m["y0"], m["dy"]),
                         (-25.0, 10.0, -15.0, 10.0))
        # linked both ways: the spectrum knows its map, the map its spectrum
        reg = [r for s in p["samples"] for r in s["regions"] if r.get("map")][0]
        self.assertEqual(reg["map"], m["id"])
        self.assertEqual(m["region"], reg["id"])
        self.assertEqual((m["sample"], m["name"]), ("S1", "C 1s"))

    def test_the_map_knows_which_picture_it_lies_on(self):
        p, _cube = self.payload()
        (m,) = p["maps"]
        self.assertEqual(m["cam"]["id"], p["cameras"][0]["id"])
        # the picture's edges in the map's own micrometres (map centred on it)
        self.assertEqual(m["cam"]["ext"], [-1600.0, 1600.0, 1200.0, -1200.0])
        self.assertEqual(m["stage"], [10.0, 20.0])

    def test_switches_leave_things_out(self):
        p, _c = self.payload(cameras=False)
        self.assertEqual(p["cameras"], [])
        self.assertIsNone(p["maps"][0]["cam"])
        p, _c = self.payload(snapmaps=False)
        self.assertEqual(p["maps"], [])
        self.assertTrue(all("map" not in r for s in p["samples"]
                            for r in s["regions"]))
        self.assertEqual(len(p["cameras"]), 1)

    def test_no_maps_or_pictures_still_gives_the_keys(self):
        p = hb.build_payload([doc("a.vms", [region("C 1s", "S1")])])
        self.assertEqual((p["cameras"], p["maps"], p["build_notes"]), ([], [], []))

    def test_an_uncalibrated_picture_is_not_a_camera_view(self):
        blob = ImageBlob("holder", 0, jpeg(50, 40), True)
        p = hb.build_payload([doc("a.vms", [region("C 1s", "S1")], images=[blob])])
        self.assertEqual(p["cameras"], [])

    def test_maps_are_thinned_to_fit_a_size_budget(self):
        items = [(map_cube(seed=s), map_cube().energy) for s in (1, 2, 3)]
        full = sum(n for _e, n in (hb.pack_cube(c, e) for c, e in items))
        half = sum(n for _e, n in (hb.pack_cube(c, e, 2) for c, e in items))
        self.assertLess(half, full)
        entries, rebin, dropped = hb.pack_maps(items, budget=full)
        self.assertEqual((len(entries), rebin, dropped), (3, 1, 0))
        entries, rebin, dropped = hb.pack_maps(items, budget=(full + half) // 2)
        self.assertEqual((len(entries), rebin, dropped), (3, 2, 0))
        self.assertEqual(entries[0]["n"], 20)
        self.assertEqual(entries[0]["e"]["n"], 20)
        entries, rebin, dropped = hb.pack_maps(items, budget=1)
        self.assertEqual((entries, dropped), ([], 3))

    def test_the_payload_says_when_it_thinned_or_dropped_maps(self):
        cube = map_cube()
        d = doc("a.vgd", [cube_region(cube)], positions={"S1": (10.0, 20.0)})
        full = hb.pack_cube(cube, cube.energy)[1]
        half = hb.pack_cube(cube, cube.energy, 2)[1]
        old = hb.MAP_BUDGET
        self.addCleanup(setattr, hb, "MAP_BUDGET", old)
        hb.MAP_BUDGET = (full + half) // 2
        p = hb.build_payload([d])
        self.assertEqual(p["maps"][0]["n"], 20)
        self.assertTrue(any("2 energy channels summed" in n
                            for n in p["build_notes"]))
        hb.MAP_BUDGET = 1
        p = hb.build_payload([d])
        self.assertEqual(p["maps"], [])
        self.assertTrue(any("left out" in n for n in p["build_notes"]))
        # and the spectrum stays, with no link to a map that is not there
        self.assertNotIn("map", p["samples"][0]["regions"][0])

    def test_rebinned_map_sums_the_channels(self):
        cube = map_cube()
        entry, _n = hb.pack_cube(cube, cube.energy, rebin=2)
        raw = np.frombuffer(zlib.decompress(base64.b64decode(entry["z"])), "<u2")
        got = raw.reshape(4, 6, 20) * entry["q"]
        want = cube.array3d().reshape(4, 6, 20, 2).sum(axis=3)
        self.assertLessEqual(np.abs(got - want).max(), entry["q"] / 2 + 1e-9)


class TestEncoding(unittest.TestCase):
    def test_round_trip(self):
        payload = {"a": [1, 2, 3], "t": "café ✓", "n": None}
        self.assertEqual(hb.decode_payload(hb.encode_payload(payload)), payload)

    def test_is_gzip_of_json_and_deterministic(self):
        text = hb.encode_payload({"x": list(range(1000))})
        raw = gzip.decompress(base64.b64decode(text))
        self.assertEqual(json.loads(raw), {"x": list(range(1000))})
        self.assertEqual(text, hb.encode_payload({"x": list(range(1000))}))
        self.assertLess(len(text), len(raw))

    def test_base64_alphabet_only(self):
        text = hb.encode_payload({"s": "</script><!--"})
        self.assertRegex(text, r"^[A-Za-z0-9+/=]+$")


class TestPage(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        d = doc("a.vms", [region("C 1s", "S1")])
        self.payload = hb.build_payload(
            [d], details={"title": "MoS2 <study> & more"})

    def test_page_is_self_contained(self):
        page = hb.build_html(self.payload)
        self.assertTrue(page.startswith("<!DOCTYPE html>"))
        for token in ("__DATA__", "__CSS__", "__JS__", "__TITLE__"):
            self.assertNotIn(token, page)
        self.assertNotRegex(page, r"https?://")               # no network
        self.assertNotRegex(page, r"<script[^>]*\ssrc=")
        self.assertNotRegex(page, r"<link\b")
        self.assertNotRegex(page, r"@import|url\(")
        self.assertEqual(len(re.findall(r"<script\b", page)), 2)   # data + code

    def test_title_is_escaped(self):
        page = hb.build_html(self.payload)
        self.assertIn("<title>MoS2 &lt;study&gt; &amp; more</title>", page)

    def test_hostile_text_cannot_break_out_of_the_data_element(self):
        d = doc("a.vms", [region("</script><script>alert(1)</script>",
                                "</SCRIPT><img src=x onerror=alert(1)>")])
        page = hb.build_html(hb.build_payload(
            [d], details={"title": "</title><script>alert(2)</script>",
                          "summary": "<img src=x onerror=alert(3)>"},
            methods_text="</script>"))
        self.assertNotIn("alert(1)", page)
        self.assertNotIn("alert(3)", page)
        self.assertEqual(page.count("</script>"), 2)
        self.assertNotIn("<script>alert(2)", page)

    def test_data_is_in_the_page_and_decodes(self):
        page = hb.build_html(self.payload)
        m = re.search(r'<script id="xps-data"[^>]*>([^<]*)</script>', page)
        self.assertEqual(hb.decode_payload(m.group(1)), self.payload)

    def test_write_html_is_atomic_and_reports_size(self):
        out = os.path.join(self.dir, "b.html")
        n = hb.write_html(out, self.payload)
        self.assertEqual(n, os.path.getsize(out))
        self.assertGreater(n, 20000)
        self.assertEqual(sorted(os.listdir(self.dir)), ["b.html"])
        n2 = hb.write_html(out, self.payload)                 # replaced in place
        self.assertEqual(n2, n)
        self.assertEqual(sorted(os.listdir(self.dir)), ["b.html"])

    def test_size_of_a_realistic_data_set_is_modest(self):
        regs = [region("C 1s", f"S{i}", n=200, scale=1 + i / 10,
                       peak=285 + i / 20) for i in range(60)]
        page = hb.build_html(hb.build_payload([doc("a.vms", regs)]))
        raw = sum(len(r.counts) for r in regs) * 8
        self.assertLess(len(page), 120_000 + raw)     # far below plain JSON

    def test_missing_viewer_file_is_a_clear_error(self):
        old = hb.VIEWER_DIR
        hb.VIEWER_DIR = self.dir
        self.addCleanup(setattr, hb, "VIEWER_DIR", old)
        with self.assertRaises(hb.ViewerError) as cm:
            hb.build_html(self.payload)
        self.assertIn("template.html", str(cm.exception))

    def test_default_name(self):
        self.assertEqual(hb.default_name({"title": "A/B"}),
                         "A_B - data browser.html")
        self.assertEqual(hb.default_name({}), "experiment - data browser.html")


def _node():
    for name in ("node", "node.exe"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _window_case(y, ne=None):
    """A spectrum on every pixel of a tiny map and what snapmap.default_window
    says about it."""
    import snapmap
    ne = len(y)
    energy = [300.0 - 0.25 * i for i in range(ne)]
    cube = snapmap.build(energy, 2, 2, 0.0, 1.0, 0.0, 1.0,
                         [((ix, iy), y) for ix in range(2) for iy in range(2)])
    return {"energy": energy, "y": y, "expect": list(snapmap.default_window(cube))}


@unittest.skipUnless(HAVE_FIT, "numpy / casafit test helpers not available")
class TestFits(unittest.TestCase):
    """CasaXPS fits in the payload: numbers and curves from the desktop side."""

    def payload(self):
        return hb.build_payload([doc("fit.vms", [fitted_region()])])

    def test_fit_block(self):
        reg = self.payload()["samples"][0]["regions"][0]
        self.assertEqual(len(reg["fit"]["rows"]), 1)
        row = reg["fit"]["rows"][0]
        self.assertEqual(row["region"], "Ti 2p")
        self.assertAlmostEqual(row["rsf"], 2.001)
        self.assertEqual(len(row["components"]), 2)
        c = row["components"][0]
        self.assertEqual(set(("name", "be", "fwhm", "area", "shape", "state",
                              "gk")) - set(c), set())
        cur = row["curve"]
        n = len(cur["env"])
        self.assertEqual(len(cur["bg"]), n)
        self.assertEqual([len(x) for x in cur["comps"]], [n, n])
        self.assertLessEqual(cur["i0"] + n, len(reg["y"]))
        # envelope = background + components, to the rounding of the curves
        for k in (0, n // 2, n - 1):
            total = cur["bg"][k] + sum(x[k] for x in cur["comps"])
            self.assertAlmostEqual(total, cur["env"][k],
                                   delta=abs(cur["env"][k]) * 1e-4 + 1e-6)

    def test_curves_line_up_with_the_data(self):
        reg = self.payload()["samples"][0]["regions"][0]
        cur = reg["fit"]["rows"][0]["curve"]
        y = reg["y"]
        # the strongest point of the envelope is the strongest point of the data
        top_env = cur["i0"] + max(range(len(cur["env"])),
                                  key=lambda k: cur["env"][k])
        top_y = max(range(len(y)), key=lambda k: y[k])
        self.assertLessEqual(abs(top_env - top_y), 2)
        # and the curves are on the data's scale, not per second
        self.assertAlmostEqual(cur["env"][top_env - cur["i0"]], y[top_y],
                               delta=y[top_y] * 0.15)

    def test_regions_without_a_fit_have_no_fit_key(self):
        d = doc("a.vms", [region("C 1s"), fitted_region()])
        regs = hb.build_payload([d])["samples"]
        by = {r["name"]: r for s in regs for r in s["regions"]}
        self.assertNotIn("fit", by["C 1s"])
        self.assertIn("fit", by["Ti 2p"])

    def test_notes_come_along(self):
        r = fitted_region()
        r.fit.regions[0].background = "Tougaard 3 Parameter"
        fit = hb.build_payload([doc("a.vms", [r])])["samples"][0]["regions"][0]["fit"]
        self.assertTrue(any("not reproduced" in n for n in fit["notes"]))

    def test_size_budget_drops_curves_not_the_table(self):
        old = hb.FIT_BUDGET
        hb.FIT_BUDGET = 10
        try:
            p = hb.build_payload([doc("a.vms", [fitted_region()])])
        finally:
            hb.FIT_BUDGET = old
        row = p["samples"][0]["regions"][0]["fit"]["rows"][0]
        self.assertIsNone(row["curve"])
        self.assertEqual(len(row["components"]), 2)
        self.assertTrue(any("Fit curves were left out" in n
                            for n in p["build_notes"]))

    def test_shift_moves_positions_with_the_axis(self):
        r = fitted_region()
        base = hb.build_payload([doc("a.vms", [r])])
        shifted = hb.build_payload(
            [doc("a.vms", [r])],
            display=lambda x: __import__("dataclasses").replace(
                x, energy=[e + 1.5 for e in x.energy],
                photon_energy=x.photon_energy + 1.5))
        b0 = base["samples"][0]["regions"][0]["fit"]["rows"][0]["components"][0]
        b1 = shifted["samples"][0]["regions"][0]["fit"]["rows"][0]["components"][0]
        self.assertAlmostEqual(b1["be"] - b0["be"], 1.5, places=3)


@unittest.skipUnless(_node(), "Node.js not installed")
class TestJavaScript(unittest.TestCase):
    """viewer.js against numbers computed by the Python side."""

    def map_fixture(self):
        """The SnapMap page maths against snapmap.py on the same map."""
        import snapmap
        cube = map_cube()
        d = doc("a.vgd", [cube_region(cube)], positions={"S1": (10.0, 20.0)})
        entry = hb.build_payload([d])["maps"][0]
        e = cube.energy
        lo, hi = e[22], e[15]
        rect = (-25.0, -15.0, 5.0, 5.0)
        mask = cube.rect_mask(*rect)
        img = cube.image(lo, hi)
        n = cube.nx * cube.ny
        cases = []
        peak = [eighths(20 + 0.5 * c + 60 * 2.718 ** (-((c - 18) / 3.0) ** 2))
                for c in range(60)]
        cases.append(_window_case(peak))
        # the background climbs to the scan edge, higher than the peak
        cases.append(_window_case([eighths(150 - 2.0 * c + 25 * 2.718 ** (-((c - 40) / 3.0) ** 2)
                                           + (0 if c > 8 else 30)) for c in range(60)]))
        cases.append(_window_case([10.0] * 40))                    # nothing there
        cases.append(_window_case([eighths(5 + 0.3 * c) for c in range(30)]))
        return {
            "entry": entry, "energy": list(e), "win": [lo, hi], "rect": list(rect),
            "image": img.ravel().tolist(),
            "image_bg": cube.image(lo, hi, background=True).ravel().tolist(),
            "total_mean": (np.asarray(cube.total()) / n).tolist(),
            "roi_mean": (np.asarray(cube.roi_spectrum(mask))
                         / int(mask.sum())).tolist(),
            "mask": mask.ravel().astype(int).tolist(), "mask_count": int(mask.sum()),
            "window_cases": cases, "range": list(snapmap.colour_range(img)),
            "csv": snapmap.to_csv_grid(cube, img),
            "pixels": [[-25.0, -15.0, [0, 0]], [15.0, 5.0, [4, 2]],
                       [30.0, 0.0, None], [-25.0, 40.0, None], [-21.0, -12.0, [0, 0]]],
            "channels": [[e[3], e[9]],
                         np.flatnonzero(cube.channels(e[3], e[9])).tolist()],
        }

    def element_fixture(self):
        """Candidate lookups as xpslines gives them, for the page's port."""
        import xpslines
        lines = xpslines.load_lines()
        table = hb.element_table(lines)
        cases = []
        for be, win, hv in ((285.0, 2.0, None), (284.4, 1.0, 1486.6),
                            (532.1, 2.0, 1486.6), (455.5, 3.0, 1486.6),
                            (978.0, 4.0, 1486.6), (978.0, 4.0, 1253.6),
                            (150.0, 0.5, None), (72.5, 5.0, 1486.6)):
            got = xpslines.candidates(be, win, lines, hv)
            cases.append({"be": be, "win": win, "hv": hv,
                          "labels": [xpslines.label_of(e) for _d, e in got],
                          "deltas": [d for d, _e in got]})
        return {"table": table, "cases": cases}

    def fit_fixture(self, tmp):
        """A fitted spectrum: the payload, the app's own CSV of it (which
        includes the fit columns) and its fit columns as the app names them."""
        r = fitted_region()
        payload = hb.build_payload([doc("fit.vms", [r])])
        path = os.path.join(tmp, "fit.csv")
        exporters.export_csv([r], path)
        with open(path, newline="") as fh:
            text = fh.read()
        import quant
        from test_quant import profile_groups, sample_groups
        groups = sample_groups()
        pgroups = profile_groups()
        pkeyed = [dict(g, entries=[dict(e, key=f"p{gi}e{ei}")
                                   for ei, e in enumerate(g["entries"])])
                  for gi, g in enumerate(pgroups)]
        prof = {"groups": pkeyed, "exclude": {"p0e2": False}}
        for mode in ("element", "state", "share"):
            prof[mode] = quant.profile(pgroups, mode)
        prof["element_excl"] = quant.profile(
            pgroups, include=[[True, True, False], [True, True], [True]])
        keyed = [dict(g, entries=[dict(e, key=f"g{gi}e{ei}")
                                  for ei, e in enumerate(g["entries"])])
                 for gi, g in enumerate(groups)]
        qx = {"profile": prof, "groups": keyed,
              "plain": quant.csv_rows(groups),
              "excluded": quant.csv_rows(groups, include=[[True, False, True],
                                                          [True]]),
              "excluded_keys": {"g0e1": False},
              "trans": quant.csv_rows(groups, transmission=True)}
        return {"quant": qx, "payload_b64": hb.encode_payload(payload), "csv": text,
                "states": [{"gk": c["gk"], "name": c["state"]}
                           for c in payload["samples"][0]["regions"][0]
                           ["fit"]["rows"][0]["components"]]}

    def test_pure_half_agrees_with_python(self):
        regs = [region("C 1s", "A", n=61), region("O 1s", "A", n=41, lo=525,
                                                 hi=540, peak=532),
                region("C 1s", "B", n=61, scale=2.5)]
        d = doc("dir/a.vms", regs)
        payload = hb.build_payload([d], details={"title": "T"})
        norm = []
        for ys in ([1.0, 5.0, 3.0], [-2.0, 4.0, 0.5, 8.0], [0.0, 0.0]):
            r = Region(name="x", index=0, offset=0, counts=ys)
            norm.append({"y": ys, "max": plots.norm_factor(r, "Max = 1"),
                         "area": plots.norm_factor(r, "Area = 1")})
        ramps = [{"colour": "#0072B2", "n": n, "bg": "#FFFFFF",
                  "expect": themes.ramp("#0072B2", n, "#FFFFFF")}
                 for n in (2, 3, 8, 30)]
        first = payload["samples"][0]["regions"][0]
        # what the app itself would write for the same spectra
        chosen = [regs[0], regs[1]]
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = os.path.join(tmp, "e.csv")
            exporters.export_csv(chosen, csv_path)
            with open(csv_path, newline="") as fh:
                csv_text = fh.read()
            fx = {
                "payload_b64": hb.encode_payload(payload),
                "n_samples": 2, "n_spectra": 3,
                "first_len": len(regs[0].energy), "first_x0": regs[0].energy[0],
                "first_x_last": regs[0].energy[-1],
                "first_y3": first["y"][3], "first_file": "a.vms",
                "norm": norm, "ramps": ramps, "csv": csv_text,
                "csv_ids": [payload["samples"][0]["regions"][0]["id"],
                            payload["samples"][0]["regions"][1]["id"]],
            }
            if HAVE_NP:
                fx["map"] = self.map_fixture()
            fx["elements"] = self.element_fixture()
            if HAVE_FIT:
                fx["fit"] = self.fit_fixture(tmp)
            fx_path = os.path.join(tmp, "fx.json")
            with open(fx_path, "w", encoding="utf-8") as fh:
                json.dump(fx, fh)
            res = subprocess.run(
                [_node(), os.path.join(ROOT, "tests", "viewer_test.js"),
                 fx_path], capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("ok ", res.stdout)


if __name__ == "__main__":
    unittest.main()
