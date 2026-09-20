"""REELS (reflection electron energy loss spectroscopy): the band gap from
the onset of inelastic losses.

A REELS spectrum is intensity against kinetic energy, with the elastic peak
at the primary energy; ``loss = E_elastic - KE`` is how much energy each
electron gave up. The band gap is read from the *onset*: a straight line (the
tangent) is drawn through two points the user picks on the rising edge of the
loss spectrum, and the gap is where that line meets the baseline level of the
flat region between the elastic peak and the onset.

Pure functions, no Tk.
"""

from __future__ import annotations

import math

ELASTIC_TAIL = 0.5          # eV: the elastic peak's own tail is not baseline


def elastic_peak(ke, counts):
    """Kinetic energy of the strongest point (the elastic peak), or None."""
    if not ke or not counts or len(ke) != len(counts):
        return None
    i = max(range(len(counts)), key=counts.__getitem__)
    return ke[i]


def loss_axis(ke, elastic):
    """Energy loss for each kinetic energy."""
    return [elastic - k for k in ke]


def _median(vals):
    vals = sorted(vals)
    n = len(vals)
    if not n:
        return None
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def baseline(loss, y, onset):
    """The flat level before the onset: the median intensity between the end
    of the elastic tail and the lower of the picked points; with too few
    points there, the lowest intensity up to the higher pick."""
    lo_x = min(onset)
    sel = [v for x, v in zip(loss, y) if ELASTIC_TAIL < x < lo_x]
    if len(sel) > 3:
        return _median(sel)
    hi_x = max(onset)
    sel = [v for x, v in zip(loss, y) if 0 < x < hi_x]
    return min(sel) if sel else None


def band_gap(loss, y, p1, p2, base=None):
    """``{"gap", "slope", "base"}`` from the tangent through ``p1`` and
    ``p2`` (each ``(loss, intensity)``), or None when the two points do not
    define a rising edge that meets the baseline at a positive loss."""
    (x1, y1), (x2, y2) = p1, p2
    if not all(math.isfinite(v) for v in (x1, y1, x2, y2)) or x1 == x2:
        return None
    slope = (y2 - y1) / (x2 - x1)
    if slope <= 0:
        return None
    if base is None:
        base = baseline(loss, y, (x1, x2))
    if base is None:
        return None
    gap = x1 + (base - y1) / slope
    if not math.isfinite(gap) or gap <= 0:
        return None
    return {"gap": gap, "slope": slope, "base": base}


def tangent_points(result, p1, p2, span=1.25):
    """Two ``(loss, intensity)`` ends for drawing: from the baseline crossing
    to a little beyond the higher pick."""
    gap = result["gap"]
    x_end = max(p1[0], p2[0])
    x_end = gap + (x_end - gap) * span
    y_end = result["base"] + result["slope"] * (x_end - gap)
    return (gap, result["base"]), (x_end, y_end)
