"""The facts for two report sections, without Tk: "At a glance" (a handful of
single-line facts a reader can take in at once) and "Timing" (when the data
were acquired and how long the instrument was counting).

Nothing is computed here that the report does not already know: the counts
come from the file list and the metadata rows, the dates from
``metasummary.date_range``, the times from ``timing`` and the elements from
the quantification (``resultspages``). A line is only written when its value
is recorded, so a file that records no operator gives no "Operator" line and
a Kratos file (whose runs record a start but no end) gives a shorter Timing
section that says why. The PDF, the slides and the Word document all lay out
these same rows.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import metasummary
import methods
import resultspages
import timing

DASH = "–"                           # en dash, for ranges
DOT = " · "                          # middle dot, between items of a line


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def quantified_elements(results):
    """The elements the quantification counts, in the order they first
    appear, and the number of samples they come from:
    ``([element, ...], n_samples)``. An element is counted when a fitted
    region of it has an atomic percent; CasaXPS's own exported tables name
    their elements directly."""
    seen, samples = [], 0
    for s in getattr(results, "samples", ()) or ():
        found = []
        for lv in s.levels:
            for e, x in zip(lv.entries, lv.res):
                if x.get("at_pct") is not None:
                    found.append(e["row"]["region"])
        cq = getattr(s, "casaxps", None)
        if cq is not None:
            found += [str(row.get("element", ""))
                      for row in getattr(cq, "survey", ()) or ()]
        elements = [resultspages.element_of(f) for f in found]
        elements = [el for el in elements if el]
        samples += bool(elements)
        seen += [el for el in dict.fromkeys(elements) if el not in seen]
    return seen, samples


def counting_text(summary):
    """"3 h 12 min" (+ " (instrument in use 8 h 38 min)" when both are
    known for every region), or "" when the counting time is not known."""
    if summary is None or summary.net is None or summary.n_without_net:
        return ""
    text = timing.fmt_duration(summary.net)
    if summary.active is not None and not summary.n_without_run:
        text += f"  (instrument in use {timing.fmt_duration(summary.active)})"
    return text


def facts(rows, file_rows=(), results=None, timing_summary=None, figures=0,
          pictures=0):
    """``[(label, value)]`` for the "At a glance" block. ``rows`` are the
    loaded files' metadata rows (``SpectrumFile.metadata_rows``),
    ``file_rows`` the file list of the report, ``results`` the
    ``resultspages.Results`` and ``timing_summary`` a ``timing.Summary``;
    ``figures`` and ``pictures`` count what else is in the report. Only what
    is recorded is listed."""
    rows = [r for r in rows or () if isinstance(r, dict)]
    out = []
    samples = methods._unique(rows, "Sample")
    parts = []
    if file_rows:
        parts.append(_plural(len(file_rows), "file"))
    if samples:
        parts.append(_plural(len(samples), "sample"))
    if rows:
        parts.append(f"{len(rows)} spectrum" if len(rows) == 1
                     else f"{len(rows)} spectra")
    if parts:
        out.append(("Data", DOT.join(parts)))
    formats = list(dict.fromkeys(str(r.get("format", "") or "").strip()
                                 for r in file_rows or ()))
    formats = [f for f in formats if f]
    if formats:
        out.append(("Format", DOT.join(formats)))
    names = methods._instrument_names(rows)
    if names:
        out.append(("Instrument", ", ".join(names)))
    operators = methods._unique(rows, "Operator")
    if operators:
        out.append(("Operator", ", ".join(operators)))
    dates = metasummary.date_range([("", r) for r in rows],
                                   sep=f" {DASH} ")
    if dates:
        out.append(("Acquired", dates))
    counted = counting_text(timing_summary)
    if counted:
        out.append(("Counting time", counted))
    elements, n_samples = quantified_elements(results)
    if elements:
        out.append(("Quantified", ", ".join(elements)
                    + f"  ({_plural(n_samples, 'sample')})"))
    extra = []
    if figures:
        extra.append(_plural(figures, "saved figure"))
    if pictures:
        extra.append("1 camera picture or map" if pictures == 1
                     else f"{pictures} camera pictures and maps")
    if extra:
        out.append(("Also included", DOT.join(extra)))
    return out


@dataclass
class Timing:
    """The "Timing" section: the summary rows, the counting time of each
    sample, and what is missing."""
    rows: list = field(default_factory=list)       # [(label, value)]
    by_sample: list = field(default_factory=list)  # [(sample, file, text)]
    notes: list = field(default_factory=list)

    def __bool__(self):
        return bool(self.rows)


def timing_section(docs, summary=None):
    """The ``Timing`` of the loaded files (``summary``: a ``timing.Summary``
    of them, worked out here when not given). It is empty (false) when the
    files record no times at all. The per-sample table appears only when it
    says something the summary does not: two or more samples, at least one
    with a known counting time."""
    docs = list(docs or ())
    summary = summary if summary is not None else timing.summarise(docs)
    out = Timing(rows=timing.describe(summary), notes=list(summary.notes))
    table = []
    for doc in docs:
        name = os.path.basename((getattr(doc, "path", "") or "").rstrip("\\/"))
        ann = getattr(doc, "annotations", None)
        fid = getattr(doc, "file_id", "")
        for sample, seconds in timing.sample_net(doc).items():
            label = ann.sample_label(fid, sample) if ann else sample
            table.append((label or sample or "-", name or "-",
                          timing.fmt_duration(seconds)
                          if seconds is not None else "not recorded"))
    if len(table) >= 2 and any(t[2] != "not recorded" for t in table):
        out.by_sample = table
    return out
