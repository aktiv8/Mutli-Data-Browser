"""The experiment report: a customer-ready PDF built from a workbook.

What goes in, and in what order, is a ``reportspec`` spec (the Report
Generator's choice; the old ``sections=`` argument is turned into one):
a **cover** (letterhead logo, title, customer / reference / operator / date),
the **summary**, **methods** and **calibration** texts, the list of **data
files**, the **metadata** of every file (tidied, as in the metadata PDF), the
**images** (camera pictures and SnapMaps, see ``imagepages``) and the saved
**figures** with their captions.

Text, tables and metadata are typeset with reportlab; consecutive ones flow
onto the same pages. The image and figure pages are drawn by the caller
(matplotlib, vector) through ``render_images`` and ``render_figure``. The parts
are joined in the spec's order with PyMuPDF, which also stamps a page footer.
No Tk here.
"""

from __future__ import annotations

import datetime
import io
import os
import tempfile
from xml.sax.saxutils import escape as xml_escape

import appinfo
import covers
import reportspec

SECTIONS = ("cover", "metadata", "images", "figures")   # the old names

_FLOW = ("cover", "summary", "methods", "calibration", "files", "metadata")


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


def _styles():
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=10,
                          leading=14)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8,
                           leading=10)
    return styles, body, small


def title_block(details, logo, art=None):
    """Flowables of the cover: the cover picture (``covers.Art``), letterhead,
    title and the details table."""
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import (Image, Paragraph, Spacer, Table,
                                    TableStyle)

    styles, body, _small = _styles()
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
    title = (details.get("title") or "").strip() or "Experiment report"
    story.append(Paragraph(xml_escape(title), styles["Title"]))
    story.append(Spacer(1, 4 * mm))

    date = (details.get("date") or "").strip() \
        or datetime.date.today().isoformat()
    rows = [(label, (details.get(key) or "").strip()) for label, key in
            (("Customer", "customer"), ("Reference", "reference"),
             ("Operator", "operator"))] + [("Date", date)]
    rows = [(k, v) for k, v in rows if v]
    if rows:
        tbl = Table([[k, Paragraph(xml_escape(v), body)] for k, v in rows],
                    colWidths=[35 * mm, 145 * mm])
        tbl.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (0, -1), 10),
            ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#2c3e50")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
        ]))
        story += [tbl, Spacer(1, 8 * mm)]
    return story


def text_block(heading, text):
    """A heading and the paragraphs of ``text`` ([] when there is none)."""
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer

    styles, body, _small = _styles()
    paras = _paragraphs(text)
    if not paras:
        return []
    story = [Paragraph(heading, styles["Heading2"])]
    for para in paras:
        story += [Paragraph(para, body), Spacer(1, 3 * mm)]
    return story


def files_table(file_rows, sha="short"):
    """The 'Data files' heading and table ([] when there are no files).
    ``sha``: "short" (16 characters) or "none" (no checksum column)."""
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    if not file_rows:
        return []
    styles, _body, small = _styles()
    with_sha = sha != "none"
    head = ["File", "Format", "Regions", "Size"] + (["SHA-256"] if with_sha
                                                    else [])
    table = [head]
    for r in file_rows:
        row = [Paragraph(xml_escape(r.get("name", "")), small),
               Paragraph(xml_escape(r.get("format", "")), small),
               str(r.get("regions", "")), _human_size(r.get("size", 0))]
        if with_sha:
            row.append((r.get("sha256") or "")[:16])
        table.append(row)
    widths = ([62, 44, 15, 20, 39] if with_sha else [86, 60, 16, 18])
    t = Table(table, repeatRows=1, colWidths=[w * mm for w in widths])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b0b0b0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return [Spacer(1, 4 * mm), Paragraph("Data files", styles["Heading2"]), t]


