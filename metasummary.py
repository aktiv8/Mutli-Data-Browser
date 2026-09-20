"""Tidy acquisition metadata: state what is the same for every spectrum once,
and for settings that differ say *which regions* share each value (e.g.
"Pass energy: 40 eV - Mo 3d, S 2p, C 1s / 160 eV - Survey").

Pure functions over the metadata dicts from ``SpectrumFile.region_metadata``;
no Tk, so the Details panel and the PDF report share them.
"""

from __future__ import annotations

# What identifies the data, what is about the run, and the per-scan analyser
# settings (the ones that legitimately differ between survey and narrow scans).
IDENT_FIELDS = ["Sample", "Source file", "File format"]
RUN_FIELDS = ["Date acquired", "Run started", "Run finished", "Instrument",
              "Acquisition software", "Operator", "Acquisition computer",
              "X-ray source", "Anode", "Photon energy (eV)",
              "Source power (W)", "Anode voltage (kV)",
              "Emission current (mA)", "X-ray spot (µm)", "Charge neutraliser",
              "Ion gun / sputtering"]
SETTING_FIELDS = ["Pass energy (eV)", "Lens mode", "Aperture",
                  "Analyser mode", "Acquisition mode", "Step (eV)",
                  "Dwell (s)", "Scans", "Counting time", "Quality"]

NOT_RECORDED = "not recorded"


def _sort_key(value):
    """Numbers ascending (so 40 comes before 160), then text."""
    try:
        return (0, float(value), "")
    except (TypeError, ValueError):
        return (1, 0.0, str(value))


def summarise(rows, fields):
    """Split ``fields`` into what is common to every row and what varies.

    ``rows`` is a list of ``(label, metadata dict)``. Returns
    ``(common, varying)``:

    * ``common``: ``[(field, value)]`` for fields with one non-empty value in
      every row (fields empty everywhere are dropped);
    * ``varying``: ``[(field, [(value, [labels])])]``, values ordered
      numerically when they are numbers, labels in row order. A value of
      ``NOT_RECORDED`` collects the rows where the field is empty.
    """
    common, varying = [], []
    for f in fields:
        values = [str(md.get(f, "") or "") for _l, md in rows]
        if not any(values):
            continue
        if len(set(values)) == 1:
            common.append((f, values[0]))
            continue
        groups = {}
        for (label, _md), v in zip(rows, values):
            groups.setdefault(v or NOT_RECORDED, []).append(label)
        order = sorted(groups, key=lambda v: (v == NOT_RECORDED, _sort_key(v)))
        varying.append((f, [(v, groups[v]) for v in order]))
    return common, varying


def compact_labels(labels, limit=6):
    """'C 1s x12, O 1s x12' style: repeats are counted, and a long list is cut
    after ``limit`` distinct names ('+N more')."""
    counts = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    items = [f"{k} ×{n}" if n > 1 else k for k, n in counts.items()]
    if len(items) > limit:
        return ", ".join(items[:limit]) + f", +{len(items) - limit} more"
    return ", ".join(items)


def date_range(rows, sep=" → "):
    """'first → last' over the rows' 'Date acquired' (a single value when
    they agree, '' when none is recorded)."""
    dates = sorted({str(md.get("Date acquired", "") or "") for _l, md in rows}
                   - {""})
    if not dates:
        return ""
    return dates[0] if len(dates) == 1 else f"{dates[0]}{sep}{dates[-1]}"


def split_columns(rows, columns, keep=()):
    """For a per-region table: which columns to drop because every row holds
    the same value. ``columns`` is ``[(heading, field)]``. Returns
    ``(constants, kept)``: ``constants`` is ``[(field, value)]`` for the
    dropped columns that have a value, ``kept`` the columns to print. The
    first column (the region name) and any field in ``keep`` (scan ranges,
    which describe the region rather than the setup) are always kept."""
    constants, kept = [], [columns[0]]
    for heading, field in columns[1:]:
        values = {str(md.get(field, "") or "") for md in rows}
        if len(values) == 1 and len(rows) > 1 and field not in keep:
            (only,) = values
            if only:
                constants.append((field, only))
        else:
            kept.append((heading, field))
    return constants, kept


# =====================================================================
#  Report layout: what goes in the file block, on a sample's line, and in
#  the scan table -- without dropping any field (used by the PDF report
#  and the PowerPoint export)
# =====================================================================
import re
from dataclasses import dataclass, field

