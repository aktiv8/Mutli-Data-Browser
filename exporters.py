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

import metasummary

# ==========================================================================
#  EXPORTERS
# ==========================================================================
def export_csv(regions, path):
    """Export selected regions to a single CSV (wide format)."""
    usable = [r for r in regions if r.decodable and r.counts]
    if not usable:
        raise ValueError("None of the selected regions contain decodable data.")
    cols = []
    maxlen = 0
    for r in usable:
        pre = f"{r.sample} " if r.sample else ""
        cols.append((f"{pre}{r.name} {r.energy_label} ({r.energy_units})", r.energy))
        cols.append((f"{pre}{r.name} {r.count_label} ({r.count_units})", r.counts))
        maxlen = max(maxlen, len(r.counts))
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([c[0] for c in cols])
        for i in range(maxlen):
            row = [(c[1][i] if i < len(c[1]) else "") for c in cols]
            w.writerow(row)
    return len(usable)


def export_vamas(regions, path, institution="Not specified",
                 instrument="", operator="", experiment_id="",
                 sample_id="Sample", include_transmission=True):
    """Export selected regions as a VAMAS (ISO 14976) file.

    Sequential block layout: experiment mode NORM, scan mode REGULAR,
    technique XPS, kinetic-energy abscissa. When the spectrometer transmission
    function is available it is written as a second corresponding variable
    ("Transmission"), interleaved with intensity, matching CasaXPS exports.
    Only regions with decodable data are written.
    """
    usable = [r for r in regions if r.decodable and r.counts]
    if not usable:
        raise ValueError("None of the selected regions contain decodable data.")

    L = []
    a = L.append

    # ---- experiment header ----
    a("VAMAS Surface Chemical Analysis Standard Data Transfer Format 1988 May 4")
    a(institution)
    a(instrument)
    a(operator)
    a(experiment_id)
    a("0")            # number of lines in comment
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
    for r in usable:
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
        dwell = f"{r.dwell:.6g}" if r.dwell else SENT

        a(r.name)                 # block identifier
        a(r.sample or sample_id)  # sample identifier
        a(str(now.year)); a(str(now.month)); a(str(now.day))
        a(str(now.hour)); a(str(now.minute)); a(str(now.second))
        a("0")                    # hours in advance of GMT
        # block comment: include etch info for depth profiles
        comment = []
        if r.etch_level is not None:
            comment.append(f"Etch level : {r.etch_level}")
        if r.etch_time is not None:
            comment.append(f"Etch time (s) : {r.etch_time:g}")
        a(str(len(comment)))      # lines in block comment
        for c in comment:
            a(c)
        a("XPS")                  # technique
        a(anode)                  # analysis source label
        a(f"{hv:.6g}")            # source characteristic energy
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
        a(f"{ke0:.6g}")           # abscissa start
        a(f"{dke:.6g}")           # abscissa increment
        a(str(n_cv))              # number of corresponding variables
        a("Intensity"); a("d")    # corresponding var 1: label, units
        if trans:
            a("Transmission"); a("d")   # corresponding var 2
        a("pulse counting")       # signal mode
        a(dwell)                  # signal collection time (s)
        a("1")                    # number of scans
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
    with open(path, "w", newline="\r\n") as fh:
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
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, restval="")
        w.writeheader()
        for row in rows:
            w.writerow(row)
    return len(rows)


# Per-region columns for the PDF table. A column whose value is the same for
# every region of the sample is dropped and stated once in the header block.
_REGION_COLS = [
    ("Region", "Region"), ("PE (eV)", "Pass energy (eV)"),
    ("BE start", "BE start (eV)"), ("BE end", "BE end (eV)"),
    ("Step (eV)", "Step (eV)"), ("Dwell (s)", "Dwell (s)"),
    ("Points", "Points"), ("Quality", "Quality"),
    ("hv (eV)", "Photon energy (eV)"),
]


