"""Cover pictures for the report and the slides.

Tk-free. A *cover* is the small dict kept in the report spec
(``reportspec``): ``{"design": id, "image": path, "accent": "#RRGGBB"}``.
Designs are

* built in and drawn here from one accent colour (so they match whatever
  colour the report uses): ``ribbon`` (stacked, fading peaks), ``band`` (a solid
  band with fine rules and a silhouette), ``minimal`` (a rule and whitespace),
  ``data`` (the spectrum you are reporting on, as a hero line; the ribbon when
  there is none) and ``grid`` (a peak map);
* a picture in ``assets/covers/`` (``file:<name>``), or any picture the user
  browsed to (``image`` with the path in ``cover["image"]``): cropped to the
  shape of the space from the middle, never stretched, and stored as JPEG so a
  photograph does not make the report heavy;
* ``none``: text only.

``art(cover, "pdf" | "pptx", data)`` gives the picture and the size to place it at,
so the PDF and the slides show one design. Without matplotlib (built-ins) or
Pillow (pictures) there is no art and the cover is text only; nothing raises.
"""

from __future__ import annotations

import hashlib
import io
import os
from dataclasses import dataclass

import appinfo

DEFAULT_ACCENT = "#2C3E50"
ACCENTS = (("Navy", "#2C3E50"), ("Teal", "#1F7A8C"), ("Green", "#2E7D5B"),
           ("Crimson", "#A23B4A"), ("Amber", "#B7791F"), ("Slate", "#5B6470"))
DEFAULT_DESIGN = "ribbon"

BUILTIN = (("ribbon", "Spectrum ribbon"), ("band", "Band"),
           ("minimal", "Minimal"), ("data", "Your data"),
           ("grid", "Peak map"))
NAMES = dict(BUILTIN)

# where the art goes and how big: (width, height) in mm for the PDF (inside the
# page margins), in inches for a slide (a strip along the bottom) and for the
# Word document (a banner at the top, the same 4:1 shape as the PDF's, sized
# to its default content width); the resolution it is drawn at is chosen so a
# photograph stays light
SIZES = {"pdf": (180.0, 45.0, "mm", 200), "pptx": (13.333, 1.55, "in", 150),
         "docx": (6.5, 1.625, "in", 200)}
THUMB = (240, 60, 100)                       # pixels and dpi of a preview

try:
    from PIL import Image
    HAVE_PIL = True
except ImportError:                                      # pragma: no cover
    HAVE_PIL = False
try:
    import matplotlib                                     # noqa: F401
    HAVE_MPL = True
except ImportError:                                      # pragma: no cover
    HAVE_MPL = False


@dataclass
class Cover:
    id: str                 # what goes in cover["design"]
    name: str               # what the picker shows
    kind: str               # none | builtin | file


@dataclass
class Art:
    data: bytes | None      # the picture; None: no art (text-only cover)
    width: float = 0.0      # size to place it at, in ``unit``
    height: float = 0.0
    unit: str = "mm"
    note: str = ""          # why there is none, or what was substituted
    fmt: str = "png"        # "png" or "jpeg"


# -- colour --------------------------------------------------------------------
def valid_accent(text):
    """``text`` as '#RRGGBB' (upper case), or '' when it is not one."""
    t = str(text or "").strip()
    if len(t) == 7 and t[0] == "#":
        try:
            int(t[1:], 16)
            return t.upper()
        except ValueError:
            pass
    return ""


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    """The colour ``t`` of the way from ``a`` to ``b`` (both '#RRGGBB')."""
    ra, rb = _rgb(a), _rgb(b)
    return "#%02X%02X%02X" % tuple(round(x + (y - x) * t)
                                   for x, y in zip(ra, rb))


def tint(accent, t):
    """``accent`` faded towards white: 0 = the accent, 1 = white."""
    return mix(accent, "#FFFFFF", t)


# -- the list ------------------------------------------------------------------
def list_covers(folder=None):
    """Everything the picker can offer, in order: none, the built-in designs
    and the pictures in ``assets/covers``."""
    out = [Cover("none", "No picture", "none")]
    out += [Cover(i, n, "builtin") for i, n in BUILTIN]
    for name, _path in appinfo.cover_images(folder):
        out.append(Cover("file:" + name, os.path.splitext(name)[0], "file"))
    return out


def resolve(cover, folder=None):
    """``(design, picture path or None, note)`` for a cover dict: the design
    actually used (``none`` / a built-in / ``picture``) and, for a picture, its
    file. A picture that is gone or a design that is unknown says so in the
    note and falls back to text only."""
    cover = cover or {}
    design = str(cover.get("design") or "none")
    if design == "none" or design in NAMES:
        return design, None, ""
    if design == "image":
        path = str(cover.get("image") or "")
        return ("picture", path, "") if os.path.isfile(path) else (
            "none", None, f"the cover picture {path or '(none chosen)'} "
                          "was not found")
    if design.startswith("file:"):
        name = design[5:]
        for n, path in appinfo.cover_images(folder):
            if n == name:
                return "picture", path, ""
        return "none", None, f"the cover picture {name} was not found"
    return "none", None, f"unknown cover design {design}"


