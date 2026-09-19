"""Holder photo geometry: mapping stage positions (mm) onto a camera photo of
the sample holder, and the small adjustments the calibration panel makes.

A calibration is ``{centre_x_mm, centre_y_mm, mm_per_px, flip_x, flip_y,
rotation_deg}``: the stage position at the photo centre, the scale, and how
the camera is turned relative to the stage. It is stored *per workbook*
(``holder.json``); the last one used also seeds new workbooks.

Pure functions, no Tk and no matplotlib, so they are unit-testable.
"""

from __future__ import annotations

import math

DEFAULT = {"centre_x_mm": 0.0, "centre_y_mm": 0.0, "mm_per_px": 0.02,
           "flip_x": False, "flip_y": False, "rotation_deg": 0.0}
_NUMBERS = ("centre_x_mm", "centre_y_mm", "mm_per_px", "rotation_deg")


def sanitise(c):
    """A complete, valid calibration from a saved dict, or ``None`` when
    ``c`` is not a usable calibration (missing, not a dict, zero scale)."""
    if not isinstance(c, dict):
        return None
    out = dict(DEFAULT)
    for key in _NUMBERS:
        if key in c:
            v = c[key]
            if isinstance(v, bool) or not isinstance(v, (int, float, str)):
                return None
            try:
                v = float(v)
            except ValueError:
                return None
            if not math.isfinite(v):
                return None
            out[key] = v
    for key in ("flip_x", "flip_y"):
        out[key] = bool(c.get(key, False))
    if out["mm_per_px"] == 0:
        return None
    out["mm_per_px"] = abs(out["mm_per_px"])
    return out


def stage_to_pixel(x_mm, y_mm, img_w, img_h, c):
    """Image pixel (origin top-left) of a stage position."""
    dx = (x_mm - c["centre_x_mm"]) / c["mm_per_px"]
    dy = (y_mm - c["centre_y_mm"]) / c["mm_per_px"]
    if c.get("flip_x"):
        dx = -dx
    if c.get("flip_y"):
        dy = -dy
    th = math.radians(c.get("rotation_deg", 0.0))
    rx = dx * math.cos(th) - dy * math.sin(th)
    ry = dx * math.sin(th) + dy * math.cos(th)
    return img_w / 2.0 + rx, img_h / 2.0 + ry


def pixel_to_stage(px, py, img_w, img_h, c):
    """Stage position (mm) under an image pixel: the inverse of
    ``stage_to_pixel``."""
    rx, ry = px - img_w / 2.0, py - img_h / 2.0
    th = math.radians(c.get("rotation_deg", 0.0))
    dx = rx * math.cos(th) + ry * math.sin(th)
    dy = -rx * math.sin(th) + ry * math.cos(th)
    if c.get("flip_x"):
        dx = -dx
    if c.get("flip_y"):
        dy = -dy
    return (c["centre_x_mm"] + dx * c["mm_per_px"],
            c["centre_y_mm"] + dy * c["mm_per_px"])


def nudged(c, dx_px, dy_px):
    """Calibration whose markers sit ``dx_px`` right and ``dy_px`` down of
    where ``c`` puts them, whatever the flips and rotation (the correction
    is made in image space, so an arrow always moves the markers the way it
    points)."""
    x, y = pixel_to_stage(-dx_px, -dy_px, 0.0, 0.0, c)
    return dict(c, centre_x_mm=x, centre_y_mm=y)


def scaled(c, factor):
    """Markers spread ``factor`` times further from the photo centre
    (``factor > 1`` spreads them; the scale is mm per pixel, so it shrinks)."""
    if not factor or not math.isfinite(factor) or factor <= 0:
        return dict(c)
    return dict(c, mm_per_px=c["mm_per_px"] / factor)


def rotated(c, degrees):
    """Markers turned ``degrees`` further about the photo centre."""
    return dict(c, rotation_deg=((c.get("rotation_deg", 0.0) + degrees
                                  + 180.0) % 360.0) - 180.0)


def flipped(c, axis):
    """Calibration with the X or Y flip toggled."""
    key = "flip_x" if axis == "x" else "flip_y"
    return dict(c, **{key: not c.get(key, False)})


def marker_points(positions, img_w, img_h, c):
    """``{sample: (px, py)}`` for stage ``positions`` ``{sample: (x, y)}``."""
    return {s: stage_to_pixel(x, y, img_w, img_h, c)
            for s, (x, y) in positions.items()}


def nearest(points, x, y, max_dist):
    """Name of the point closest to ``(x, y)`` within ``max_dist``, or None.
    ``points`` is ``{name: (px, py)}`` in the same units as x, y."""
    best, best_d = None, max_dist
    for name, (px, py) in points.items():
        d = math.hypot(px - x, py - y)
        if d <= best_d:
            best, best_d = name, d
    return best
