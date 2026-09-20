"""Writers: CSV, VAMAS (ISO 14976) and per-sample metadata (CSV / PDF).

They work on ``Region`` objects only, so any format the readers can load can
be exported (e.g. Thermo .avg -> VAMAS)."""

from __future__ import annotations

import os
import re
import csv
import math
import struct
import datetime

import casafit
import metasummary
import vamasmeta

# ==========================================================================
#  EXPORTERS
# ==========================================================================
def fit_columns(r, pre=""):
    """CSV columns ``[(header, values)]`` for a region's CasaXPS fit: the
    background, each component (above the background, as CasaXPS draws it)
    and the envelope, on the spectrum's own points, in its own units. Empty
    when the region has no fit (or numpy is missing)."""
    fit = getattr(r, "fit", None)
    if fit is None or not r.photon_energy:
        return []
    try:
        cvs = casafit.curves(fit, r.energy, r.counts, r.photon_energy,
                             *r.dwell_and_scans())
    except ImportError:
        return []
    cols = []
    for cv in cvs:
        tag = f"{pre}{r.name} fit" + (f" [{cv.region}]" if len(cvs) > 1 else "")
        if cv.background is not None:
            cols.append((f"{tag}: background", cv.background))
        for comp, vals in cv.components:
            cols.append((f"{tag}: {comp.name}", vals))
        if cv.envelope is not None:
            cols.append((f"{tag}: envelope", cv.envelope))
    return cols


def export_csv(regions, path, include_fits=True):
    """Export selected regions to a single CSV (wide format). A region with a
    CasaXPS fit gets its background, components and envelope as extra
    columns (``include_fits=False`` leaves them out)."""
    usable = [r for r in regions if r.decodable and r.counts]
    if not usable:
        raise ValueError("None of the selected regions contain decodable data.")
    cols = []
    maxlen = 0
    for r in usable:
        pre = f"{r.sample} " if r.sample else ""
        cols.append((f"{pre}{r.name} {r.energy_label} ({r.energy_units})", r.energy))
        cols.append((f"{pre}{r.name} {r.count_label} ({r.count_units})", r.counts))
        if include_fits:
            cols += fit_columns(r, pre)
        maxlen = max(maxlen, len(r.counts))
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([c[0] for c in cols])
        for i in range(maxlen):
            row = [("" if (i >= len(c[1]) or c[1][i] != c[1][i]) else c[1][i])
                   for c in cols]
            w.writerow(row)
    return len(usable)


