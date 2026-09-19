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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


@unittest.skipUnless(_node(), "Node.js not installed")
class TestJavaScript(unittest.TestCase):
    """viewer.js against numbers computed by the Python side."""

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
