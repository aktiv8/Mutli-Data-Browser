"""Acquisition metadata carried inside VAMAS comments, so an exported file can
be read back without losing what VAMAS has no field for (lens mode, aperture,
neutraliser, sputter settings, dates, positions, notes, ...).

The metadata are written as a delimited block of ``key: value`` lines in a
comment, which other software simply shows as text::

    === eXPoSe SpectraDeck metadata ===
    Lens mode: Hybrid
    Pass energy (eV): 20
    === end of eXPoSe SpectraDeck metadata ===

A block in the file header holds the experiment-wide entries (instrument,
neutraliser ...), one in each block comment the entries of that spectrum. The
reader restores them; values VAMAS itself stores exactly (photon energy, pass
energy, dwell, step) are never overridden from the text.

Pure functions, no Tk.
"""

from __future__ import annotations

import re

import appinfo

START = f"=== {appinfo.NAME} metadata ==="
END = f"=== end of {appinfo.NAME} metadata ==="
_OLD_NAME = "ESCApe Explorer"                # the former name, still read
_START_RE = re.compile(r"^===\s*(?:%s|%s)\s+metadata\s*===$"
                       % (re.escape(appinfo.NAME), re.escape(_OLD_NAME)), re.I)
_END_RE = re.compile(r"^===\s*end of\s+.*metadata\s*===$", re.I)
# a doubled backslash before "u" is a literal backslash; \uXXXX is a character
_TOKEN = re.compile(r"\\\\(?=u)|\\u([0-9a-fA-F]{4})")

# metadata that belong to the whole experiment rather than to one spectrum
EXPERIMENT_KEYS = ("Instrument", "Operator", "Acquisition computer",
                   "X-ray source", "Lens mode", "Aperture",
                   "Charge neutraliser", "Ion gun / sputtering")
# stored by VAMAS itself, exactly: the text never overrides these
VAMAS_OWN = ("Photon energy (eV)", "Pass energy (eV)", "Dwell (s)",
             "Step (eV)", "Points", "BE start (eV)", "BE end (eV)")


def _esc(text: str) -> str:
    r"""Latin-1 safe: anything beyond it becomes ``\uXXXX``; a literal
    backslash before a "u" is doubled so it cannot be mistaken for one."""
    text = re.sub(r"\\(?=u)", r"\\\\", text)
    return "".join(c if ord(c) < 256 else f"\\u{ord(c):04x}" for c in text)


def _unesc(text: str) -> str:
    return _TOKEN.sub(
        lambda m: "\\" if m.group(1) is None else chr(int(m.group(1), 16)),
        text)


def _clean_value(v) -> str:
    return re.sub(r"\s*[\r\n]+\s*", " / ", str(v)).strip()


def encode(md, keys=None) -> list:
    """The comment lines for a metadata dict (empty values are left out).
    ``keys`` restricts and orders it. Returns [] when there is nothing to
    write."""
    items = []
    for k in (keys if keys is not None else list(md)):
        v = md.get(k)
        if v is None or str(v).strip() == "":
            continue
        key = _clean_value(k).replace(": ", " - ").replace(":", "")
        if key:
            items.append(f"{_esc(key)}: {_esc(_clean_value(v))}")
    if not items:
        return []
    return [START] + items + [END]


def decode(lines) -> dict:
    """The metadata dict held in a comment, or {} when it has no block."""
    out, inside = {}, False
    for raw in lines or ():
        line = raw.strip()
        if not inside:
            if _START_RE.match(line):
                inside = True
            continue
        if _END_RE.match(line) or _START_RE.match(line):
            inside = False
            continue
        key, sep, val = line.partition(": ")
        if not sep:
            key, sep, val = line.partition(":")
        key = _unesc(key.strip())
        if key and sep:
            out.setdefault(key, _unesc(val.strip()))
    return out


def split(md) -> tuple:
    """``(experiment, per_spectrum)`` halves of a metadata dict."""
    exp = {k: v for k, v in md.items() if k in EXPERIMENT_KEYS}
    rest = {k: v for k, v in md.items() if k not in EXPERIMENT_KEYS}
    return exp, rest


def common_experiment(rows) -> dict:
    """The experiment-wide entries that every row agrees on (first value
    otherwise, so nothing is lost)."""
    out = {}
    for md in rows:
        for k in EXPERIMENT_KEYS:
            v = str(md.get(k, "") or "").strip()
            if v and k not in out:
                out[k] = v
    return out


def _float(text):
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return None


def apply_to_region(r, md) -> None:
    """Restore what ``md`` says about a spectrum onto a ``Region``. Fields
    VAMAS holds exactly are left alone; the whole dict is kept in
    ``r.extra['preserved_metadata']`` so entries without a home (notes,
    energy shift, sputter values ...) still show in the metadata."""
    if not md:
        return
    if md.get("Region"):                # the name as it was, not as VAMAS
        r.name = md["Region"]           # (or the reader) canonicalises it
    if md.get("Anode"):                 # VAMAS keeps only the element
        r.anode = md["Anode"]
    pw = _float(md.get("Source power (W)"))
    if pw is not None:
        r.conditions["X-ray Power"] = f"{md['Source power (W)'].strip()} W"
    if md.get("Technique"):
        r.technique = md["Technique"]
    if md.get("Date acquired"):
        r.date = md["Date acquired"]
    x, y = _float(md.get("Position X (mm)")), _float(md.get("Position Y (mm)"))
    if x is not None and y is not None:
        r.pos_x, r.pos_y = x, y
    lvl = _float(md.get("Etch level"))
    if lvl is not None:
        r.etch_level = int(round(lvl))
    t = _float(md.get("Etch time (s)"))
    if t is not None:
        r.etch_time = t
    if md.get("Lens mode") and not r.lens_mode:
        r.lens_mode = md["Lens mode"]
    if md.get("Aperture") and not r.aperture:
        r.aperture = md["Aperture"]
    if md.get("Quality"):
        r.conditions["Quality"] = md["Quality"]
    r.extra["preserved_metadata"] = {
        k: v for k, v in md.items() if k not in VAMAS_OWN}