def export_vamas(regions, path, institution="Not specified",
                 instrument="", operator="", experiment_id="",
                 sample_id="Sample", include_transmission=True,
                 metadata=None, experiment_metadata=None):
    """Export selected regions as a VAMAS (ISO 14976) file.

    Sequential block layout: experiment mode NORM, scan mode REGULAR,
    technique XPS, kinetic-energy abscissa. When the spectrometer transmission
    function is available it is written as a second corresponding variable
    ("Transmission"), interleaved with intensity, matching CasaXPS exports.
    Only regions with decodable data are written.

    ``metadata`` (one dict per input region, e.g. ``parser.region_metadata``)
    is written into the block comments and ``experiment_metadata`` (default:
    what every region agrees on) into the file header, inside a delimited
    block (see ``vamasmeta``), so reading the file back restores it.
    """
    pairs = [(r, metadata[i] if metadata and i < len(metadata) else None)
             for i, r in enumerate(regions) if r.decodable and r.counts]
    usable = [r for r, _m in pairs]
    if not usable:
        raise ValueError("None of the selected regions contain decodable data.")
    metas = [m for _r, m in pairs]
    exp_md = (experiment_metadata if experiment_metadata is not None
              else vamasmeta.common_experiment([m for m in metas if m]))
    header_comment = vamasmeta.encode(exp_md, vamasmeta.EXPERIMENT_KEYS)

    L = []
    a = L.append

    # ---- experiment header ----
    a("VAMAS Surface Chemical Analysis Standard Data Transfer Format 1988 May 4")
    a(institution)
    a(instrument)
    a(operator)
    a(experiment_id)
    a(str(len(header_comment)))   # number of lines in comment
    for c in header_comment:
        a(c)
    a("NORM")         # experiment mode
    a("REGULAR")      # scan mode
    a(str(len(usable)))  # number of spectral regions (NORM)
    a("0")            # number of experimental variables
    a("0")            # parameter inclusion/exclusion list entries
    a("0")            # manually entered items in block
    a("0")            # future-upgrade experiment entries
    a("0")            # future-upgrade block entries
    a(str(len(usable)))  # number of blocks

    now = datetime.datetime.now()
    SENT = "1E+37"    # VAMAS "not specified" sentinel
    for r, md in pairs:
        hv = r.photon_energy if r.photon_energy else 1486.69
        # Kinetic-energy abscissa (matches CasaXPS and the transmission axis).
        ke = r.kinetic_energy or [hv - be for be in r.energy]
        ke0 = ke[0]
        dke = (ke[1] - ke[0]) if len(ke) > 1 else 1.0
        counts = r.counts
        trans = r.transmission() if include_transmission else None
        n_cv = 2 if trans else 1
        anode = (r.anode.split()[0] if r.anode else "Al")  # element only
        power = ""
        if r.conditions.get("X-ray Power"):
            power = r.conditions["X-ray Power"].replace("W", "").strip()
        per_sweep, n_scans = r.dwell_and_scans()   # VAMAS: time per scan
        dwell = f"{per_sweep:.6g}" if per_sweep else SENT

        a(r.name)                 # block identifier
        a(r.sample or sample_id)  # sample identifier
        a(str(now.year)); a(str(now.month)); a(str(now.day))
        a(str(now.hour)); a(str(now.minute)); a(str(now.second))
        a("0")                    # hours in advance of GMT
        # block comment: include etch info for depth profiles
        comment = list(casafit.to_lines(getattr(r, "fit", None)))
        cc = r.extra.get("casa_calib") if r.calibration_shift else None
        if cc and not any(str(c).strip().startswith("Calib") for c in comment):
            # the charge correction the source file recorded travels as a
            # Calib line (the CasaXPS convention), not in the axis
            comment.insert(0, casafit.calib_line(cc["measured"],
                                                 cc["assigned"]))
        if r.etch_level is not None:
            comment.append(f"Etch level : {r.etch_level}")
        if r.etch_time is not None:
            comment.append(f"Etch time (s) : {r.etch_time:g}")
        if md:
            comment += vamasmeta.encode(
                {k: v for k, v in md.items()
                 if k not in vamasmeta.EXPERIMENT_KEYS})
        a(str(len(comment)))      # lines in block comment
        for c in comment:
            a(c)
        a("XPS")                  # technique
        a(anode)                  # analysis source label
        # A display copy already carries the file's own correction in hv and
        # the binding energies; the Calib line brings it back on reading, so
        # the axis keeps only what the user added on top.
        a(f"{hv - (r.calibration_shift if r.shift_applied else 0.0):.10g}")
                                  # source characteristic energy
        a(power or SENT)          # source strength (W)
        a(SENT)                   # beam width x
        a(SENT)                   # beam width y
        a(SENT)                   # source polar angle of incidence
        a(SENT)                   # source azimuth
        a("FAT")                  # analyser mode
        a(f"{r.pass_energy:g}" if r.pass_energy else SENT)  # pass energy
        a(SENT)                   # magnification of transfer lens
        a("-4.5")                 # analyser work function
        a(SENT)                   # target bias
        a(SENT)                   # analysis width x
        a(SENT)                   # analysis width y
        a(SENT)                   # take-off polar angle
        a(SENT)                   # take-off azimuth
        a(r.name)                 # species label
        a("")                     # transition / charge state label
        a("-1")                   # charge of detected particle
        # (scan mode REGULAR)
        a("Kinetic energy")       # abscissa label
        a("eV")                   # abscissa units
        a(f"{ke0:.10g}")          # abscissa start
        a(f"{dke:.10g}")          # abscissa increment
        a(str(n_cv))              # number of corresponding variables
        a("Intensity"); a("d")    # corresponding var 1: label, units
        if trans:
            a("Transmission"); a("d")   # corresponding var 2
        a("pulse counting")       # signal mode
        a(dwell)                  # signal collection time (s)
        a(str(n_scans))           # number of scans
        a("0")                    # signal time correction
        a(SENT)                   # sample normal polar angle of tilt
        a(SENT)                   # sample normal tilt azimuth
        a(SENT)                   # sample rotation angle
        a("0")                    # additional numerical parameters

        def fc(v):                # count: integer when whole, else 8 sig figs
            return str(int(round(v))) if abs(v - round(v)) < 1e-6 else f"{v:.8g}"

        def ft(v):                # transmission: high precision
            return f"{v:.12g}"

        a(str(len(counts) * n_cv))             # number of ordinate values
        a(fc(min(counts)))                     # var 1 min
        a(fc(max(counts)))                     # var 1 max
        if trans:
            a(ft(min(trans)))                  # var 2 min
            a(ft(max(trans)))                  # var 2 max
        # ordinate values, interleaved per point
        if trans:
            for c, t in zip(counts, trans):
                a(fc(c))
                a(ft(t))
        else:
            for c in counts:
                a(fc(c))

    a("end of experiment")
    # Latin-1: what other VAMAS software (CasaXPS) reads; anything beyond it
    # was escaped in the metadata block, other fields fall back to "?"
    with open(path, "w", newline="\r\n", encoding="latin-1",
              errors="replace") as fh:
        fh.write("\n".join(L) + "\n")
    return len(usable)


