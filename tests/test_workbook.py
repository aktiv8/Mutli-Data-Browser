"""The .xpscontainer workbook format and the AVG/VGD import choice.

Run:  python -m unittest discover tests
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import importplan  # noqa: E402
import workbook as wbk  # noqa: E402
from readers import Region  # noqa: E402


def region(name, sample="S1", level=None):
    return Region(name=name, index=0, offset=0, energy=[1.0, 2.0],
                  counts=[1.0, 2.0], decodable=True, sample=sample,
                  etch_level=level)


def read(path):
    with open(path, "rb") as fh:
        return fh.read()


class Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, name, data=b"data"):
        p = os.path.join(self.dir, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(data)
        return p

    def workbook(self):
        a = self.write("in/a.vgd", b"\x00\x01binary" * 100)
        b = self.write("in/b.avg", b"<xml/>")
        logo = self.write("logo.png", b"\x89PNG fake")
        wb = wbk.Workbook(
            details={"title": "MoS2 study", "customer": "ACME",
                     "reference": "J-42", "operator": "DM",
                     "date": "2026-01-02", "summary": "Line one\nLíne two ✓"},
            state={"view_mode": "Heatmap", "cursors": {"C 1s": 285.0},
                   "ticked": [wbk.region_ref("f1", 0, region("C 1s"))]},
            figures=[{"id": "g1", "name": "Fig A", "caption": "Depth",
                      "state": {"view_mode": "Stack"}}],
            files=[wbk.FileEntry("f1", "a.vgd", a, original_path=a),
                   wbk.FileEntry("f2", "b.avg", b, original_path=b)],
            logo=logo, metadata={"a.vgd": {"n": 1}},
            extra={"future_key": {"x": 1}})
        return wb, a, b


class TestRoundTrip(Tmp):
    def test_everything_survives(self):
        wb, a, b = self.workbook()
        path = os.path.join(self.dir, "exp" + wbk.EXT)
        wbk.save(path, wb, preview_png=b"PNGDATA")
        out = wbk.load(path, os.path.join(self.dir, "x"))
        self.assertEqual(out.details, wb.details)
        self.assertEqual(out.state, wb.state)
        self.assertEqual(out.figures, wb.figures)
        self.assertEqual(out.metadata, wb.metadata)
        self.assertEqual(out.extra, {"future_key": {"x": 1}})
        self.assertEqual([f.name for f in out.files], ["a.vgd", "b.avg"])
        for f, src in zip(out.files, (a, b)):
            with open(f.path, "rb") as x, open(src, "rb") as y:
                self.assertEqual(x.read(), y.read())     # byte-identical
            self.assertEqual(f.sha256, wbk.sha256_file(src))
        self.assertTrue(out.logo.endswith("logo.png"))
        self.assertEqual(read(out.logo), b"\x89PNG fake")
        self.assertEqual(out.warnings, [])
        self.assertEqual(wbk.read_preview(path), b"PNGDATA")

    def test_survives_deleting_the_originals(self):
        wb, a, b = self.workbook()
        path = os.path.join(self.dir, "exp" + wbk.EXT)
        wbk.save(path, wb)
        shutil.rmtree(os.path.join(self.dir, "in"))
        out = wbk.load(path, os.path.join(self.dir, "x"))
        self.assertTrue(all(os.path.isfile(f.path) for f in out.files))

    def test_resave_from_extracted_copies(self):
        wb, _a, _b = self.workbook()
        p1 = os.path.join(self.dir, "one" + wbk.EXT)
        wbk.save(p1, wb)
        out = wbk.load(p1, os.path.join(self.dir, "x"))
        p2 = os.path.join(self.dir, "two" + wbk.EXT)
        wbk.save(p2, out)
        again = wbk.load(p2, os.path.join(self.dir, "y"))
        self.assertEqual([f.sha256 for f in again.files],
                         [f.sha256 for f in wb.files])
        self.assertEqual(again.extra, wb.extra)
        self.assertEqual(again.created, wb.created)

    def test_missing_source_is_reported_and_nothing_written(self):
        wb, a, _b = self.workbook()
        os.remove(a)
        path = os.path.join(self.dir, "exp" + wbk.EXT)
        with self.assertRaises(wbk.WorkbookError) as cm:
            wbk.save(path, wb)
        self.assertIn("a.vgd", str(cm.exception))
        self.assertFalse(os.path.exists(path))
        self.assertEqual([f for f in os.listdir(self.dir)
                          if f.startswith(".xpsc_")], [])

    def test_failed_save_keeps_the_old_file(self):
        wb, _a, _b = self.workbook()
        path = os.path.join(self.dir, "exp" + wbk.EXT)
        wbk.save(path, wb)
        before = read(path)
        wb.logo = os.path.join(self.dir, "nope.png")
        with self.assertRaises(wbk.WorkbookError):
            wbk.save(path, wb)
        self.assertEqual(read(path), before)


class TestSafety(Tmp):
    def crafted(self, manifest, members=None):
        path = os.path.join(self.dir, "bad" + wbk.EXT)
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            for k, v in (members or {}).items():
                zf.writestr(k, v)
        return path

    def base(self, **kw):
        m = {"format": wbk.FORMAT, "format_version": 1, "files": []}
        m.update(kw)
        return m

    def test_zip_slip_names_stay_inside(self):
        m = self.base(files=[{"id": "f1", "member": "data/f1/x",
                              "original_name": "../../evil.txt"}])
        path = self.crafted(m, {"data/f1/x": "hi"})
        out = wbk.load(path, os.path.join(self.dir, "x"))
        dest = os.path.abspath(out.files[0].path)
        self.assertTrue(dest.startswith(os.path.abspath(
            os.path.join(self.dir, "x")) + os.sep))
        self.assertEqual(os.path.basename(dest), "evil.txt")
        self.assertFalse(os.path.exists(os.path.join(self.dir, "evil.txt")))

    def test_bad_ids_rejected(self):
        for bad in ("../f1", "a/b", ""):
            m = self.base(files=[{"id": bad, "member": "data/x/y",
                                  "original_name": "y"}])
            path = self.crafted(m, {"data/x/y": "hi"})
            with self.assertRaises(wbk.WorkbookError):
                wbk.load(path, os.path.join(self.dir, "x"))

    def test_member_named_but_absent(self):
        m = self.base(files=[{"id": "f1", "member": "data/f1/a.vgd",
                              "original_name": "a.vgd"}])
        with self.assertRaises(wbk.WorkbookError) as cm:
            wbk.load(self.crafted(m), os.path.join(self.dir, "x"))
        self.assertIn("a.vgd", str(cm.exception))

    def test_newer_format_refused(self):
        path = self.crafted(self.base(format_version=99))
        with self.assertRaises(wbk.WorkbookError) as cm:
            wbk.load(path, os.path.join(self.dir, "x"))
        self.assertIn("newer version", str(cm.exception))

    def test_not_a_workbook(self):
        p = self.write("junk.xpscontainer", b"not a zip")
        with self.assertRaises(wbk.WorkbookError):
            wbk.load(p, os.path.join(self.dir, "x"))
        path = os.path.join(self.dir, "other.zip")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("hello.txt", "x")
        with self.assertRaises(wbk.WorkbookError):
            wbk.load(path, os.path.join(self.dir, "x"))
        with self.assertRaises(wbk.WorkbookError):
            wbk.load(self.crafted({"format": "other", "format_version": 1}),
                     os.path.join(self.dir, "x"))

    def test_damaged_json_and_truncated_archive(self):
        path = os.path.join(self.dir, "d" + wbk.EXT)
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("manifest.json", "{not json")
        with self.assertRaises(wbk.WorkbookError):
            wbk.load(path, os.path.join(self.dir, "x"))
        wb, _a, _b = self.workbook()
        good = os.path.join(self.dir, "g" + wbk.EXT)
        wbk.save(good, wb)
        data = read(good)
        cut = self.write("cut.xpscontainer", data[:len(data) // 2])
        with self.assertRaises(wbk.WorkbookError):
            wbk.load(cut, os.path.join(self.dir, "x"))

    def test_hash_mismatch_is_a_warning(self):
        wb, _a, _b = self.workbook()
        good = os.path.join(self.dir, "g" + wbk.EXT)
        wbk.save(good, wb)
        tampered = os.path.join(self.dir, "t" + wbk.EXT)
        with zipfile.ZipFile(good) as zin, \
                zipfile.ZipFile(tampered, "w") as zout:
            for item in zin.namelist():
                data = zin.read(item)
                if item == "data/f2/b.avg":
                    data = b"<changed/>"
                zout.writestr(item, data)
        out = wbk.load(tampered, os.path.join(self.dir, "x"))
        self.assertEqual(len(out.warnings), 1)
        self.assertIn("b.avg", out.warnings[0])

    def test_safe_name(self):
        self.assertEqual(wbk.safe_name("../../a/b.vgd"), "b.vgd")
        self.assertEqual(wbk.safe_name("C:\\x\\y.avg"), "y.avg")
        self.assertEqual(wbk.safe_name(""), "file")
        self.assertEqual(wbk.safe_name("a:b?.txt"), "a_b_.txt")


class TestRegionRefs(unittest.TestCase):
    def setUp(self):
        self.regs = [region("C 1s", "S1", 0), region("C 1s", "S1", 1),
                     region("O 1s", "S1", 0), region("C 1s", "S2", 0)]

    def refs(self, idx):
        return [wbk.region_ref("f1", i, self.regs[i]) for i in idx]

    def test_position_match(self):
        out, missing = wbk.resolve_refs(self.refs([0, 2]), {"f1": self.regs})
        self.assertEqual((out, missing), ([self.regs[0], self.regs[2]], 0))

    def test_reordered_regions_are_found_by_identity(self):
        refs = self.refs([1, 3])
        shuffled = self.regs[::-1]
        out, missing = wbk.resolve_refs(refs, {"f1": shuffled})
        self.assertEqual((out, missing), ([self.regs[1], self.regs[3]], 0))

    def test_missing_file_or_region_is_counted(self):
        refs = self.refs([0]) + [{"file": "f9", "pos": 0, "name": "X",
                                  "sample": "", "etch_level": None}]
        out, missing = wbk.resolve_refs(refs, {"f1": self.regs[1:]})
        self.assertEqual((out, missing), ([], 2))

    def test_duplicates_are_not_taken_twice(self):
        twins = [region("C 1s"), region("C 1s")]
        refs = [wbk.region_ref("f1", 0, twins[0]),
                wbk.region_ref("f1", 0, twins[0])]
        out, missing = wbk.resolve_refs(refs, {"f1": twins})
        self.assertEqual(out, twins)
        self.assertEqual(missing, 0)

    def test_new_id(self):
        self.assertEqual(wbk.new_id(["f1", "f3"], "f"), "f2")
        self.assertEqual(wbk.new_id([], "g"), "g1")


try:
    import reportlab  # noqa: F401
    try:
        import pymupdf as mupdf
    except ImportError:
        import fitz as mupdf
    HAVE_REPORT = True
except ImportError:
    HAVE_REPORT = False


@unittest.skipUnless(HAVE_REPORT, "reportlab / PyMuPDF not installed")
class TestReport(Tmp):
    def setUp(self):
        super().setUp()
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from test_metasummary import Doc, region as mregion
        self.docs = [Doc([mregion("Survey", 160, step=1.0),
                          mregion("Mo 3d", 40)], "a.vgd")]
        self.figs = [{"name": "One", "caption": "First\n\nsecond", "state": {}},
                     {"name": "Two", "caption": "", "state": {}}]
        self.rows = [{"name": "a.vgd", "format": "Thermo", "regions": 2,
                      "size": 2048, "sha256": "ab" * 32}]
        self.details = {"title": "Study <1> & co", "customer": "ACME",
                        "reference": "J-1", "operator": "", "date": "",
                        "summary": "Para one.\nline two\n\nPara <two>."}
        self.calls = []

    def render(self, pdf, n, fig):
        from matplotlib.figure import Figure
        self.calls.append((n, fig["name"]))
        f = Figure(figsize=(11.7, 8.3))
        f.text(0.5, 0.5, f"figure {n}")
        pdf.savefig(f)
        return 1

    def build(self, sections, logo=""):
        import report
        path = os.path.join(self.dir, "r.pdf")
        n = report.build_report(path, self.details, logo, self.rows, self.docs,
                                self.figs, self.render, sections)
        return path, n

    def pages(self, path):
        with mupdf.open(path) as d:
            return [p.get_text() for p in d]

    def test_all_sections(self):
        path, n = self.build(("cover", "metadata", "figures"))
        text = self.pages(path)
        self.assertEqual(n, len(text))
        self.assertGreaterEqual(n, 4)               # cover, metadata, 2 figures
        self.assertIn("Study <1> & co", text[0])    # escaped, not swallowed
        self.assertIn("Para <two>.", text[0])
        self.assertIn("ACME", text[0])
        self.assertIn("a.vgd", text[0])
        meta = "".join(text[1:-2])
        for token in ("Common to every region", "Survey", "Mo 3d", "160",
                      "PE (eV)"):
            self.assertIn(token, meta)
        self.assertIn("figure 1", text[-2])
        self.assertIn(f"report page {n} of {n}", text[-1])
        self.assertEqual(self.calls, [(1, "One"), (2, "Two")])

    def test_sections_are_optional(self):
        _p, cover_only = self.build(("cover",))
        self.assertEqual(cover_only, 1)
        self.assertEqual(self.calls, [])            # figures not drawn
        _p, figs_only = self.build(("figures",))
        self.assertEqual(figs_only, 2)

    def test_nothing_to_report(self):
        import report
        self.figs = []
        with self.assertRaises(report.ReportError):
            self.build(("figures",))

    def test_logo_is_accepted_and_a_bad_one_is_ignored(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        logo = os.path.join(self.dir, "logo.png")
        Image.new("RGB", (200, 80), (10, 90, 160)).save(logo)
        _p, n = self.build(("cover",), logo)
        self.assertEqual(n, 1)
        bad = self.write("bad.png", b"not an image")
        _p, n = self.build(("cover",), bad)
        self.assertEqual(n, 1)


class TestImportPlan(unittest.TestCase):
    PATHS = ["/d/one.avg", "/d/one.vgd", "/d/two.AVG", "/d/TWO.vgd",
             "/d/three.avg", "/e/one.vgd", "/d/four.vms"]

    def test_find_pairs_case_insensitive_and_per_folder(self):
        pairs = importplan.find_pairs(self.PATHS)
        self.assertEqual(pairs, [("/d/one.avg", "/d/one.vgd"),
                                 ("/d/two.AVG", "/d/TWO.vgd")])

    def test_no_pairs(self):
        self.assertEqual(importplan.find_pairs(["/d/a.avg", "/d/b.vgd"]), [])
        self.assertEqual(importplan.find_pairs([]), [])

    def test_choices(self):
        pairs = importplan.find_pairs(self.PATHS)
        avg = importplan.apply_choice(self.PATHS, pairs, "avg")
        self.assertEqual(avg, ["/d/one.avg", "/d/two.AVG", "/d/three.avg",
                               "/e/one.vgd", "/d/four.vms"])
        vgd = importplan.apply_choice(self.PATHS, pairs, "vgd")
        self.assertEqual(vgd, ["/d/one.vgd", "/d/TWO.vgd", "/d/three.avg",
                               "/e/one.vgd", "/d/four.vms"])
        self.assertEqual(importplan.apply_choice(self.PATHS, pairs, "both"),
                         self.PATHS)

    def test_per_pair_choice(self):
        pairs = importplan.find_pairs(self.PATHS)
        out = importplan.apply_choice(
            self.PATHS, pairs, {"/d/one.avg": "vgd", "/d/two.AVG": "avg"})
        self.assertNotIn("/d/one.avg", out)
        self.assertIn("/d/one.vgd", out)
        self.assertNotIn("/d/TWO.vgd", out)

    def test_unknown_choice(self):
        with self.assertRaises(ValueError):
            importplan.apply_choice(self.PATHS,
                                    importplan.find_pairs(self.PATHS), "zip")


if __name__ == "__main__":
    unittest.main()