# Setup fields, in display order. Each is stated once for the whole file when
# it is the same everywhere, else on the sample's line when it is constant
# within that sample, else it becomes a column of that sample's scan table.
SETUP_FIELDS = [
    "Technique", "Instrument", "Acquisition software", "Operator",
    "Acquisition computer", "Institution", "Project", "Experiment",
    "Platter", "Source configuration", "X-ray source", "Anode",
    "Photon energy (eV)", "Source power (W)", "Anode voltage (kV)",
    "Emission current (mA)", "X-ray spot (µm)", "Charge neutraliser",
    "Ion gun / sputtering", "Lens mode", "Aperture", "Analyser mode",
    "Acquisition mode", "Pass energy (eV)", "Step (eV)", "Dwell (s)",
    "Scans", "Counting time", "Quality", "Work function (eV)",
    "Sample tilt (°)", "Take-off angle (°)", "Position X (mm)",
    "Position Y (mm)", "BE shift (eV)", "Comments", "Notes",
]
# Only Latin-1 characters: the PDF uses the built-in Helvetica.
SHORT = {
    "Acquisition computer": "Computer", "Photon energy (eV)": "hv (eV)",
    "Source power (W)": "Power (W)", "Charge neutraliser": "Neutraliser",
    "Ion gun / sputtering": "Ion gun", "Lens mode": "Lens",
    "Pass energy (eV)": "PE (eV)", "Position X (mm)": "X (mm)",
    "Position Y (mm)": "Y (mm)", "BE shift (eV)": "BE shift",
    "Acquisition software": "Software", "Anode voltage (kV)": "Anode (kV)",
    "Emission current (mA)": "Emission (mA)", "X-ray spot (µm)": "Spot (µm)",
    "Analyser mode": "Analyser", "Acquisition mode": "Mode",
    "Counting time": "Counting", "Work function (eV)": "WF (eV)",
    "Source configuration": "Configuration",
}
# Scan ranges describe the region rather than the setup: always columns.
RANGE_COLS = [("BE start", "BE start (eV)"), ("BE end", "BE end (eV)"),
              ("Points", "Points")]

_DAY_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)")
DASH = "–"


@dataclass
class SampleLayout:
    name: str
    line: list = field(default_factory=list)       # [(field, value)]
    columns: list = field(default_factory=list)    # [heading]
    rows: list = field(default_factory=list)       # [{heading: text}]
    strips: list = field(default_factory=list)     # [(title, [(lvl, etch, date)])]
    n_regions: int = 0


@dataclass
class FileLayout:
    common: list = field(default_factory=list)     # [(field, value)]
    samples: list = field(default_factory=list)    # [SampleLayout]
    n_regions: int = 0


def _val(md, key):
    return str(md.get(key, "") or "")


def split_day(text):
    """('YYYY-MM-DD', 'HH:MM[:SS]') for an ISO-like date, else (None, text)."""
    m = _DAY_RE.match(text or "")
    return (m.group(1), m.group(2)) if m else (None, text or "")


def level_runs(levels):
    """'0-60 (61)' / '0-4, 7, 9-12 (10)': every level, written as runs."""
    levels = sorted(levels)
    runs, start, prev = [], levels[0], levels[0]
    for v in levels[1:]:
        if v == prev + 1:
            prev = v
            continue
        runs.append((start, prev))
        start = prev = v
    runs.append((start, prev))
    text = ", ".join(str(a) if a == b else f"{a}{DASH}{b}" for a, b in runs)
    return text if len(levels) == 1 else f"{text} ({len(levels)})"


def etch_summary(levels, times):
    """Etch times as '0-1800 s, 30 s steps' when that reproduces every
    level's time exactly; None when it does not (list them instead)."""
    if len(levels) == 1:
        return f"{times[0]:g} s"
    dl = levels[-1] - levels[0]
    if dl == 0:
        return None
    step = (times[-1] - times[0]) / dl
    for lvl, t in zip(levels, times):
        want = times[0] + step * (lvl - levels[0])
        if abs(t - want) > 1e-9 * max(1.0, abs(want)):
            return None
    return f"{times[0]:g}{DASH}{times[-1]:g} s, {step:g} s steps"