def export_metadata_csv(parser, path):
    """Write one row of acquisition metadata per region."""
    rows = parser.metadata_rows()
    if not rows:
        raise ValueError("No regions found to export metadata for.")
    fields = []
    for row in rows:                       # union, in first-seen order
        for k in row:
            if k not in fields:
                fields.append(k)
    # UTF-8 with a BOM (Excel opens it as such): the Windows default codec
    # cannot hold the "Kα" of "Al Kα" that every Avantage file carries
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, restval="")
        w.writeheader()
        for row in rows:
            w.writerow(row)
    return len(rows)


def export_metadata_pdf(parser, path):
    """Write a formatted, per-sample metadata report as PDF.

    Uses reportlab if available (nicer tables); otherwise falls back to a
    matplotlib-rendered PDF so the feature works with the base dependencies.
    """
    samples = parser.samples_metadata()
    if not samples:
        raise ValueError("No regions found to export metadata for.")
    try:
        return _metadata_pdf_reportlab(parser, samples, path)
    except ImportError:
        return _metadata_pdf_matplotlib(parser, samples, path)


NAVY = "#2c3e50"
PAGE_MARGIN_MM = 15
TEXT_WIDTH_MM = 210 - 2 * PAGE_MARGIN_MM          # portrait A4


def _metadata_story(parser, samples, title="Acquisition Metadata",
                    level=1, fname=None):
    """Flowables for one file's metadata report (portrait A4, 180 mm wide).

    Shared by the metadata PDF and the experiment report. What is the same
    for the whole file is stated once, what is constant within a sample sits
    on the sample's line, and the rest is a compact scan table; nothing is
    dropped (see ``metasummary.layout_file``)."""
    from xml.sax.saxutils import escape as xml_escape
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (CondPageBreak, KeepTogether, Paragraph,
                                    Spacer, Table, TableStyle)

    lay = metasummary.layout_file(samples)
    navy = colors.HexColor(NAVY)
    styles = getSampleStyleSheet()
    head = styles["Heading%d" % level]
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8,
                           leading=10)
    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=7.5,
                          leading=9)
    key_style = ParagraphStyle("key", parent=cell, fontName="Helvetica-Bold",
                               textColor=navy)
    sample_style = ParagraphStyle("sample", parent=styles["Normal"],
                                  fontName="Helvetica-Bold", fontSize=10.5,
                                  leading=13, textColor=navy, spaceBefore=9,
                                  spaceAfter=3)
    strip_head = ParagraphStyle("strip", parent=cell, fontSize=7,
                                fontName="Helvetica-Bold", spaceBefore=4,
                                spaceAfter=1)
    tiny = ParagraphStyle("tiny", parent=cell, fontSize=6.5, leading=8)

    def P(text, style=cell):
        return Paragraph(xml_escape(str(text)), style)

    def kv_grid(items, per_row=3):
        """Key / value pairs, ``per_row`` pairs across."""
        rows = []
        for i in range(0, len(items), per_row):
            chunk = items[i:i + per_row]
            row = []
            for k, v in chunk:
                row += [P(metasummary.SHORT.get(k, k), key_style), P(v)]
            row += [""] * (2 * per_row - len(row))
            rows.append(row)
        lab, val = 24 * mm, (TEXT_WIDTH_MM * mm / per_row) - 24 * mm
        t = Table(rows, colWidths=[lab, val] * per_row)
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        return t

    table_style = [
        ("BACKGROUND", (0, 0), (-1, 0), navy),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7.5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#c8d0d8")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f2f5f8")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]

    story = []
    fname = fname or os.path.basename(parser.path or "experiment")
    story.append(Paragraph(xml_escape(title), head))
    story.append(Paragraph(
        f"File: {xml_escape(fname)} &nbsp;|&nbsp; "
        + (f"{xml_escape(parser.format_name)} &nbsp;|&nbsp; "
           if getattr(parser, "format_name", "") else "")
        + f"Samples: {len(samples)} &nbsp;|&nbsp; "
        f"Regions: {lay.n_regions} &nbsp;|&nbsp; "
        f"Generated: {datetime.datetime.now():%Y-%m-%d %H:%M}", small))
    if parser.corruption["corrupted"]:
        story.append(Paragraph(
            "<font color='red'>Warning: this file's binary data is corrupted; "
            "numeric values may be unavailable.</font>", small))
    story.append(Spacer(1, 3 * mm))

    if lay.common:
        story.append(Paragraph("Common to every region", strip_head))
        story.append(kv_grid(lay.common))

    for sl in lay.samples:
        story.append(CondPageBreak(45 * mm))
        story.append(Paragraph(
            f"{xml_escape(sl.name)} "
            f"<font size='8' color='#6b7785'>&nbsp;{sl.n_regions} "
            f"region{'s' if sl.n_regions != 1 else ''}</font>",
            sample_style))
        if sl.line:
            story.append(kv_grid(sl.line))
            story.append(Spacer(1, 1.5 * mm))
        weights = metasummary.column_weights(sl.columns)
        total = sum(weights)
        widths = [TEXT_WIDTH_MM * mm * w / total for w in weights]
        data = [[P(c, ParagraphStyle("h", parent=cell, textColor=colors.white,
                                     fontName="Helvetica-Bold"))
                 for c in sl.columns]]
        for row in sl.rows:
            data.append([P(row.get(c, "")) for c in sl.columns])
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle(table_style))
        story.append(t)

        for title_, entries in sl.strips:
            story.append(Paragraph(xml_escape(title_), strip_head))
            per_col = -(-len(entries) // 3)                 # ceil
            blocks = [entries[i * per_col:(i + 1) * per_col]
                      for i in range(3)]
            head_row = []
            for _ in range(3):
                head_row += [P("Level", tiny), P("Etch (s)", tiny),
                             P("Acquired", tiny)]
            grid = [head_row]
            for r in range(per_col):
                line = []
                for b in blocks:
                    line += ([P(x, tiny) for x in b[r]] if r < len(b)
                             else [P("", tiny)] * 3)
                grid.append(line)
            w = TEXT_WIDTH_MM * mm / 3
            st = Table(grid, colWidths=[w * 0.16, w * 0.22, w * 0.62] * 3,
                       repeatRows=1)
            st.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.4, navy),
                ("TOPPADDING", (0, 0), (-1, -1), 0.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("LINEAFTER", (2, 0), (2, -1), 0.25, colors.HexColor("#c8d0d8")),
                ("LINEAFTER", (5, 0), (5, -1), 0.25, colors.HexColor("#c8d0d8")),
            ]))
            story.append(st)
    return story


