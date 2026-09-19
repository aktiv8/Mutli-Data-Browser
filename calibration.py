"""Binding-energy calibration helpers (pure): find a reference peak and work
out the shift that puts it at its reference energy, and word the calibration
statement for reports."""

from __future__ import annotations

# (label, expected measured BE for searching, reference BE)
PRESETS = [
    ("C 1s adventitious carbon - 284.8 eV", 285.0, 284.8),
    ("Au 4f7/2 - 83.95 eV", 84.0, 83.95),
    ("Ag 3d5/2 - 368.26 eV", 368.3, 368.26),
    ("Cu 2p3/2 - 932.67 eV", 932.7, 932.67),
    ("Fermi edge - 0 eV", 0.0, 0.0),
    ("Custom", None, None),
]


def find_peak(energy, counts, lo, hi, smooth=5):
    """Binding energy of the maximum of a (lightly smoothed) spectrum inside
    ``[lo, hi]``, refined by a parabola through the top three points.

    Returns ``(be, height)`` or None if the window holds fewer than 3 points.
    ``energy`` may run in either direction."""
    lo, hi = min(lo, hi), max(lo, hi)
    pts = sorted((e, c) for e, c in zip(energy, counts) if lo <= e <= hi)
    if len(pts) < 3:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    n = len(ys)
    half = max(0, smooth // 2)
    sm = []
    for i in range(n):
        a, b = max(0, i - half), min(n, i + half + 1)
        sm.append(sum(ys[a:b]) / (b - a))
    k = max(range(n), key=sm.__getitem__)
    if 0 < k < n - 1:
        y0, y1, y2 = sm[k - 1], sm[k], sm[k + 1]
        den = y0 - 2 * y1 + y2
        if den < 0:
            off = 0.5 * (y0 - y2) / den                # in [-0.5, 0.5]
            step = (xs[k + 1] - xs[k - 1]) / 2.0
            return xs[k] + off * step, y1
    return xs[k], sm[k]


def shift_for(measured, reference):
    """The correction to add to measured energies."""
    return float(reference) - float(measured)


def statement(entries, override=""):
    """Calibration statement for reports. An explicit ``override`` wins;
    otherwise one sentence per logged calibration (latest per scope)."""
    if override and override.strip():
        return override.strip()
    latest = {}
    for e in entries:
        latest[e.get("scope", "")] = e
    lines = []
    for e in latest.values():
        if not e.get("shift"):
            continue
        what = e.get("ref_text") or "a reference peak"
        where = e.get("scope_text") or "the data"
        lines.append(
            f"Binding energies of {where} were shifted by "
            f"{e['shift']:+.2f} eV to place {what} at "
            f"{e.get('reference', 0):.2f} eV (measured "
            f"{e.get('measured', 0):.2f} eV).")
    return " ".join(lines)
