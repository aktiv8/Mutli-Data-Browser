"""Element identification from a survey: an approximate table of XPS lines
(``assets/xps_lines.json``, editable), candidate lookup near a binding energy
and automatic peak labelling. Pure functions; no Tk."""

from __future__ import annotations

import json
import os

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "assets", "xps_lines.json")
DEFAULT_HV = 1486.6                      # Al K-alpha
# Elements met on almost every sample: they win close calls (~1 eV) against
# rarer elements when labelling.
COMMON = {"C", "O", "N", "Si", "Na", "Cl", "S", "Ca", "Al", "F", "K", "P",
          "Fe", "Zn", "Cu", "Ti", "Mg", "B"}
COMMON_BONUS = 1.0


def load_lines(path=None):
    """The line table as a list of dicts (``el``, ``line``, ``be`` or
    ``ke``, ``rank``); [] if the file is missing or unreadable."""
    try:
        with open(path or DEFAULT_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        out = []
        for e in data.get("lines", []):
            if not isinstance(e, dict):
                continue
            if e.get("el") and e.get("line") and (
                    isinstance(e.get("be"), (int, float))
                    or isinstance(e.get("ke"), (int, float))):
                out.append(e)
        return out
    except (OSError, ValueError, AttributeError):
        return []


def line_be(entry, hv=None):
    """Binding energy of a table entry (Auger lines follow the photon
    energy: BE = hv - KE)."""
    if isinstance(entry.get("be"), (int, float)):
        return float(entry["be"])
    return float(hv or DEFAULT_HV) - float(entry["ke"])


def label_of(entry):
    return f"{entry['el']} {entry['line']}"


def candidates(be, window, lines, hv=None):
    """Lines within ``window`` eV of ``be``: ``[(delta, entry)]`` with the
    most plausible first: nearest, with secondary lines (rank > 1) needing to
    be about 0.8 eV closer per rank step to win, and common elements
    (``COMMON``, main lines only) given a 1 eV head start."""
    out = []
    for e in lines:
        d = line_be(e, hv) - be
        if abs(d) <= window:
            out.append((d, e))
    out.sort(key=lambda t: abs(t[0]) + 0.8 * (t[1].get("rank", 1) - 1)
             - (COMMON_BONUS if t[1]["el"] in COMMON
                and t[1].get("rank", 1) == 1 else 0.0))
    return out


def find_peaks(energy, counts, prominence=0.04, min_sep=3.0, smooth=5,
               limit=30):
    """Peak positions of a spectrum, strongest first: ``[(be, height)]``.

    A peak is a local maximum of the lightly smoothed data standing above the
    lowest point within +/- ``min_sep`` * 4 eV by at least ``prominence`` of
    the full range; no two peaks closer than ``min_sep`` eV are kept."""
    pts = sorted(zip(energy, counts))
    if len(pts) < 5:
        return []
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    n = len(ys)
    half = max(0, smooth // 2)
    sm = []
    for i in range(n):
        a, b = max(0, i - half), min(n, i + half + 1)
        sm.append(sum(ys[a:b]) / (b - a))
    span = max(sm) - min(sm)
    if span <= 0:
        return []
    reach = min_sep * 4
    found = []
    for i in range(1, n - 1):
        if sm[i] < sm[i - 1] or sm[i] <= sm[i + 1]:
            continue
        lo = min(sm[j] for j in range(n) if abs(xs[j] - xs[i]) <= reach)
        if sm[i] - lo >= prominence * span:
            found.append((xs[i], sm[i], sm[i] - lo))
    found.sort(key=lambda t: -t[2])
    kept = []
    for x, y, _p in found:
        if all(abs(x - k[0]) >= min_sep for k in kept):
            kept.append((x, y))
        if len(kept) >= limit:
            break
    return kept


def auto_label(energy, counts, lines, hv=None, window=2.0, **kw):
    """Peaks of a survey each given the best-matching line:
    ``[(be, "C 1s")]`` (peaks with no candidate are left out)."""
    out = []
    for be, _h in find_peaks(energy, counts, **kw):
        cand = candidates(be, window, lines, hv)
        if cand:
            out.append((be, label_of(cand[0][1])))
    return sorted(out)