def _numbered_canvas():
    """A canvas class that writes 'Page x of y' at the foot of every page."""
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm

    class NumberedCanvas(canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                self.setFont("Helvetica", 7.5)
                self.setFillGray(0.4)
                self.drawRightString(A4[0] - PAGE_MARGIN_MM * mm, 8 * mm,
                                     f"Page {self._pageNumber} of {total}")
                super().showPage()
            super().save()

    return NumberedCanvas


def _metadata_pdf_reportlab(parser, samples, path):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate

    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=PAGE_MARGIN_MM * mm,
                            rightMargin=PAGE_MARGIN_MM * mm,
                            topMargin=PAGE_MARGIN_MM * mm,
                            bottomMargin=16 * mm,
                            title="Acquisition metadata")
    doc.build(_metadata_story(parser, samples),
              canvasmaker=_numbered_canvas())
    return len(samples)


def _metadata_pdf_matplotlib(parser, samples, path):
    """Plain-text fallback (no reportlab): the same content, monospaced."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    lay = metasummary.layout_file(samples)
    fname = os.path.basename(parser.path or "experiment")
    lines = [f"Acquisition metadata - {fname}", ""]
    if lay.common:
        lines.append("Common to every region")
        lines += [f"  {k}: {v}" for k, v in lay.common]
        lines.append("")
    for sl in lay.samples:
        lines.append(f"{sl.name}  ({sl.n_regions} regions)")
        lines += [f"  {k}: {v}" for k, v in sl.line]
        lines.append("  " + " | ".join(sl.columns))
        for row in sl.rows:
            lines.append("  " + " | ".join(row.get(c, "")
                                           for c in sl.columns))
        for title_, entries in sl.strips:
            lines.append(f"  {title_}")
            lines += [f"    level {a}  etch {b} s  {c}"
                      for a, b, c in entries]
        lines.append("")
    per_page = 78
    with PdfPages(path) as pdf:
        for i in range(0, len(lines), per_page):
            fig = plt.figure(figsize=(8.3, 11.7))
            fig.text(0.05, 0.97, "\n".join(lines[i:i + per_page]), va="top",
                     fontsize=7, family="monospace")
            pdf.savefig(fig)
            plt.close(fig)
    return len(samples)