# -- drawing -------------------------------------------------------------------
def _gauss(x, c, w):
    import numpy as np
    return np.exp(-0.5 * ((x - c) / w) ** 2)


def _draw_ribbon(ax, w, h, accent, _data):
    import numpy as np
    x = np.linspace(0.0, 1.0, 600)
    # peak positions, widths and heights of each layer: fixed, so the design is
    # the same every time
    layers = [((0.16, 0.030, 0.9), (0.34, 0.020, 0.5), (0.61, 0.026, 0.7),
               (0.83, 0.018, 0.4)),
              ((0.12, 0.028, 0.6), (0.29, 0.022, 0.9), (0.55, 0.020, 0.5),
               (0.78, 0.030, 0.8)),
              ((0.21, 0.025, 0.8), (0.42, 0.030, 0.6), (0.66, 0.022, 0.9),
               (0.90, 0.020, 0.5)),
              ((0.10, 0.020, 0.5), (0.37, 0.026, 0.8), (0.58, 0.030, 0.6),
               (0.74, 0.020, 0.7)),
              ((0.18, 0.030, 0.7), (0.47, 0.020, 0.9), (0.70, 0.028, 0.5),
               (0.87, 0.022, 0.6))]
    n = len(layers)
    for k in range(n - 1, -1, -1):                # back (top, pale) to front
        base = 0.10 + 0.145 * k
        y = sum(a * _gauss(x, c, s) for c, s, a in layers[k]) * 0.26
        ax.fill_between(x, base, base + y, color=tint(accent, 0.12 + 0.13 * k),
                        linewidth=0, zorder=2 + (n - k) * 2)
        ax.plot(x, base + y, color=tint(accent, 0.05 + 0.10 * k),
                linewidth=0.9, zorder=3 + (n - k) * 2)


def _draw_band(ax, w, h, accent, _data):
    import numpy as np
    ax.add_patch(matplotlib_rect(0, 0, 1, 1, accent))
    for y in (0.22, 0.42, 0.62, 0.82):
        ax.plot([0, 1], [y, y], color=tint(accent, 0.82), linewidth=0.6,
                alpha=0.35, zorder=3)
    x = np.linspace(0.0, 1.0, 500)
    y = 0.05 + 0.34 * (0.9 * _gauss(x, 0.30, 0.035)
                       + 0.6 * _gauss(x, 0.52, 0.03)
                       + 1.0 * _gauss(x, 0.74, 0.04)
                       + 0.45 * _gauss(x, 0.90, 0.025))
    ax.fill_between(x, 0, y, color=tint(accent, 0.55), alpha=0.55,
                    linewidth=0, zorder=4)
    ax.plot(x, y, color=tint(accent, 0.75), linewidth=1.0, zorder=5)


def _draw_minimal(ax, w, h, accent, _data):
    import numpy as np
    ax.plot([0.0, 1.0], [0.5, 0.5], color=tint(accent, 0.75), linewidth=0.8)
    ax.plot([0.0, 0.13], [0.5, 0.5], color=accent, linewidth=4.0,
            solid_capstyle="butt")
    x = np.linspace(0.84, 1.0, 120)
    y = 0.5 + 0.22 * (0.8 * _gauss(x, 0.90, 0.012) + _gauss(x, 0.95, 0.010))
    ax.plot(x, y, color=accent, linewidth=1.2)


def _draw_grid(ax, w, h, accent, _data):
    import numpy as np
    from matplotlib.colors import LinearSegmentedColormap
    nx = 96
    ny = max(6, round(nx * h / w))
    xs = np.linspace(0, 1, nx)[None, :]
    ys = np.linspace(0, 1, ny)[:, None]
    field = np.zeros((ny, nx))
    for cx, cy, sx, sy, a in ((0.18, 0.60, 0.07, 0.30, 0.8),
                              (0.42, 0.35, 0.10, 0.35, 1.0),
                              (0.66, 0.65, 0.06, 0.28, 0.7),
                              (0.85, 0.40, 0.08, 0.32, 0.9)):
        field += a * np.exp(-0.5 * (((xs - cx) / sx) ** 2
                                    + ((ys - cy) / sy) ** 2))
    rng = np.random.default_rng(7)                # fixed: the same every time
    field += 0.05 * rng.random((ny, nx))
    cmap = LinearSegmentedColormap.from_list("cover", [tint(accent, 0.94),
                                                       tint(accent, 0.45),
                                                       accent])
    ax.imshow(field, cmap=cmap, extent=(0, 1, 0, 1), origin="lower",
              interpolation="nearest", aspect="auto", vmin=0,
              vmax=float(field.max()))


