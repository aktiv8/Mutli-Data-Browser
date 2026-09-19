"""The experiment report: a customer-ready PDF built from a workbook.

Sections (each optional): a **cover** (letterhead logo, title, customer /
reference / operator / date, the free-text summary and the list of source
files), the **metadata** of every file (tidied, as in the metadata PDF) and
the saved **figures** with their captions.

Cover and metadata are typeset with reportlab; the figure pages are drawn by
the caller (matplotlib, vector) through ``render_figure``. The parts are
joined with PyMuPDF, which also stamps a page footer. No Tk here.
"""

from __future__ import annotations

import datetime
import os
import tempfile
from xml.sax.saxutils import escape as xml_escape

import appinfo

SECTIONS = ("cover", "metadata", "figures")


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


def cover_story(details, logo, file_rows):
    """Flowables for the cover page."""
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import (Image, Paragraph, Spacer, Table,
                                    TableStyle)

    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=10,
                          leading=14)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8,
                           leading=10)
    story = []
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

    paras = _paragraphs(details.get("summary"))
    if paras:
        story.append(Paragraph("Summary", styles["Heading2"]))
        for para in paras:
            story += [Paragraph(para, body), Spacer(1, 3 * mm)]

    methods = (details.get("methods") or "").strip()
    if methods:
        story.append(Paragraph("Methods", styles["Heading2"]))
        for para in _paragraphs(methods):
            story += [Paragraph(para, body), Spacer(1, 3 * mm)]

    cal = (details.get("calibration") or "").strip()
    if cal and cal not in methods:      # the methods text usually states it
        story += [Paragraph("Energy calibration", styles["Heading2"]),
                  Paragraph(xml_escape(cal), body), Spacer(1, 3 * mm)]

    if file_rows:
        story += [Spacer(1, 4 * mm),
                  Paragraph("Data files", styles["Heading2"])]
        table = [["File", "Format", "Regions", "Size", "SHA-256"]]
        for r in file_rows:
            table.append([Paragraph(xml_escape(r.get("name", "")), small),
                          Paragraph(xml_escape(r.get("format", "")), small),
                          str(r.get("regions", "")),
                          _human_size(r.get("size", 0)),
                          (r.get("sha256") or "")[:16]])
        t = Table(table, repeatRows=1,
                  colWidths=[62 * mm, 44 * mm, 15 * mm, 20 * mm, 39 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b0b0b0")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(t)
    return story


def _front_pdf(path, sections, details, logo, file_rows, docs):
    """Cover and/or metadata as one reportlab PDF. Returns False if empty."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, SimpleDocTemplate
    import exporters

    story = []
    if "cover" in sections:
        story += cover_story(details, logo, file_rows)
    if "metadata" in sections:
        for parser in docs:
            samples = parser.samples_metadata()
            if not samples:
                continue
            if story:
                story.append(PageBreak())
            name = os.path.basename(parser.path or "experiment")
            story += exporters._metadata_story(
                parser, samples, title=f"Acquisition metadata - {name}",
                level=2, fname=name)
    if not story:
        return False
    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=16 * mm,
                            title=(details.get("title") or "").strip()
                            or "Experiment report")
    doc.build(story)
    return True


def build_report(path, details, logo, file_rows, docs, figures,
                 render_figure, sections=SECTIONS):
    """Write the report to ``path``; returns the number of pages.

    ``figures`` is a list of ``{"name", "caption", "state"}`` and
    ``render_figure(pdf, number, figure)`` draws that figure's pages onto a
    matplotlib ``PdfPages`` and returns how many it wrote."""
    sections = tuple(s for s in SECTIONS if s in sections)
    try:
        import reportlab  # noqa: F401
    except ImportError:
        raise ReportError("The experiment report needs reportlab "
                          "(pip install reportlab).")
    mu = _mupdf()
    with tempfile.TemporaryDirectory(prefix="xpsc_report_") as tmp:
        parts = []
        front = os.path.join(tmp, "front.pdf")
        if _front_pdf(front, sections, details, logo, file_rows, docs):
            parts.append(front)
        if "figures" in sections and figures:
            from matplotlib.backends.backend_pdf import PdfPages
            figs = os.path.join(tmp, "figures.pdf")
            written = 0
            with PdfPages(figs) as pdf:
                for n, fig in enumerate(figures, 1):
                    written += render_figure(pdf, n, fig)
            if written:
                parts.append(figs)
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
