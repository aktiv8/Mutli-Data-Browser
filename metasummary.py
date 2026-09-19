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
RUN_FIELDS = ["Date acquired", "Instrument", "Operator",
              "Acquisition computer", "X-ray source", "Anode",
              "Photon energy (eV)", "Source power (W)", "Charge neutraliser",
              "Ion gun / sputtering"]
SETTING_FIELDS = ["Pass energy (eV)", "Lens mode", "Aperture", "Step (eV)",
                  "Dwell (s)", "Quality"]

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
