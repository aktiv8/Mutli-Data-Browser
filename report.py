"""The experiment report: a customer-ready PDF built from a workbook.

What goes in, and in what order, is a ``reportspec`` spec (the Report
Generator's choice; the old ``sections=`` argument is turned into one):
a **cover** (letterhead logo, title, customer / reference / operator / date),
the **contents** (sections and their pages), the **summary**, the
**quantification** (``resultspages``), **methods** and
**calibration** texts, the list of **data files**, the **metadata** of every
file (tidied, as in the metadata PDF), the **images** (camera pictures and
SnapMaps, see ``imagepages``) and the saved **figures** with their captions.

Text, tables and metadata are typeset with reportlab in the report's look
(``pdfstyle``: IBM Plex Sans, the cover's accent colour); consecutive ones
flow onto the same pages. The image and figure pages are drawn by the caller
(matplotlib, vector) through ``render_images`` and ``render_figure``. The parts
are joined in the spec's order with PyMuPDF, which also writes the PDF
bookmarks and stamps a footer (title, section, page x of y) on every page but
a leading cover. The contents are typeset last, once every part has said where
its headings fell, so its page numbers are the real ones. No Tk here.
"""

from __future__ import annotations

import datetime
import io
import os
import tempfile
from xml.sax.saxutils import escape as xml_escape

import appinfo
import covers
import pdfstyle
import reportspec

SECTIONS = ("cover", "metadata", "images", "figures")   # the old names

_FLOW = ("cover", "summary", "results", "methods", "calibration", "files",
         "metadata")
FOOTER_SIZE = 7.5
FOOTER_MARGIN = 36                       # points from the page edge


class ReportError(Exception):
    """The report could not be built (message is user-facing)."""


def _mupdf():
    try:
        import pymupdf as mu
    except ImportError:
        try:
            import fitz as mu
        except ImportError:
            raise ReportError("The experiment report needs PyMuPDF "
                              "(pip install pymupdf).")
    return mu


def _paragraphs(text):
    """Blank-line separated paragraphs of free text, escaped for reportlab
    with single line breaks kept."""
    out = []
    for block in (text or "").replace("\r\n", "\n").split("\n\n"):
        block = block.strip("\n")
        if block.strip():
            out.append(xml_escape(block).replace("\n", "<br/>"))
    return out


def _human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0


# -- headings that say where they landed ------------------------------------------
def _mark(flowable, sid, child=None):
    """Tag a heading so the page it lands on is recorded (``_Doc``): ``sid``
    is the report section, ``child`` a sub-entry (a file, a figure)."""
    flowable._mark = (sid, child)
    return flowable


def _marks_of(flowable):
    """The tags on a flowable and on what it holds (a heading kept with the
    next flowable is wrapped in a container)."""
    tag = getattr(flowable, "_mark", None)
    if tag:
        yield tag
    for sub in getattr(flowable, "_content", None) or ():
        yield from _marks_of(sub)


