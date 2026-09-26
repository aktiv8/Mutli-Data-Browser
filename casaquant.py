"""CasaXPS exported quantification sidecar files (Tk-free).

An experiment directory may also hold plain-text files CasaXPS itself
exported when a user quantified the data there by hand: ``Quant_survey.txt``
(whole-sample %Conc per element, from CasaXPS's own "Peak Area Results"
block), ``Quant_regions.txt`` (per fitted-component %At Conc) and, for
carbon materials, ``Quant_Dparam.txt`` (Auger D-parameter: peak name and
FWHM). These are CasaXPS's own numbers, a different provenance from this
app's own fit-derived quantification (``quant.py``): nothing here is
guessed or recomputed, what CasaXPS wrote is what is shown.

The three tables do not reliably nest -- a real ``Quant_regions.txt`` can
list components with no matching element in the same directory's
``Quant_survey.txt`` (the two can come from different quantification
setups), and repeats one ``Name`` several times within a sample with no
disambiguating text at all -- so each is kept as its own flat list of rows,
in file order, exactly as exported.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from readers.base import read_bytes

_KIND_KEYWORDS = {"survey": "survey", "regions": "region", "dparam": "dparam"}
_ROW_LABELS = {"%conc", "st.dev.", "area", "cps"}
_SAMPLE_PREFIX = re.compile(r"^\s*sample\s+name\s*:\s*", re.IGNORECASE)


def _to_float(s):
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return None


def strip_sample_prefix(text):
    """Remove a leading "Sample Name: " if present (not every export has
    one -- and a VAMAS file's own sample identifier can carry it too, when
    CasaXPS wrote it, so this is also used to match a fitted region's
    ``Region.sample`` against a CasaXPS export's sample names), else return
    the text unchanged."""
    return _SAMPLE_PREFIX.sub("", text or "").strip()


def _text(path):
    return read_bytes(path).decode("latin-1")


def _lines(text):
    return text.replace("\r", "").split("\n")


def find(folder):
    """``({"survey"|"regions"|"dparam": path}, notes)`` for the sidecar
    files present in ``folder`` (top-level only, matched fuzzily and
    case-insensitively on the filename); the alphabetically first match
    wins for a kind with more than one candidate, noted in ``notes``."""
    found, notes = {}, []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return found, notes
    for kind, keyword in _KIND_KEYWORDS.items():
        candidates = [n for n in names
                      if n.lower().endswith(".txt") and keyword in n.lower()
                      and os.path.isfile(os.path.join(folder, n))]
        if not candidates:
            continue
        found[kind] = os.path.join(folder, candidates[0])
        if len(candidates) > 1:
            notes.append(f'More than one file matched "{keyword}" in '
                        f"{folder}; using {candidates[0]}.")
    return found, notes


def _read_table(text):
    """Rows of the first table after a header row whose first cell is
    "Sample Identifier": one dict per row, keyed by header text (column
    lookup must always be by name -- two real files have columns, such as
    FWHM and Raw Area, that hold coincidentally identical values), plus the
    sample identifier carried forward from the last non-blank first cell."""
    lines = _lines(text)
    header = None
    start = 0
    for i, line in enumerate(lines):
        cells = line.split("\t")
        if cells and cells[0].strip() == "Sample Identifier":
            header = [c.strip() for c in cells]
            start = i + 1
            break
    if header is None:
        return []
    rows = []
    current_sample = None
    for line in lines[start:]:
        if not line.strip():
            break
        cells = line.split("\t")
        cells += [""] * (len(header) - len(cells))
        sample_cell = cells[0].strip()
        if sample_cell:
            current_sample = strip_sample_prefix(sample_cell)
        row = {header[j]: cells[j].strip() for j in range(len(header))}
        row["Sample Identifier"] = current_sample
        rows.append(row)
    return rows


def parse_regions(text):
    """``[{"sample", "name", "position", "at_pct"}]``, one row per fitted
    component, in file order (duplicate names kept, nothing merged or
    de-duplicated -- a real file repeats "Pt 4d" and "O 1s" with no
    disambiguating text at all, told apart only by position)."""
    out = []
    for row in _read_table(text):
        out.append({"sample": row.get("Sample Identifier"),
                    "name": row.get("Name", ""),
                    "position": _to_float(row.get("Position")),
                    "at_pct": _to_float(row.get("%At Conc"))})
    return out


def parse_dparam(text):
    """``[{"sample", "name", "fwhm"}]``, one row per Auger line (e.g.
    "C KVV")."""
    out = []
    for row in _read_table(text):
        out.append({"sample": row.get("Sample Identifier"),
                    "name": row.get("Name", ""),
                    "fwhm": _to_float(row.get("FWHM"))})
    return out


def parse_survey(text):
    """``[{"sample", "element", "pct"}]`` from the "Peak Area Results"
    block (the exact heading -- not its "Compact form" or "RSF Corrected"
    variants, which repeat the same numbers differently laid out): one row
    per sample per element. A sample's own row is any non-blank first cell
    that is not a known row label ("%Conc"/"St.Dev."/"Area"/"CPS"): the
    identifier is not consistently prefixed "Sample Name: " across real
    files, so that text cannot be used to spot a new sample block."""
    lines = _lines(text)
    out = []
    i = 0
    in_section = False
    started = False           # a sample block has been read (vs. a blank
                              # line just before the table starts)
    while i < len(lines):
        line = lines[i]
        if not in_section:
            if line.strip() == "Peak Area Results":
                in_section = True
            i += 1
            continue
        if not line.strip():
            if started:
                break
            i += 1
            continue
        cells = line.split("\t")
        label = cells[0].strip()
        if label and label.lower() not in _ROW_LABELS:
            started = True
            sample = strip_sample_prefix(label)
            elements = [c.strip() for c in cells[1:] if c.strip()]
            i += 1
            if i < len(lines) and lines[i].split("\t")[0].strip() == "%Conc":
                values = lines[i].split("\t")[1:]
                for element, v in zip(elements, values):
                    out.append({"sample": sample, "element": element,
                                "pct": _to_float(v)})
            i += 1
        else:
            i += 1
    return out


@dataclass
class SampleQuant:
    """One sample's CasaXPS-exported numbers: three independent flat lists
    (see the module docstring for why they are not nested)."""
    survey: list = field(default_factory=list)      # [{"element","pct"}]
    regions: list = field(default_factory=list)      # [{"name","position","at_pct"}]
    dparam: list = field(default_factory=list)       # [{"name","fwhm"}]


@dataclass
class CasaQuant:
    folder: str
    samples: dict = field(default_factory=dict)      # name -> SampleQuant
    notes: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)          # "survey"|"regions"|"dparam" -> text


def _sample(quant, name):
    return quant.samples.setdefault(name, SampleQuant())


def load(folder):
    """Read the CasaXPS export files of ``folder`` into a ``CasaQuant``, or
    None if none of the three are there."""
    found, notes = find(folder)
    if not found:
        return None
    quant = CasaQuant(folder=folder, notes=list(notes))
    if "survey" in found:
        text = quant.raw["survey"] = _text(found["survey"])
        for row in parse_survey(text):
            _sample(quant, row["sample"]).survey.append(
                {"element": row["element"], "pct": row["pct"]})
    if "regions" in found:
        text = quant.raw["regions"] = _text(found["regions"])
        for row in parse_regions(text):
            _sample(quant, row["sample"]).regions.append(
                {"name": row["name"], "position": row["position"],
                 "at_pct": row["at_pct"]})
    if "dparam" in found:
        text = quant.raw["dparam"] = _text(found["dparam"])
        for row in parse_dparam(text):
            _sample(quant, row["sample"]).dparam.append(
                {"name": row["name"], "fwhm": row["fwhm"]})
    return quant


# -- JSON round trip (workbook persistence) -----------------------------------
def to_json(q):
    """``q`` (a ``CasaQuant`` or None) as plain JSON-ready data."""
    if q is None:
        return {}
    return {"folder": q.folder, "notes": list(q.notes), "raw": dict(q.raw),
            "samples": {name: {"survey": list(s.survey),
                               "regions": list(s.regions),
                               "dparam": list(s.dparam)}
                       for name, s in q.samples.items()}}


def from_json(data):
    """The ``CasaQuant`` ``to_json`` made, or None for empty/missing data."""
    if not data:
        return None
    q = CasaQuant(folder=data.get("folder", ""),
                 notes=list(data.get("notes") or []),
                 raw=dict(data.get("raw") or {}))
    for name, s in (data.get("samples") or {}).items():
        q.samples[name] = SampleQuant(
            survey=list(s.get("survey") or []),
            regions=list(s.get("regions") or []),
            dparam=list(s.get("dparam") or []))
    return q