def _draw_data(ax, w, h, accent, data):
    import numpy as np
    try:
        e = np.asarray(data[0], dtype=float)
        c = np.asarray(data[1], dtype=float)
        ok = e.size == c.size and e.size >= 3 and np.isfinite(c).all()
    except (TypeError, ValueError, IndexError):
        ok = False
    if not ok:
        return _draw_ribbon(ax, w, h, accent, None)
    step = max(1, e.size // 900)
    e, c = e[::step], c[::step]
    span = float(e.max() - e.min()) or 1.0
    x = 0.03 + 0.94 * (float(e.max()) - e) / span      # binding energy: high at left
    order = np.argsort(x)
    x, c = x[order], c[order]
    lo, hi = float(c.min()), float(c.max())
    y = 0.14 + 0.72 * (c - lo) / ((hi - lo) or 1.0)
    ax.fill_between(x, 0.14, y, color=tint(accent, 0.72), linewidth=0, zorder=2)
    ax.plot(x, y, color=accent, linewidth=1.3, zorder=3)
    ax.plot([0.03, 0.97], [0.14, 0.14], color=tint(accent, 0.5), linewidth=0.8,
            zorder=3)


def matplotlib_rect(x, y, w, h, colour):
    from matplotlib.patches import Rectangle
    return Rectangle((x, y), w, h, facecolor=colour, edgecolor="none",
                     zorder=1)


_DRAW = {"ribbon": _draw_ribbon, "band": _draw_band, "minimal": _draw_minimal,
         "grid": _draw_grid, "data": _draw_data}


def _render_builtin(design, px, dpi, accent, data):
    if not HAVE_MPL:
        return None
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        w, h = px
        fig = Figure(figsize=(w / dpi, h / dpi), dpi=dpi, facecolor="white")
        FigureCanvasAgg(fig)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_axis_off()
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        _DRAW[design](ax, w, h, accent, data)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, facecolor="white")
        return buf.getvalue()
    except Exception:                                    # noqa: BLE001
        return None                # art is a nicety: never stop a report


def _render_picture(path, px, fmt="jpeg"):
    """The picture at ``path`` scaled to cover ``px`` and cropped to it from
    the middle, as JPEG (or PNG); None when it cannot be read."""
    if not HAVE_PIL:
        return None
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            w, h = px
            scale = max(w / im.width, h / im.height)
            size = (max(w, round(im.width * scale)),
                    max(h, round(im.height * scale)))
            im = im.resize(size, Image.LANCZOS)
            left, top = (size[0] - w) // 2, (size[1] - h) // 2
            im = im.crop((left, top, left + w, top + h))
            buf = io.BytesIO()
            if fmt == "jpeg":
                im.save(buf, format="JPEG", quality=90, optimize=True)
            else:
                im.save(buf, format="PNG")
            return buf.getvalue()
    except Exception:                                    # noqa: BLE001
        return None


_cache = {}


def _data_key(data):
    if not data:
        return ""
    try:
        e, c = list(data[0]), list(data[1])
        stride = max(1, len(e) // 64)
        return hashlib.sha1(repr((len(e), e[::stride], c[::stride]))
                            .encode()).hexdigest()
    except Exception:                                    # noqa: BLE001
        return ""


def render(cover, px, dpi, data=None, folder=None, jpeg=False):
    """``(picture bytes or None, note)`` for ``cover`` at ``px`` = (w, h)
    pixels. A picture of the user's is JPEG when ``jpeg`` (report and slides)
    and PNG otherwise (the picker's previews, which Tk can show); a built-in
    design is always PNG."""
    design, path, note = resolve(cover, folder)
    if design == "none":
        return None, note
    accent = valid_accent((cover or {}).get("accent")) or DEFAULT_ACCENT
    mtime = ""
    if path:
        try:
            mtime = f"{os.path.getmtime(path):.0f}:{os.path.getsize(path)}"
        except OSError:
            mtime = ""
    key = (design, path, mtime, px, dpi, accent, bool(jpeg),
           _data_key(data) if design == "data" else "")
    if key in _cache:
        return _cache[key], note
    if design == "picture":
        png = _render_picture(path, px, "jpeg" if jpeg else "png")
        if png is None:
            return None, note or f"the picture {os.path.basename(path)} " \
                                 "could not be read"
    else:
        png = _render_builtin(design, px, dpi, accent, data)
        if png is None:
            return None, note or "the cover picture needs matplotlib"
    if len(_cache) > 48:
        _cache.pop(next(iter(_cache)))
    _cache[key] = png
    return png, note


def art(cover, kind, data=None, folder=None):
    """The cover picture for the ``"pdf"`` or ``"pptx"`` cover, with the size
    (in ``unit``) to place it at. ``data`` = ``(energy, counts)`` for the
    ``data`` design. ``Art.png`` is None when there is nothing to show."""
    width, height, unit, dpi = SIZES[kind]
    inches = (width / 25.4, height / 25.4) if unit == "mm" else (width, height)
    px = (round(inches[0] * dpi), round(inches[1] * dpi))
    data_, note = render(cover, px, dpi, data, folder, jpeg=True)
    fmt = "jpeg" if data_ and data_[:2] == b"\xff\xd8" else "png"
    return Art(data_, width, height, unit, note, fmt)


def thumbnail(cover, data=None, folder=None):
    """A small PNG (240 x 60) of ``cover`` for the picker, or None."""
    w, h, dpi = THUMB
    return render(cover, (w, h), dpi, data, folder)[0]