def _to_float(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _date_cell(dates, day):
    """One cell for a set of acquisition dates: the value, or first-last.
    Times only when the day is stated elsewhere."""
    dates = [d for d in dates if d]
    if not dates:
        return ""

    def show(d):
        dd, tt = split_day(d)
        return tt if (day and dd == day) else d
    uniq = list(dict.fromkeys(dates))
    if len(uniq) == 1:
        return show(uniq[0])
    return f"{show(min(uniq))} {DASH} {show(max(uniq))}"


def layout_file(samples):
    """Arrange ``SpectrumFile.samples_metadata()`` for a report.

    Every field in ``SETUP_FIELDS``, the acquisition date, the depth-profile
    levels and the scan ranges is placed somewhere. What is left out on
    purpose: the identifiers already used as headings (Sample, Region, Source
    file, File format) and per-run detail that only makes sense over a whole
    experiment ("Run started" / "Run finished", reported by ``timing``).

    * ``common``: setup fields identical in every region of the file;
    * per sample ``line``: fields constant within that sample only (stage
      position, ...);
    * per sample ``rows`` / ``columns``: one row per region, with the
      depth-profile levels of one region collapsed into a single row (levels
      written as runs; etch times as start-end with the step *only if that
      reproduces every time exactly*);
    * ``strips``: per-level (level, etch time, acquired) entries for any
      collapsed group whose etch times or dates cannot be reconstructed from
      its row, so the report loses no value.
    """
    all_rows = [md for _s, rows in samples for md in rows]
    out = FileLayout(n_regions=len(all_rows))
    if not all_rows:
        return out

    file_const = set()
    for f in SETUP_FIELDS:
        vals = {_val(md, f) for md in all_rows}
        if len(vals) == 1 and "" not in vals:
            out.common.append((f, next(iter(vals))))
            file_const.add(f)

    all_dates = {_val(md, "Date acquired") for md in all_rows}
    file_day = None
    if len(all_dates) == 1 and "" not in all_dates:
        out.common.append(("Date acquired", next(iter(all_dates))))
        dates_stated = True                 # one value for the whole file
    else:
        dates_stated = False
        days = {split_day(d)[0] for d in all_dates if d}
        if len(days) == 1 and None not in days and "" not in all_dates:
            file_day = next(iter(days))
            out.common.append(("Date acquired", file_day))

    for name, rows in samples:
        sl = SampleLayout(name=name or "(unnamed)", n_regions=len(rows))
        extra = []
        for f in SETUP_FIELDS:
            if f in file_const:
                continue
            vals = {_val(md, f) for md in rows}
            if vals == {""}:
                continue
            if len(vals) == 1:
                sl.line.append((f, next(iter(vals))))
            else:
                extra.append(f)

        dates = [_val(md, "Date acquired") for md in rows]
        date_col = (not dates_stated) and len(set(dates)) > 1
        day = file_day
        if not dates_stated and not date_col and dates and dates[0]:
            sl.line.append(("Date acquired", dates[0]))
        elif date_col and not file_day:
            here = {split_day(d)[0] for d in dates}
            if len(here) == 1 and None not in here and "" not in dates:
                day = next(iter(here))
                sl.line.append(("Date acquired", day))

        depth = any(_val(md, "Etch level") for md in rows)
        cols = ["Region"]
        if depth:
            cols += ["Levels", "Etch"]
        cols += [SHORT.get(f, f) for f in extra]
        cols += [h for h, _k in RANGE_COLS]
        if date_col:
            cols.append("Acquired")
        sl.columns = cols

        groups, seen = [], {}          # all levels of one region, one row
        for md in rows:
            key = (_val(md, "Region"), _val(md, "BE start (eV)"),
                   _val(md, "BE end (eV)"), _val(md, "Points"),
                   tuple(_val(md, f) for f in extra),
                   bool(_val(md, "Etch level")))
            if key[-1] and key in seen:      # depth levels may interleave
                groups[seen[key]][1].append(md)
            else:
                if key[-1]:
                    seen[key] = len(groups)
                groups.append((key, [md]))

        for key, members in groups:
            md0 = members[0]
            row = {"Region": _val(md0, "Region")}
            for f in extra:
                row[SHORT.get(f, f)] = _val(md0, f)
            for h, k in RANGE_COLS:
                row[h] = _val(md0, k)
            gdates = [_val(m, "Date acquired") for m in members]
            if date_col:
                row["Acquired"] = _date_cell(gdates, day)
            if depth:
                row["Levels"] = row["Etch"] = ""
                lv = [_to_float(_val(m, "Etch level")) for m in members]
                if key[-1] and None not in lv:
                    lv = [int(x) for x in lv]
                    tm = [_to_float(_val(m, "Etch time (s)"))
                          for m in members]
                    order = sorted(range(len(lv)), key=lv.__getitem__)
                    lv_s = [lv[i] for i in order]
                    tm_s = [tm[i] for i in order]
                    row["Levels"] = level_runs(lv)
                    need_strip = False
                    if None not in tm_s:
                        summary = etch_summary(lv_s, tm_s)
                        if summary is None:
                            row["Etch"] = "per level, see below"
                            need_strip = True
                        else:
                            row["Etch"] = summary
                    if len(members) > 1 and len(set(gdates)) > 1:
                        need_strip = True
                    if need_strip:
                        sl.strips.append((
                            f"{row['Region']} {DASH} per-level details",
                            [(str(lv[i]), "" if tm[i] is None
                              else f"{tm[i]:g}",
                              _date_cell([gdates[i]], day))
                             for i in order]))
            sl.rows.append(row)
        if depth and not any(r.get("Etch") for r in sl.rows):
            sl.columns.remove("Etch")        # no etch times recorded
        out.samples.append(sl)
    return out


def column_weights(columns):
    """Relative widths for the columns of a scan table (PDF and slides)."""
    w = {"Region": 1.5, "Levels": 1.9, "Etch": 3.0, "Acquired": 3.2,
         "BE start": 1.0, "BE end": 1.0, "Points": 0.9, "Quality": 1.3,
         "Lens": 1.4, "Aperture": 1.4}
    return [w.get(c, 1.15) for c in columns]
