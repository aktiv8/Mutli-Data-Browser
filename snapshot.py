"""Sample-view camera images (and the SnapMaps taken on them): geometry.

Tk-free. Every camera image carries its own calibration in ``ImageBlob.calib``:
the stage position of its centre and the size of a pixel, so no holder photo or
manual calibration is needed to say where an analysis point sits on it::

    {"x_mm", "y_mm": stage position of the image centre,
     "um_per_px_x", "um_per_px_y", "width", "height"}

Axis directions were measured, not assumed, on a K-Alpha+: neighbouring images
registered against each other (four pairs, correlation 0.53-0.80 against under
0.3 for every other sign choice) show that **image x runs against stage X and
image y runs with stage Y**. A SnapMap's own X / Y axes, by contrast, follow the
image (its maps overlay the photo without a flip), and are centred on the stage
position stored with the map.
"""

from __future__ import annotations

import math

X_DIR = -1      # image column increases as stage X decreases
Y_DIR = +1      # image row increases as stage Y increases


def has_calibration(calib) -> bool:
    return bool(calib) and all(
        calib.get(k) for k in ("width", "height", "um_per_px_x",
                               "um_per_px_y", "x_mm", "y_mm"))


def stage_to_pixel(calib, x_mm, y_mm):
    """Pixel ``(column, row)`` of a stage position (may lie outside the image)."""
    return (calib["width"] / 2 + X_DIR * (x_mm - calib["x_mm"]) * 1000.0
            / calib["um_per_px_x"],
            calib["height"] / 2 + Y_DIR * (y_mm - calib["y_mm"]) * 1000.0
            / calib["um_per_px_y"])


def pixel_to_stage(calib, col, row):
    """Stage position ``(x_mm, y_mm)`` under a pixel."""
    return (calib["x_mm"] + X_DIR * (col - calib["width"] / 2)
            * calib["um_per_px_x"] / 1000.0,
            calib["y_mm"] + Y_DIR * (row - calib["height"] / 2)
            * calib["um_per_px_y"] / 1000.0)


def field_of_view_mm(calib):
    """``(width, height)`` of the picture in mm."""
    return (calib["width"] * calib["um_per_px_x"] / 1000.0,
            calib["height"] * calib["um_per_px_y"] / 1000.0)


def markers(calib, positions, margin=0.0):
    """``{label: (column, row)}`` for the stage positions that fall inside the
    picture (``margin`` extra pixels are allowed round the edge).
    ``positions`` is ``{label: (x_mm, y_mm)}``."""
    out = {}
    w, h = calib["width"], calib["height"]
    for label, (x, y) in positions.items():
        c, r = stage_to_pixel(calib, x, y)
        if -margin <= c <= w + margin and -margin <= r <= h + margin:
            out[label] = (c, r)
    return out


def map_rectangle(calib, cube):
    """Where a SnapMap lies on the picture: ``(left, top, width, height)`` in
    pixels. The map is centred on its own stage position (the picture's centre
    when it has none)."""
    if cube.stage_x_mm is not None and cube.stage_y_mm is not None:
        cx, cy = stage_to_pixel(calib, cube.stage_x_mm, cube.stage_y_mm)
    else:
        cx, cy = calib["width"] / 2, calib["height"] / 2
    left, right, bottom, top = cube.extent()           # µm, in the image frame
    ux, uy = calib["um_per_px_x"], calib["um_per_px_y"]
    return (cx + left / ux, cy + top / uy, (right - left) / ux,
            (bottom - top) / uy)


def nearest_image(images, x_mm, y_mm, tol_mm=0.1):
    """The calibrated picture centred closest to a stage position, within
    ``tol_mm``; among equals the latest one (images are in time order)."""
    best, best_d = None, tol_mm
    for blob in images:
        c = blob.calib
        if not has_calibration(c):
            continue
        d = math.hypot(c["x_mm"] - x_mm, c["y_mm"] - y_mm)
        if d <= best_d:
            best, best_d = blob, d
    return best