def _doc_class():
    from reportlab.platypus import SimpleDocTemplate

    class Doc(SimpleDocTemplate):
        """Records ``(section, child, page)`` for every tagged heading."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.marks = []

        def afterFlowable(self, flowable):
            for sid, child in _marks_of(flowable):
                self.marks.append((sid, child, self.page))

    return Doc


# -- the flowables of each section -----------------------------------------------
def title_block(details, logo, art=None, look=None):
    """Flowables of the cover: the cover picture (``covers.Art``), letterhead,
    an accent bar, the title and the details table."""
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import (Image, Paragraph, Spacer, Table,
                                    TableStyle)

    look = look or pdfstyle.look()
    st = pdfstyle.styles(look)
    story = []
    if art is not None and art.data:
        story += [Image(io.BytesIO(art.data), width=art.width * mm,
                        height=art.height * mm, hAlign="LEFT"),
                  Spacer(1, 8 * mm)]
    if logo and os.path.isfile(logo):
        try:
            w, h = ImageReader(logo).getSize()
            scale = min(70 * mm / w, 28 * mm / h)
            story += [Image(logo, width=w * scale, height=h * scale,
                            hAlign="LEFT"), Spacer(1, 6 * mm)]
        except Exception:
            pass                       # an unreadable logo must not stop a report
    bar = Table([[""]], colWidths=[24 * mm], rowHeights=[2.2 * mm],
                hAlign="LEFT")
    bar.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1),
                              colors.HexColor(look.accent))]))
    title = (details.get("title") or "").strip() or "Experiment report"
    story += [bar, Spacer(1, 4 * mm),
              Paragraph(xml_escape(title), st["title"]), Spacer(1, 4 * mm)]

    date = (details.get("date") or "").strip() \
        or datetime.date.today().isoformat()
    rows = [(label, (details.get(key) or "").strip()) for label, key in
            (("Customer", "customer"), ("Reference", "reference"),
             ("Operator", "operator"))] + [("Date", date)]
    rows = [(k, v) for k, v in rows if v]
    if rows:
        tbl = Table([[Paragraph(k, st["label"]),
                      Paragraph(xml_escape(v), st["body"])] for k, v in rows],
                    colWidths=[35 * mm, 145 * mm], hAlign="LEFT")
        tbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4,
             colors.HexColor(look.tint(0.8))),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
        ]))
        story += [tbl, Spacer(1, 8 * mm)]
    return story


def text_block(heading, text, look=None, sid=None):
    """A heading and the paragraphs of ``text`` ([] when there is none).
    ``sid`` tags the heading with its report section."""
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer

    st = pdfstyle.styles(look or pdfstyle.look())
    paras = _paragraphs(text)
    if not paras:
        return []
    head = Paragraph(heading, st["h1"])
    story = [_mark(head, sid) if sid else head]
    for para in paras:
        story += [Paragraph(para, st["body"]), Spacer(1, 3 * mm)]
    return story


def files_table(file_rows, sha="short", look=None):
    """The 'Data files' heading and table ([] when there are no files).
    ``sha``: "short" (16 characters) or "none" (no checksum column)."""
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    if not file_rows:
        return []
    look = look or pdfstyle.look()
    st = pdfstyle.styles(look)
    with_sha = sha != "none"
    head = ["File", "Format", "Regions", "Size"] + (["SHA-256"] if with_sha
                                                    else [])
    table = [head]
    for r in file_rows:
        row = [Paragraph(xml_escape(r.get("name", "")), st["small"]),
               Paragraph(xml_escape(r.get("format", "")), st["small"]),
               str(r.get("regions", "")), _human_size(r.get("size", 0))]
        if with_sha:
            row.append((r.get("sha256") or "")[:16])
        table.append(row)
    widths = ([62, 44, 15, 20, 39] if with_sha else [86, 60, 16, 18])
    t = Table(table, repeatRows=1, colWidths=[w * mm for w in widths])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(look.ink)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), look.font),
        ("FONTNAME", (0, 0), (-1, 0), look.bold),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor(look.tint(0.94))]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor(pdfstyle.RULE)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return [Spacer(1, 4 * mm), _mark(Paragraph("Data files", st["h1"]),
                                     "files"), t]


def _grid(header, rows, widths, look, right_from=1, kinds=None):
    """A styled table: ink header, banded rows, numbers right-aligned from
    column ``right_from``; rows whose kind (``kinds``) is "state" are set
    smaller and grey."""
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Table, TableStyle

    t = Table([list(header)] + [list(r) for r in rows], repeatRows=1,
              colWidths=[w * mm for w in widths])
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(look.ink)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), look.font),
        ("FONTNAME", (0, 0), (-1, 0), look.bold),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor(look.tint(0.94))]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor(pdfstyle.RULE)),
        ("ALIGN", (right_from, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for i, kind in enumerate(kinds or (), 1):
        if kind == "state":
            style += [("TEXTCOLOR", (0, i), (-1, i),
                       colors.HexColor("#555555")),
                      ("FONTSIZE", (0, i), (-1, i), 7.5)]
    t.setStyle(TableStyle(style))
    return t


def results_story(results, skip=(), look=None, sid="results"):
    """The Quantification section: how the numbers are made, then for each
    sample its composition (chart and table, one level) or its depth profile
    (chart and table), and the notes."""
    from reportlab.lib.units import mm
    from reportlab.platypus import (CondPageBreak, Image, KeepTogether,
                                    Paragraph, Spacer)
    import resultspages

    samples = results.chosen(skip) if results else []
    if not samples:
        return []
    look = look or pdfstyle.look()
    st = pdfstyle.styles(look)
    story = [_mark(Paragraph("Quantification", st["h1"]), sid),
             Paragraph(xml_escape(results.method), st["small"]),
             Spacer(1, 3 * mm)]
    for s in samples:
        story.append(CondPageBreak(70 * mm))
        head = _mark(Paragraph(xml_escape(s.label), st["h2"]), sid, s.label)
        if not s.is_profile:
            rows = resultspages.composition_cells(s.levels[0])
            cpng = resultspages.composition_png(s.levels[0], size=(7.0, 3.0),
                                                dpi=200)
            block = [head]
            if cpng:
                block.append(Image(io.BytesIO(cpng), width=170 * mm,
                                   height=170 * mm * 3.0 / 7.0,
                                   hAlign="LEFT"))
            block.append(_grid(resultspages.COMPOSITION_HEADER,
                               [c for _k, c in rows],
                               [36, 26, 18, 32, 26, 20, 22], look,
                               right_from=2, kinds=[k for k, _c in rows]))
            story += block
            if resultspages.has_survey_rows(s.levels[0]):
                story.append(Paragraph(
                    xml_escape(resultspages.SURVEY_FOOTNOTE), st["small"]))
            continue
        png = resultspages.profile_png(s, size=(7.0, 3.0), dpi=200)
        block = [head]
        if png:
            block.append(Image(io.BytesIO(png), width=170 * mm,
                               height=170 * mm * 3.0 / 7.0, hAlign="LEFT"))
        story += block
        header, rows = resultspages.profile_cells(s)
        first = 30 if len(header) > 6 else 40
        rest = (180 - first) / max(1, len(header) - 1)
        story += [Spacer(1, 2 * mm),
                  _grid(header, rows, [first] + [rest] * (len(header) - 1),
                        look)]
    notes = results.notes_for(samples)
    if notes:
        story.append(Spacer(1, 3 * mm))
        for note in notes:
            story.append(Paragraph("• " + xml_escape(note), st["small"]))
    return story


def contents_story(entries, look=None):
    """The contents page: ``entries`` is ``[(level, title, page)]``."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table, TableStyle

    look = look or pdfstyle.look()
    st = pdfstyle.styles(look)
    head = ParagraphStyle("contents", parent=st["h1"], spaceBefore=0,
                          spaceAfter=10)
    rows, rules = [], []
    for level, title, page in entries:
        main = st["toc1"] if level == 1 else st["toc2"]
        right = ParagraphStyle(f"page{level}", parent=main, alignment=TA_RIGHT,
                               leftIndent=0)
        if level == 1:
            rules.append(len(rows))
        rows.append([Paragraph(xml_escape(title), main),
                     Paragraph(str(page), right)])
    story = [Paragraph("Contents", head)]
    if rows:
        tbl = Table(rows, colWidths=[160 * mm, 20 * mm], hAlign="LEFT")
        style = [("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                 ("LEFTPADDING", (0, 0), (-1, -1), 0),
                 ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                 ("TOPPADDING", (0, 0), (-1, -1), 2),
                 ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
        for i in rules:
            style += [("LINEABOVE", (0, i), (-1, i), 0.5,
                       colors.HexColor(look.tint(0.7))),
                      ("TOPPADDING", (0, i), (-1, i), 7)]
        tbl.setStyle(TableStyle(style))
        story.append(tbl)
    return story


def _flow_story(items, details, logo, file_rows, docs, sha, art=None,
                look=None, results=None):
    """Flowables of consecutive reportlab sections. ``items`` is
    ``[(section id, skipped child ids)]``; ``art`` the cover picture."""
    from reportlab.platypus import PageBreak
    import exporters

    look = look or pdfstyle.look()
    story = []
    methods_on = any(sid == "methods" for sid, _s in items)
    methods = (details.get("methods") or "").strip()
    for sid, skip in items:
        if sid == "cover":
            story += title_block(details, logo, art, look)
        elif sid == "summary":
            story += text_block("Summary", details.get("summary"), look, sid)
        elif sid == "results":
            story += results_story(results, skip, look, sid)
        elif sid == "methods":
            story += text_block("Methods", methods, look, sid)
        elif sid == "calibration":
            cal = (details.get("calibration") or "").strip()
            # the methods text usually states it: not twice on the same pages
            if cal and not (methods_on and cal in methods):
                story += text_block("Energy calibration", cal, look, sid)
        elif sid == "files":
            story += files_table(file_rows, sha, look)
        elif sid == "metadata":
            for parser in docs:
                if reportspec.doc_key(parser) in skip:
                    continue
                samples = parser.samples_metadata()
                if not samples:
                    continue
                if story:
                    story.append(PageBreak())
                name = os.path.basename(parser.path or "experiment")
                part = exporters._metadata_story(
                    parser, samples, title=f"Acquisition metadata - {name}",
                    level=2, fname=name, look=look)
                _mark(part[0], sid, name)
                story += part
    return story


def _build_pdf(path, story, details, look, pagesize=None):
    """Typeset ``story`` (portrait; A4 unless ``pagesize`` says otherwise, see
    ``pdfstyle.page_size``) to ``path``; returns the tagged headings as
    ``[(section, child, page)]``."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm

    doc = _doc_class()(path, pagesize=pagesize or A4,
                       leftMargin=15 * mm, rightMargin=15 * mm,
                       topMargin=15 * mm, bottomMargin=16 * mm,
                       title=(details.get("title") or "").strip()
                       or "Experiment report", author=appinfo.NAME)
    doc.build(story)
    return doc.marks


def _page_count(mu, path):
    with mu.open(path) as src:
        return src.page_count


def _runs(items):
    """Split the ordered sections into runs of reportlab sections and single
    ones: [("flow", [items]), ("contents", ...), ("images", ...), ...]."""
    runs = []
    for item in items:
        if item[0] in _FLOW:
            if runs and runs[-1][0] == "flow":
                runs[-1][1].append(item)
            else:
                runs.append(("flow", [item]))
        else:
            runs.append((item[0], [item]))
    return runs


# -- the contents and the bookmarks ----------------------------------------------
def _starts(parts):
    """The report page each part begins on."""
    out, page = [], 1
    for part in parts:
        out.append(page)
        page += part["pages"]
    return out


def _entries(parts):
    """``[(section, level, title, page)]`` for the contents and the PDF
    bookmarks: one line per section, and under it the files or figures when
    there are two or more."""
    heads, kids = {}, {}
    order = []
    for part, start in zip(parts, _starts(parts)):
        for sid, child, page in part["marks"]:
            at = start + page - 1
            if sid not in heads:
                heads[sid] = at
                order.append(sid)
            if child:
                kids.setdefault(sid, []).append((child, at))
    out = []
    for sid in order:
        out.append((sid, 1, reportspec.LABELS[sid], heads[sid]))
        if len(kids.get(sid, ())) >= 2:
            out += [(sid, 2, title, at) for title, at in kids[sid]]
    return out


def _page_sections(parts):
    """The section each report page belongs to (for the footer): the last
    tagged heading at or before it, else the part's own section."""
    out = []
    for part in parts:
        for page in range(1, part["pages"] + 1):
            sid = part["sid"]
            for tag, _child, at in part["marks"]:
                if at <= page:
                    sid = tag
            out.append(sid)
    return out


def _footer(out, mu, title, sections, look, skip_first):
    """Stamp the title, the section and 'report page x of y' on every page."""
    total = out.page_count
    path = pdfstyle.font_file()
    font = None
    if path:
        try:
            font = mu.Font(fontfile=path)
        except Exception:                    # noqa: BLE001 - fall back to helv
            font = None
    name = "plex" if font else "helv"

    def width(text):
        if font:
            return font.text_length(text, fontsize=FOOTER_SIZE)
        return mu.get_text_length(text, fontname="helv", fontsize=FOOTER_SIZE)

    def put(page, x, y, text, colour):
        kw = {"fontfile": path} if font else {}
        page.insert_text((x, y), text, fontsize=FOOTER_SIZE, fontname=name,
                         color=colour, **kw)

    muted = pdfstyle.rgb(pdfstyle.MUTED)
    ink = pdfstyle.rgb(look.ink)
    for i, page in enumerate(out, 1):
        if i == 1 and skip_first:
            continue
        y, right = page.rect.height - 16, page.rect.width - FOOTER_MARGIN
        put(page, FOOTER_MARGIN, y, title, muted)
        count = f"report page {i} of {total}"
        put(page, right - width(count), y, count, muted)
        label = reportspec.LABELS.get(sections[i - 1], "")
        if label:
            gap = width(count) + width("   ")
            put(page, right - gap - width(label), y, label, ink)


def build_report(path, details, logo, file_rows, docs, figures,
                 render_figure, sections=SECTIONS, render_images=None,
                 spec=None, cover_data=None, notes=None, results=None):
    """Write the report to ``path``; returns the number of pages.

    ``spec`` (see ``reportspec``) says which sections go in, in which order,
    which figures and files, and the cover picture and accent colour; without
    it ``sections`` (the old names) do. ``cover_data`` is ``(energy, counts)``
    for the "your data" cover; a problem with the cover picture is appended to
    ``notes``. ``figures`` is a list of ``{"name", "caption", "state"}`` and
    ``render_figure(pdf, number, figure)`` draws that figure's pages onto a
    matplotlib ``PdfPages`` and returns how many it wrote.
    ``render_images(pdf)`` does the same for the camera-picture and SnapMap
    pages (None: there are none). ``results`` is the ``resultspages.Results``
    the Quantification section is made from (None: there is none)."""
    if spec is None:
        spec = reportspec.spec_from_sections(sections, "pdf")
    sha = reportspec.option(spec, "sha")
    items = reportspec.active(spec)
    try:
        import reportlab  # noqa: F401
    except ImportError:
        raise ReportError("The experiment report needs reportlab "
                          "(pip install reportlab).")
    mu = _mupdf()
    look = pdfstyle.look(reportspec.cover_of(spec)["accent"])
    pagesize = pdfstyle.page_size(reportspec.option(spec, "page"))[0]
    art = None
    if any(sid == "cover" for sid, _s in items):
        art = covers.art(reportspec.cover_of(spec), "pdf", cover_data)
        if art.note and notes is not None:
            notes.append(art.note)
    title = (details.get("title") or "").strip() or "Experiment report"
    with tempfile.TemporaryDirectory(prefix="xpsc_report_") as tmp:
        parts = []              # in report order: path, pages, marks, sid

        def add(k, kind, sid, pages, marks):
            if pages:
                parts.append({"path": os.path.join(tmp, f"part{k}.pdf"),
                              "kind": kind, "sid": sid, "pages": pages,
                              "marks": marks})

        for k, (kind, run) in enumerate(_runs(items)):
            part = os.path.join(tmp, f"part{k}.pdf")
            if kind == "contents":
                parts.append({"path": part, "kind": "contents",
                              "sid": "contents", "pages": 1,
                              "marks": [("contents", None, 1)]})
            elif kind == "flow":
                story = _flow_story(run, details, logo, file_rows, docs, sha,
                                    art, look, results)
                if story:
                    marks = _build_pdf(part, story, details, look, pagesize)
                    add(k, kind, run[0][0], _page_count(mu, part), marks)
            elif kind == "images" and render_images is not None:
                from matplotlib.backends.backend_pdf import PdfPages
                with PdfPages(part) as pdf:
                    written = render_images(pdf)
                add(k, kind, "images", written and _page_count(mu, part),
                    [("images", None, 1)])
            elif kind == "figures" and figures:
                from matplotlib.backends.backend_pdf import PdfPages
                skip = run[0][1]
                chosen = [f for i, f in enumerate(figures, 1)
                          if reportspec.figure_id(f, i) not in skip]
                marks, at = [], 1
                with PdfPages(part) as pdf:
                    for n, fig in enumerate(chosen, 1):
                        name = (fig.get("name") or "").strip()
                        written = render_figure(pdf, n, fig)
                        if written:
                            marks.append(("figures", f"Figure {n}"
                                          + (f" — {name}" if name else ""),
                                          at))
                            at += written
                add(k, kind, "figures", at - 1, marks)
        parts = [p for p in parts if p["pages"]]

        contents = next((p for p in parts if p["kind"] == "contents"), None)
        if contents is not None:
            # the page numbers depend on how many pages the contents take, and
            # that on how many lines there are: settle it (it does not move)
            for _try in range(3):
                listed = [(lvl, text, at) for sid, lvl, text, at
                          in _entries(parts) if sid != "contents"]
                if not listed:
                    parts.remove(contents)
                    break
                _build_pdf(contents["path"], contents_story(listed, look),
                           details, look, pagesize)
                pages = _page_count(mu, contents["path"])
                if pages == contents["pages"]:
                    break
                contents["pages"] = pages
        if not parts:
            raise ReportError("Nothing to put in the report: choose at "
                              "least one section that has content.")
        out = mu.open()
        for part in parts:
            with mu.open(part["path"]) as src:
                out.insert_pdf(src)
        outline = [[lvl, text, at] for _sid, lvl, text, at in _entries(parts)]
        if outline and outline[0][0] == 1:
            try:
                out.set_toc(outline)
            except Exception:                # noqa: BLE001 - bookmarks are extra
                pass
        _footer(out, mu, title, _page_sections(parts), look,
                skip_first=bool(items) and items[0][0] == "cover")
        out.set_metadata({"title": title, "creator": appinfo.NAME})
        total = out.page_count
        out.save(path, garbage=3, deflate=True)
        out.close()
    return total