def _sample_block(rows):
    """Tidy one sample's metadata for the report.

    Returns ``(info, columns)``: ``info`` is ``[(field, value)]`` for the
    header block (what is the same for every region, and pass energy grouped
    by region, e.g. "40: Mo 3d, S 2p; 160: Survey") and ``columns`` the
    per-region table columns that still differ."""
    ms = metasummary
    lrows = [(r.get("Region", ""), r) for r in rows]
    info = []
    when = ms.date_range(lrows, sep=" to ")
    if when:
        info.append(("Date acquired", when))
    common, run_var = ms.summarise(
        lrows, [f for f in ms.RUN_FIELDS if f != "Date acquired"])
    info += common
    for field, groups in run_var:
        info.append((field, "; ".join(
            f"{v}: {ms.compact_labels(ls, 10)}" for v, ls in groups)))
    constants, columns = ms.split_columns(
        rows, _REGION_COLS,
        keep=("BE start (eV)", "BE end (eV)", "Points"))
    have = {k for k, _ in info}
    info += [(f, v) for f, v in constants if f not in have]
    lens, _ = ms.summarise(lrows, ["Lens mode", "Aperture"])
    info += [(f, v) for f, v in lens if f not in have]
    _c, pe = ms.summarise(lrows, ["Pass energy (eV)"])
    for field, groups in pe:
        info.append((field, "; ".join(
            f"{v}: {ms.compact_labels(ls, 10)}" for v, ls in groups)))
        columns = [c for c in columns if c[1] != field]
    return info, columns


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


def _metadata_pdf_reportlab(parser, samples, path):
    from xml.sax.saxutils import escape as xml_escape
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak)

    styles = getSampleStyleSheet()
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8,
                           leading=10)
    doc = SimpleDocTemplate(path, pagesize=landscape(A4),
                            leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=14 * mm, bottomMargin=12 * mm,
                            title="ESCApe acquisition metadata")
    story = []
    fname = os.path.basename(parser.path or "experiment")
    story.append(Paragraph("ESCApe Acquisition Metadata", h1))
    story.append(Paragraph(
        f"File: {fname} &nbsp;&nbsp; Samples: {len(samples)} &nbsp;&nbsp; "
        f"Regions: {parser.summary['n_regions']} &nbsp;&nbsp; "
        f"Generated: {datetime.datetime.now():%Y-%m-%d %H:%M}", small))
    if parser.corruption["corrupted"]:
        story.append(Paragraph(
            "<font color='red'>Warning: this file's binary data is corrupted; "
            "numeric values may be unavailable.</font>", small))
    story.append(Spacer(1, 6 * mm))

    hdr_style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b0b0b0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f2f5f8")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ])

    for si, (sample, rows) in enumerate(samples):
        if si > 0:
            story.append(PageBreak())
        story.append(Paragraph(f"Sample: {sample}", h2))
        info, columns = _sample_block(rows)
        if info:
            info_tbl = Table(
                [[k, Paragraph(xml_escape(v), small)] for k, v in info],
                colWidths=[55 * mm, 200 * mm])
            info_tbl.setStyle(TableStyle([
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#2c3e50")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(info_tbl)
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph(f"Regions ({len(rows)})", small))

        table = [[c[0] for c in columns]]
        for row in rows:
            table.append([row.get(c[1], "") for c in columns])
        t = Table(table, repeatRows=1)
        t.setStyle(hdr_style)
        story.append(t)

    doc.build(story)
    return len(samples)


def _metadata_pdf_matplotlib(parser, samples, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    fname = os.path.basename(parser.path or "experiment")
    with PdfPages(path) as pdf:
        for sample, rows in samples:
            fig = plt.figure(figsize=(11.7, 8.3))  # A4 landscape
            fig.suptitle(f"ESCApe metadata — {fname}\nSample: {sample}",
                         fontsize=12, x=0.02, ha="left")
            ax = fig.add_axes([0.02, 0.02, 0.96, 0.84])
            ax.axis("off")
            info, columns = _sample_block(rows)
            lines = [f"{k}: {v}" for k, v in info]
            ax.text(0, 1.0, "\n".join(lines), va="top", fontsize=8,
                    family="monospace")
            col_labels = [c[0] for c in columns]
            cells = [[row.get(c[1], "") for c in columns] for row in rows]
            tbl = ax.table(cellText=cells, colLabels=col_labels,
                           loc="lower center", cellLoc="center")
            tbl.auto_set_font_size(False)
            tbl.set_fontsize(7)
            tbl.scale(1, 1.2)
            pdf.savefig(fig)
            plt.close(fig)
    return len(samples)

