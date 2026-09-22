"""The redesigned PDF report: contents with real page numbers, bookmarks, the
footer and the look (milestone G4).

Run:  python -m unittest discover tests
"""

import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import pdfstyle  # noqa: E402
import reportspec as rs  # noqa: E402

try:
    import pymupdf as mupdf
except ImportError:
    try:
        import fitz as mupdf
    except ImportError:
        mupdf = None
try:
    import reportlab  # noqa: F401
    import matplotlib  # noqa: F401
    HAVE_PDF = mupdf is not None
except ImportError:
    HAVE_PDF = False


class TestLook(unittest.TestCase):
    def test_a_bad_accent_is_the_default_and_ink_is_darker(self):
        self.assertEqual(pdfstyle.look("nope").accent, "#2C3E50")
        amber = pdfstyle.look("#b7791f")
        self.assertEqual(amber.accent, "#B7791F")
        self.assertLess(sum(int(amber.ink[i:i + 2], 16) for i in (1, 3, 5)),
                        sum(int(amber.accent[i:i + 2], 16) for i in (1, 3, 5)))

    def test_the_bundled_typeface_is_used_when_it_loads(self):
        lk = pdfstyle.look()
        self.assertIn(lk.font, (pdfstyle.REGULAR, pdfstyle.FALLBACK[0]))
        self.assertEqual(lk.bold == pdfstyle.BOLD, lk.font == pdfstyle.REGULAR)

    def test_page_size_resolves_a4_or_letter(self):
        a4, a4_fig = pdfstyle.page_size("a4")
        letter, letter_fig = pdfstyle.page_size("letter")
        self.assertEqual((round(a4[0]), round(a4[1])), (595, 842))
        self.assertEqual((round(letter[0]), round(letter[1])), (612, 792))
        self.assertAlmostEqual(a4_fig[0], 11.69, places=1)
        self.assertAlmostEqual(a4_fig[1], 8.27, places=1)
        self.assertEqual(letter_fig, (11.0, 8.5))
        self.assertEqual(pdfstyle.page_size("nope")[0], a4)   # bad -> a4


class TestOldSpecs(unittest.TestCase):
    def test_a_spec_from_before_the_contents_gets_it_after_the_cover(self):
        old = {"sections": [{"id": i, "on": True} for i in
                            ("summary", "cover", "figures", "images", "methods",
                             "calibration", "metadata", "files")]}
        s = rs.sanitise(old)
        self.assertEqual(rs.order(s)[:4],
                         ["summary", "results", "cover", "contents"])
        self.assertTrue(rs.is_on(s, "contents"))
        self.assertEqual(rs.order(rs.sanitise({"sections": []})),
                         list(rs.SECTION_IDS))

    def test_the_old_section_names_have_no_contents(self):
        self.assertNotIn("contents", [i for i, _ in rs.active(
            rs.spec_from_sections(("cover", "figures"), "pdf"))])

    def test_presets(self):
        self.assertTrue(rs.is_on(rs.BUILTIN_PRESETS["Customer report"],
                                 "contents"))
        self.assertFalse(rs.is_on(rs.BUILTIN_PRESETS["Quick look"], "contents"))


