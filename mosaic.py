"""Stitching neighbouring camera pictures into one mosaic (Tk-free; numpy and
Pillow are imported where a picture is read).

Every calibrated camera picture knows where its centre is on the stage and how
big a pixel is (``snapshot``), so neighbouring pictures can be laid side by
side with no help. Two things are then done with what the pictures show:

* **matching**: each pair of overlapping pictures is compared where they
  overlap and shifted by the small amount that makes them agree best (the stage
  position is good to a few tens of micrometres, a few to about fifteen
  pixels on a 1280-pixel picture, measured on 15 real pairs: correlation 0.85
  by position alone, 0.91 after matching). A pair is only moved when the match
  is convincing (``MIN_NCC``, ``MIN_GAIN``); a featureless overlap keeps the
  stage position. The pair shifts are then made consistent for the whole set by
  least squares, so a chain of pictures does not drift;
* **blending**: overlaps are feathered (each picture counts less the nearer a
  pixel is to its edge), so there is no hard seam.

The mosaic has a calibration of its own, in the same form as a picture's
(``snapshot`` conventions), so the analysis points and SnapMap outlines on it
come from the same ``snapshot.view_of`` as on any picture.

Only one picture per stage position is used (the latest: it shows the marks of
the analysis); pictures of different pixel size are not mixed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math

import snapshot

MOSAIC_PX = 1800           # longest side of the mosaic's picture
MIN_OVERLAP = 0.10         # of a picture's width and height, to be neighbours
SAME_SPOT_MM = 0.02        # closer than this is the same stage position
SCALE_TOL = 0.02           # pictures of a mosaic share a pixel size within this
COARSE_WIDTH = 320         # pictures are searched at about this width first
SEARCH = 12                # coarse pixels searched each way (about +-48 px)
MIN_PATCH = 40             # smallest overlap (coarse pixels) worth comparing
MIN_NCC = 0.5              # a match must correlate at least this well ...
MIN_GAIN = 0.02            # ... and beat the stage position by this much
PRIOR = 0.1                # weight of "stay where the stage put it"


@dataclass
class Mosaic:
    calib: dict                # same form as a picture's calibration
    array: object              # RGB uint8, at most ``MOSAIC_PX`` on its long side
    names: list                # the pictures used
    positions: dict            # name -> (left, top) in full-size mosaic pixels
    matched: int = 0           # pairs whose match moved them
    pairs: int = 0             # pairs that overlap
    notes: list = field(default_factory=list)

    def description(self):
        """One line on how it was made, for notes and captions."""
        text = f"{len(self.names)} pictures placed by stage position"
        if self.pairs:
            text += (f", {self.matched} of {self.pairs} overlaps refined by "
                     "matching what they show")
        return text + ", overlaps blended."


# -- which pictures belong together --------------------------------------------------
def _footprint(calib):
    fw, fh = snapshot.field_of_view_mm(calib)
    return fw, fh


def _neighbours(a, b):
    """True when two pictures overlap by at least ``MIN_OVERLAP`` of their
    width and of their height."""
    fw, fh = _footprint(a)
    return (abs(a["x_mm"] - b["x_mm"]) < fw * (1 - MIN_OVERLAP)
            and abs(a["y_mm"] - b["y_mm"]) < fh * (1 - MIN_OVERLAP))


def _one_per_spot(pictures):
    """The latest picture at each stage position (``pictures`` in time order)."""
    kept = []
    for pic in pictures:
        c = pic.calib
        for i, old in enumerate(kept):
            o = old.calib
            if (abs(o["x_mm"] - c["x_mm"]) < SAME_SPOT_MM
                    and abs(o["y_mm"] - c["y_mm"]) < SAME_SPOT_MM):
                kept[i] = pic
                break
        else:
            kept.append(pic)
    return kept


def clusters(pictures):
    """Groups of two or more pictures that overlap (directly or through
    neighbours), one picture per stage position and one pixel size per group,
    as lists in the order the pictures were given."""
    pics = [p for p in _one_per_spot(pictures)
            if snapshot.has_calibration(p.calib)]
    parent = list(range(len(pics)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(len(pics)):
        for j in range(i + 1, len(pics)):
            a, b = pics[i].calib, pics[j].calib
            if (abs(a["um_per_px_x"] / b["um_per_px_x"] - 1) <= SCALE_TOL
                    and abs(a["um_per_px_y"] / b["um_per_px_y"] - 1)
                    <= SCALE_TOL and _neighbours(a, b)):
                parent[find(i)] = find(j)
    groups = {}
    for i, p in enumerate(pics):
        groups.setdefault(find(i), []).append(p)
    return [g for g in groups.values() if len(g) > 1]


# -- geometry --------------------------------------------------------------------------
def frame_of(pictures):
    """The calibration of the canvas that holds ``pictures`` (same convention
    as a picture's: stage position of its centre, pixel size, pixels)."""
    ux = pictures[0].calib["um_per_px_x"]
    uy = pictures[0].calib["um_per_px_y"]
    x0 = y0 = math.inf
    x1 = y1 = -math.inf
    for p in pictures:
        c = p.calib
        fw, fh = _footprint(c)
        x0, x1 = min(x0, c["x_mm"] - fw / 2), max(x1, c["x_mm"] + fw / 2)
        y0, y1 = min(y0, c["y_mm"] - fh / 2), max(y1, c["y_mm"] + fh / 2)
    return {"x_mm": (x0 + x1) / 2, "y_mm": (y0 + y1) / 2,
            "um_per_px_x": ux, "um_per_px_y": uy,
            "width": max(1, round((x1 - x0) * 1000.0 / ux)),
            "height": max(1, round((y1 - y0) * 1000.0 / uy))}


def placed(frame, pictures):
    """Where each picture's top left corner falls in the canvas, from the stage
    positions alone: ``[(left, top)]`` in full-size pixels."""
    out = []
    for p in pictures:
        c = p.calib
        cx, cy = snapshot.stage_to_pixel(frame, c["x_mm"], c["y_mm"])
        out.append((cx - c["width"] / 2, cy - c["height"] / 2))
    return out


# -- matching ---------------------------------------------------------------------------
def _gray(rgb):
    return rgb.astype("float32").mean(axis=2)


def _shrink(a, k):
    """``a`` reduced by the whole factor ``k`` (block means)."""
    if k <= 1:
        return a
    h, w = (a.shape[0] // k) * k, (a.shape[1] // k) * k
    return a[:h, :w].reshape(h // k, k, w // k, k).mean(axis=(1, 3))


def _overlap(a, b, dx, dy):
    """The parts of ``a`` and ``b`` (2-D) that coincide when ``b``'s corner is
    ``(dx, dy)`` pixels from ``a``'s; None when they barely touch."""
    dx, dy = int(round(dx)), int(round(dy))
    h, w = a.shape
    x0, x1 = max(0, dx), min(w, dx + b.shape[1])
    y0, y1 = max(0, dy), min(h, dy + b.shape[0])
    if x1 - x0 < MIN_PATCH or y1 - y0 < MIN_PATCH:
        return None
    return (a[y0:y1, x0:x1],
            b[y0 - dy:y1 - dy, x0 - dx:x1 - dx])


def ncc(u, v):
    """Normalised cross-correlation of two equal-shape arrays (0 when either
    is flat)."""
    u = u - u.mean()
    v = v - v.mean()
    den = math.sqrt(float((u * u).sum()) * float((v * v).sum()))
    return float((u * v).sum()) / den if den > 1e-6 else 0.0


def match(a, b, dx, dy, search=SEARCH):
    """How far ``b`` should move from ``(dx, dy)`` (its corner relative to
    ``a``'s, in the pixels of these 2-D arrays) to agree best with ``a``:
    ``(sx, sy, ncc at dx, dy, best ncc)``, or None when they barely overlap.
    Exhaustive over ``+-search`` pixels."""
    base = _overlap(a, b, dx, dy)
    if base is None:
        return None
    n0 = ncc(*base)
    best = (n0, 0, 0)
    for sy in range(-search, search + 1):
        for sx in range(-search, search + 1):
            p = _overlap(a, b, dx + sx, dy + sy)
            if p is None:
                continue
            v = ncc(*p)
            if v > best[0]:
                best = (v, sx, sy)
    return best[1], best[2], n0, best[0]


def refine_pair(ga, gb, dx, dy, scale):
    """The shift, in full-size pixels, that makes two pictures agree where they
    overlap, or None when the match is not convincing. ``ga`` / ``gb`` are
    grey arrays at ``scale`` times full size and ``(dx, dy)`` the full-size
    offset of ``b`` from ``a``. A coarse search over about +-48 px is followed
    by a fine one round its result."""
    k = max(1, round(ga.shape[1] / COARSE_WIDTH))
    ca, cb = _shrink(ga, k), _shrink(gb, k)
    f = scale / k                                   # full-size -> coarse pixels
    coarse = match(ca, cb, dx * f, dy * f)
    if coarse is None:
        return None
    ox, oy = dx * scale + coarse[0] * k, dy * scale + coarse[1] * k
    fine = match(ga, gb, ox, oy, search=k)
    if fine is None:
        return None
    best = fine[3]
    ncc0 = _ncc_at(ga, gb, dx * scale, dy * scale)   # by stage position alone
    if best < MIN_NCC or best - ncc0 < MIN_GAIN:
        return None
    sx = coarse[0] * k + fine[0]
    sy = coarse[1] * k + fine[1]
    return sx / scale, sy / scale, best


def _ncc_at(a, b, dx, dy):
    p = _overlap(a, b, dx, dy)
    return ncc(*p) if p is not None else 0.0


def solve_offsets(n, pair_shifts):
    """One ``(x, y)`` correction per picture from the pair shifts
    ``[(i, j, sx, sy, weight)]`` (``j`` moves ``(sx, sy)`` relative to ``i``):
    least squares, with a weak pull of every picture to where the stage put
    it, so pictures without a match stay and the set cannot drift."""
    import numpy as np
    rows = len(pair_shifts) + n
    a = np.zeros((rows, n))
    bx = np.zeros(rows)
    by = np.zeros(rows)
    for r, (i, j, sx, sy, w) in enumerate(pair_shifts):
        a[r, j], a[r, i] = w, -w
        bx[r], by[r] = w * sx, w * sy
    for i in range(n):
        a[len(pair_shifts) + i, i] = PRIOR
    tx = np.linalg.lstsq(a, bx, rcond=None)[0]
    ty = np.linalg.lstsq(a, by, rcond=None)[0]
    return list(zip(tx.tolist(), ty.tolist()))


# -- putting it together ----------------------------------------------------------------
_memo = {}                                          # key -> Mosaic (a few)


def build(pictures, refine=True):
    """The mosaic of ``pictures`` (one cluster from ``clusters``): pictures
    exposing ``calib``, ``name`` and ``array(max_px)``."""
    import numpy as np
    from PIL import Image

    # keyed on the picture's own identity (its ``blob`` when there is one,
    # e.g. imagepages.Picture -- a name and a rounded position are not
    # enough: a picture retaken at the same spot on the same sample keeps
    # both, and would otherwise silently get the earlier one's mosaic) plus
    # its position, so a picture nudged in the calibration still rebuilds
    key = (refine, tuple((id(getattr(p, "blob", p)),
                          round(p.calib["x_mm"], 4),
                          round(p.calib["y_mm"], 4)) for p in pictures))
    if key in _memo:
        return _memo[key]
    frame = frame_of(pictures)
    base = placed(frame, pictures)
    k = min(1.0, MOSAIC_PX / max(frame["width"], frame["height"]))
    arrays = []
    for p in pictures:
        width = max(64, round(p.calib["width"] * k))
        arrays.append(p.array(width))
    scales = [a.shape[1] / p.calib["width"] for a, p in zip(arrays, pictures)]

    shifts, pairs = [], 0
    notes = []
    if refine:
        grays = [_gray(a) for a in arrays]
        for i in range(len(pictures)):
            for j in range(i + 1, len(pictures)):
                if not _neighbours(pictures[i].calib, pictures[j].calib):
                    continue
                pairs += 1
                dx = base[j][0] - base[i][0]
                dy = base[j][1] - base[i][1]
                got = refine_pair(grays[i], grays[j], dx, dy, scales[i])
                if got is not None:
                    shifts.append((i, j, got[0], got[1], got[2]))
    corr = solve_offsets(len(pictures), shifts) if shifts else \
        [(0.0, 0.0)] * len(pictures)
    left_alone = pairs - len(shifts)
    if left_alone > 0:
        notes.append(f"{left_alone} overlap{'s' if left_alone != 1 else ''} "
                     "had too little detail to match and stay where the "
                     "stage put them.")

    w, h = round(frame["width"] * k), round(frame["height"] * k)
    acc = np.zeros((h, w, 3), dtype="float32")
    wsum = np.zeros((h, w), dtype="float32")
    pos = {}
    for p, a, (bx, by), (cx, cy) in zip(pictures, arrays, base, corr):
        left, top = bx + cx, by + cy
        pos[p.name] = (left, top)
        tw, th = max(1, round(p.calib["width"] * k)), \
            max(1, round(p.calib["height"] * k))
        if a.shape[1] != tw or a.shape[0] != th:
            a = np.asarray(Image.fromarray(a).resize((tw, th),
                                                     Image.LANCZOS))
        x0, y0 = round(left * k), round(top * k)
        sx0, sy0 = max(0, -x0), max(0, -y0)
        sx1, sy1 = min(tw, w - x0), min(th, h - y0)
        if sx1 <= sx0 or sy1 <= sy0:
            continue
        ramp_x = np.minimum(np.arange(tw), np.arange(tw)[::-1]) + 1.0
        ramp_y = np.minimum(np.arange(th), np.arange(th)[::-1]) + 1.0
        weight = np.minimum.outer(ramp_y, ramp_x).astype("float32")
        ys, xs = slice(y0 + sy0, y0 + sy1), slice(x0 + sx0, x0 + sx1)
        wt = weight[sy0:sy1, sx0:sx1]
        acc[ys, xs] += a[sy0:sy1, sx0:sx1].astype("float32") * wt[..., None]
        wsum[ys, xs] += wt
    out = np.full((h, w, 3), 24, dtype="uint8")          # dark where nothing is
    ok = wsum > 0
    out[ok] = np.clip(acc[ok] / wsum[ok][:, None] + 0.5, 0, 255).astype(
        "uint8")
    m = Mosaic(frame, out, [p.name for p in pictures], pos, len(shifts),
               pairs, notes)
    _memo[key] = m
    while len(_memo) > 6:
        _memo.pop(next(iter(_memo)))
    return m