def _flow_story(items, details, logo, file_rows, docs, sha, art=None):
    """Flowables of consecutive reportlab sections. ``items`` is
    ``[(section id, skipped child ids)]``; ``art`` the cover picture."""
    from reportlab.platypus import PageBreak
    import exporters

    story = []
    methods_on = any(sid == "methods" for sid, _s in items)
    methods = (details.get("methods") or "").strip()
    for sid, skip in items:
        if sid == "cover":
            story += title_block(details, logo, art)
        elif sid == "summary":
            story += text_block("Summary", details.get("summary"))
        elif sid == "methods":
            story += text_block("Methods", methods)
        elif sid == "calibration":
            cal = (details.get("calibration") or "").strip()
            # the methods text usually states it: not twice on the same pages
            if cal and not (methods_on and cal in methods):
                story += text_block("Energy calibration", cal)
        elif sid == "files":
            story += files_table(file_rows, sha)
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
                story += exporters._metadata_story(
                    parser, samples, title=f"Acquisition metadata - {name}",
                    level=2, fname=name)
    return story


def _flow_pdf(path, story, details):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate

    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=16 * mm,
                            title=(details.get("title") or "").strip()
                            or "Experiment report")
    doc.build(story)


def _runs(items):
    """Split the ordered sections into runs of reportlab sections and single
    matplotlib ones: [("flow", [items]), ("images", ...), ("figures", ...)]."""
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


def build_report(path, details, logo, file_rows, docs, figures,
                 render_figure, sections=SECTIONS, render_images=None,
                 spec=None, cover_data=None, notes=None):
    """Write the report to ``path``; returns the number of pages.

    ``spec`` (see ``reportspec``) says which sections go in, in which order,
    which figures and files, and the cover picture; without it ``sections``
    (the old names) do. ``cover_data`` is ``(energy, counts)`` for the "your
    data" cover; a problem with the cover picture is appended to ``notes``.
    ``figures`` is a list of ``{"name", "caption", "state"}`` and
    ``render_figure(pdf, number, figure)`` draws that figure's pages onto a
    matplotlib ``PdfPages`` and returns how many it wrote.
    ``render_images(pdf)`` does the same for the camera-picture and SnapMap
    pages (None: there are none)."""
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
    art = None
    if any(sid == "cover" for sid, _s in items):
        art = covers.art(reportspec.cover_of(spec), "pdf", cover_data)
        if art.note and notes is not None:
            notes.append(art.note)
    with tempfile.TemporaryDirectory(prefix="xpsc_report_") as tmp:
        parts = []
        for k, (kind, run) in enumerate(_runs(items)):
            part = os.path.join(tmp, f"part{k}.pdf")
            if kind == "flow":
                story = _flow_story(run, details, logo, file_rows, docs, sha,
                                    art)
                if story:
                    _flow_pdf(part, story, details)
                    parts.append(part)
            elif kind == "images" and render_images is not None:
                from matplotlib.backends.backend_pdf import PdfPages
                with PdfPages(part) as pdf:
                    written = render_images(pdf)
                if written:
                    parts.append(part)
            elif kind == "figures" and figures:
                from matplotlib.backends.backend_pdf import PdfPages
                skip = run[0][1]
                chosen = [f for i, f in enumerate(figures, 1)
                          if reportspec.figure_id(f, i) not in skip]
                written = 0
                with PdfPages(part) as pdf:
                    for n, fig in enumerate(chosen, 1):
                        written += render_figure(pdf, n, fig)
                if written:
                    parts.append(part)
        if not parts:
            raise ReportError("Nothing to put in the report: choose at "
                              "least one section that has content.")
        out = mu.open()
        for part in parts:
            with mu.open(part) as src:
                out.insert_pdf(src)
        title = (details.get("title") or "").strip() or "Experiment report"
        total = out.page_count
        for i, page in enumerate(out, 1):
            page.insert_text(
                (36, page.rect.height - 16),
                f"{title} - report page {i} of {total}",
                fontsize=7.5, fontname="helv", color=(0.35, 0.35, 0.35))
        out.set_metadata({"title": title, "creator": appinfo.NAME})
        out.save(path, garbage=3, deflate=True)
        out.close()
    return total