@unittest.skipUnless(HAVE_PDF, "reportlab / PyMuPDF / matplotlib missing")
class TestReport(unittest.TestCase):
    def setUp(self):
        from test_metasummary import Doc, region
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.docs = [Doc([region("Survey", 160, step=1.0)], "a.vgd"),
                     Doc([region("Mo 3d", 40)], "b.vgd")]
        self.rows = [{"name": "a.vgd", "format": "Thermo", "regions": 1,
                      "size": 2048, "sha256": "ab" * 32}]
        self.details = {"title": "Kα study", "customer": "ACME",
                        "summary": "Everything worked.",
                        "methods": "Spectra were recorded.",
                        "calibration": "C 1s at 284.8 eV."}
        self.figs = [{"name": f"Fig {i}", "caption": "", "state": {}}
                     for i in range(1, 4)]

    def render(self, pdf, n, fig):
        from matplotlib.figure import Figure
        f = Figure(figsize=(11.7, 8.3))
        f.text(0.5, 0.5, f"figure {n} {fig['name']}")
        pdf.savefig(f)
        return 1

    def build(self, spec=None, figs=None):
        import report
        path = os.path.join(self.dir, "r.pdf")
        self.n = report.build_report(
            path, self.details, "", self.rows, self.docs,
            self.figs if figs is None else figs, self.render,
            spec=spec or rs.default_spec())
        self.doc = mupdf.open(path)
        self.addCleanup(self.doc.close)
        return [p.get_text() for p in self.doc]

    def test_the_contents_are_the_second_page_and_list_the_sections(self):
        pages = self.build()
        self.assertIn("Contents", pages[1])
        for token in ("Summary", "Figures", "Methods", "Energy calibration",
                      "Acquisition metadata", "Data files", "Fig 2"):
            self.assertIn(token, pages[1])

    def test_every_entry_points_at_the_page_it_names(self):
        pages = self.build()
        toc = self.doc.get_toc()
        self.assertTrue(toc)
        for level, title, page in toc:
            text = pages[page - 1]
            if title.startswith("Figure "):
                n, name = re.match(r"Figure (\d+) — (.*)", title).groups()
                self.assertIn(f"figure {n} {name}", text, title)
            elif title != "Contents" and not title.endswith(".vgd"):
                self.assertIn(title, text, title)
        # and the numbers printed on the contents page are the same ones
        printed = pages[1]
        for level, title, page in toc:
            if title == "Data files":
                self.assertRegex(printed, rf"Data files\s*\n?\s*{page}\b")

    def test_the_figure_pages_are_where_the_contents_say(self):
        pages = self.build()
        toc = {t: p for _l, t, p in self.doc.get_toc()}
        fig = next(p for t, p in toc.items() if t.startswith("Figure 3"))
        self.assertIn("figure 3", pages[fig - 1])

    def test_a_long_contents_list_still_has_true_numbers(self):
        figs = [{"name": f"F{i}", "caption": "", "state": {}}
                for i in range(1, 71)]
        pages = self.build(figs=figs)
        toc = self.doc.get_toc()
        at = {t: p for _l, t, p in toc}
        self.assertGreaterEqual(at["Summary"] - at["Contents"], 2)   # runs over
        last = next(p for _l, t, p in toc if t.startswith("Figure 70"))
        self.assertIn("figure 70 F70", pages[last - 1])
        first = next(p for _l, t, p in toc if t.startswith("Figure 1 "))
        self.assertEqual(last - first, 69)

    def test_bookmarks_come_with_or_without_the_contents_page(self):
        spec = rs.with_on(rs.default_spec(), "contents", False)
        pages = self.build(spec)
        self.assertNotIn("Contents", "\n".join(pages))
        self.assertTrue(self.doc.get_toc())

    def test_the_footer_names_the_section_and_the_cover_has_none(self):
        pages = self.build()
        self.assertNotIn("report page 1 of", pages[0])
        self.assertIn("report page 2 of %d" % self.n, pages[1])
        self.assertTrue(pages[1].rstrip().endswith("Contents"))    # the label
        self.assertRegex(pages[-1], r"report page %d of %d" % (self.n, self.n))
        toc = {t: p for _l, t, p in self.doc.get_toc()}
        self.assertIn("Figures", pages[toc["Figures"] - 1])
        self.assertIn("Kα study", pages[toc["Figures"] - 1])   # title in footer

    def test_the_greek_letter_survives(self):
        self.assertIn("Kα", self.build()[0])

    def test_page_size_option_changes_every_text_page(self):
        # no figures: isolate the text-flow pages report.py itself sizes
        # (a figure/image page's size is the caller's own responsibility,
        # verified separately against a real Workspace); separate paths and
        # docs so one is not still open (Windows locks it) when the other
        # writes.
        import report

        def sizes(name, spec):
            path = os.path.join(self.dir, name)
            report.build_report(path, self.details, "", self.rows,
                                self.docs, [], self.render, spec=spec)
            with mupdf.open(path) as doc:
                return {tuple(round(x, 1) for x in p.rect[2:]) for p in doc}
        self.assertEqual(sizes("a4.pdf", rs.default_spec()), {(595.3, 841.9)})
        self.assertEqual(
            sizes("letter.pdf", rs.with_option(rs.default_spec(), "page",
                                               "letter")),
            {(612.0, 792.0)})

    def test_contents_alone_is_not_a_report(self):
        import report
        spec = rs.with_all(rs.default_spec(), False)
        with self.assertRaises(report.ReportError):
            self.build(rs.with_on(spec, "contents", True))

    def test_the_accent_and_a_moved_contents_page(self):
        spec = rs.with_cover(rs.moved(rs.default_spec(), "contents", 3),
                             accent="#1F7A8C")
        pages = self.build(spec)
        self.assertNotIn("Contents", pages[1][:40])
        toc = {t: p for _l, t, p in self.doc.get_toc()}
        self.assertIn("Contents", pages[toc["Contents"] - 1])


if __name__ == "__main__":
    unittest.main()
