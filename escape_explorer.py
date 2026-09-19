#!/usr/bin/env python3
"""
ESCApe Explorer
===============
A single-window GUI to browse, plot and export XPS spectra from many
instruments (Kratos ESCApe/Vision, VAMAS from any vendor, Thermo Avantage,
PHI MultiPak, Scienta SES).

* **File tree with tick boxes**: tick spectra to plot them; spectra of the same
  element are stacked with a y offset on one panel.
* **Readers** (``readers/``): one module per format, chosen by content.
* **Themes** (``themes.py``), **PDF preview** (``pdf_preview.py``) and
  **exporters** (``exporters.py``: CSV, VAMAS, metadata CSV/PDF).

Dependencies
------------
* ``tkinter``  (standard library)
* ``matplotlib``  (spectrum plots)                  pip install matplotlib
* ``Pillow``      (camera images)                   pip install pillow
* ``reportlab``   (formatted metadata PDF)          pip install reportlab
* ``pymupdf``     (in-app PDF preview)              pip install pymupdf

The app runs without the optional packages; the affected panes show a notice.

Note on reverse-engineered formats
----------------------------------
``.experiment`` (Kratos ESCApe), ``.vgd`` (Thermo) and ``.kal`` (Kratos Vision)
are undocumented; their readers are best-effort and were validated against
exports of the same data. See the README.
"""

from __future__ import annotations

import os
import re
import sys
import csv
import copy
import io
import shutil
import tempfile
import textwrap
import contextlib
import json
import math

import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

# Optional dependencies ----------------------------------------------------
try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import (
        FigureCanvasTkAgg, NavigationToolbar2Tk
    )
    HAVE_MPL = True
except Exception:
    HAVE_MPL = False

try:
    from PIL import Image, ImageTk
    HAVE_PIL = True
except Exception:
    HAVE_PIL = False



from readers import (Region, ImageBlob, TreeNode, SpectrumFile, EscapeParser,
                     load_file, reader_for, supported_patterns,
                     UnsupportedFormat)
import fonts
import themes
import viewdata
import metasummary
import workbook as wbk
import report
import pptx_export
import importplan
import workbook_ui
from themes import (ThemeManager, THEME_NAMES, PRINT, mpl_rc, SwatchCache,
                    ramp)
from pdf_preview import PdfPreview, HAVE_PDF, open_external
from exporters import (export_csv, export_vamas, export_metadata_csv,
                       export_metadata_pdf)


# ==========================================================================
#  GUI
# ==========================================================================
CALIB_PATH = os.path.join(os.path.expanduser("~"), ".escape_explorer_calib.json")


def load_calibration():
    try:
        with open(CALIB_PATH) as fh:
            return json.load(fh)
    except Exception:
        return None


def save_calibration(c):
    try:
        with open(CALIB_PATH, "w") as fh:
            json.dump(c, fh, indent=2)
        return True
    except Exception:
        return False


CONFIG_PATH = os.path.join(os.path.expanduser("~"),
                           ".escape_explorer_config.json")


def load_config():
    """User settings (theme, layout, view options); missing file -> {}."""
    try:
        with open(CONFIG_PATH) as fh:
            cfg = json.load(fh)
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w") as fh:
            json.dump(cfg, fh, indent=2)
        return True
    except Exception:
        return False


def stage_to_pixel(x_mm, y_mm, img_w, img_h, c):
    """Map a stage coordinate (mm) to an image pixel using a calibration:
    {centre_x_mm, centre_y_mm, mm_per_px, flip_x, flip_y, rotation_deg}."""
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


def interp_intensity(region, energy):
    """Linear interpolation of a region's intensity at a given energy.
    Works for ascending or descending energy axes; clamps at the ends."""
    xs, ys = region.energy, region.counts
    if not xs or not ys:
        return None
    pts = sorted(zip(xs, ys))
    xs2 = [p[0] for p in pts]
    ys2 = [p[1] for p in pts]
    if energy <= xs2[0]:
        return ys2[0]
    if energy >= xs2[-1]:
        return ys2[-1]
    import bisect
    i = bisect.bisect_left(xs2, energy)
    x0, x1 = xs2[i - 1], xs2[i]
    y0, y1 = ys2[i - 1], ys2[i]
    f = (energy - x0) / (x1 - x0) if x1 != x0 else 0.0
    return y0 + f * (y1 - y0)


def trace_label(r, multi_file=False, show_name=True):
    """Short end-of-trace label. Depth profiles: the level (and etch time);
    otherwise the sample, plus the region name only where a panel mixes
    regions. Unnamed samples fall back to the file stem (several files) or the
    region name. Colour already tells files apart, so no file prefix."""
    if r.etch_level is not None:
        base = (f"L{r.etch_level} ({r.etch_time:g} s)"
                if r.etch_time is not None else f"L{r.etch_level}")
    else:
        parts = [r.sample] if r.sample else []
        if show_name and parts:
            parts.append(r.name)
        if not parts:
            parts = [os.path.splitext(r.source)[0]
                     if (multi_file and r.source) else r.name]
        base = " ".join(parts)
    return base if len(base) <= 24 else base[:22] + "…"


def colour_slots(docs):
    """{id(region): palette slot}: one slot per file when several files are
    loaded, else one per sample, so a file/sample keeps its colour whatever is
    ticked."""
    slots, out = {}, {}
    multi = len(docs) > 1
    for p in docs:
        for r in p.regions:
            key = p.path if multi else r.sample
            out[id(r)] = slots.setdefault(key, len(slots))
    return out


def stack_colours(slots, cycle, background):
    """Colours for one stack given each trace's slot: the categorical colour,
    or a sequential ramp of one hue when every trace shares a slot (e.g. the
    levels of a depth profile)."""
    if len(slots) > 1 and len(set(slots)) == 1:
        return ramp(cycle[slots[0] % len(cycle)], len(slots), background)
    return [cycle[s % len(cycle)] for s in slots]


def nice_step(x):
    """Round a positive number down to 1, 2 or 5 x 10^n."""
    if not x or x <= 0 or not math.isfinite(x):
        return 1.0
    e = math.floor(math.log10(x))
    m = x / 10 ** e
    for k in (5, 2, 1):
        if m >= k:
            return k * 10 ** e
    return 10 ** e


def dodge(values, gap):
    """Nudge label positions upward so neighbours are at least ``gap`` apart
    (order preserved). Returns the new positions."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = list(values)
    for a, b in zip(order, order[1:]):
        if out[b] - out[a] < gap:
            out[b] = out[a] + gap
    return out


def normalise_name(name):
    """Case/whitespace-insensitive key for a region (element) name."""
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


def regions_under(node):
    """All regions at or below a tree node, in tree order."""
    out = []
    if node.region is not None:
        out.append(node.region)
    for c in node.children:
        out += regions_under(c)
    return out


def tick_state(leaf_ids, checked):
    """Tri-state for a tree node: 0 = none ticked, 1 = some, 2 = all."""
    if not leaf_ids:
        return 0
    k = len(checked.intersection(leaf_ids))
    return 0 if k == 0 else (2 if k == len(leaf_ids) else 1)


def _span(r):
    if r.energy:
        return (min(r.energy[0], r.energy[-1]), max(r.energy[0], r.energy[-1]))
    return None


def _iou(a, b):
    """Intersection-over-union of two (lo, hi) energy spans."""
    inter = min(a[1], b[1]) - max(a[0], b[0])
    if inter <= 0:
        return 0.0
    union = max(a[1], b[1]) - min(a[0], b[0])
    return inter / union if union else 0.0


def group_regions(regions, mode="name"):
    """Group spectra that belong on one stacked panel.

    mode "name":  same element/region name (e.g. every 'C 1s').
    mode "range": x-axis spans that overlap by >= 50 % (intersection over
                  union), whatever the name.
    mode "sample": same element name within one sample (one panel per sample
                  and element, e.g. one depth profile each).
    mode "file":  same element name within one file.
    Returns an ordered list of (label, [regions]); order is first appearance.
    """
    if mode in ("sample", "file"):
        keyed = {}
        for r in regions:
            part = r.sample if mode == "sample" else r.source
            if mode == "file" and part:
                part = os.path.splitext(part)[0]
            keyed.setdefault((normalise_name(r.name), part or ""),
                             (r.name, part or "", []))[2].append(r)
        return [(f"{name} · {part}" if part else name, rs)
                for name, part, rs in keyed.values()]
    if mode == "range":
        groups = []
        for r in regions:
            span = _span(r)
            for g in groups:
                if span and g["span"] and _iou(span, g["span"]) >= 0.5:
                    g["regions"].append(r)
                    break
            else:
                groups.append({"span": span, "regions": [r]})
        out = []
        for g in groups:
            names = {normalise_name(r.name) for r in g["regions"]}
            if len(names) == 1:
                key = g["regions"][0].name
            elif g["span"]:
                key = f"{g['span'][0]:.0f}–{g['span'][1]:.0f} eV"
            else:
                key = "Other"
            out.append((key, g["regions"]))
        return out
    by_name = {}
    for r in regions:
        by_name.setdefault(normalise_name(r.name), (r.name, []))[1].append(r)
    return list(by_name.values())


def _grid_dims(n):
    cols = min(4, max(1, math.ceil(math.sqrt(n))))
    rows = min(4, math.ceil(n / cols))
    return rows, cols


def norm_factor(r, mode, cursor=None):
    """Divisor that normalises spectrum r for the chosen mode."""
    ys = r.counts
    if mode == "Max = 1":
        m = max(ys)
        return m if m else 1.0
    if mode == "Area = 1":
        s = sum(abs(y) for y in ys)
        return s / len(ys) if s else 1.0
    if mode == "At cursor" and cursor is not None:
        v = interp_intensity(r, cursor)
        return v if v and v > 0 else 1.0
    return 1.0


def add_ke_axis(ax, hv, muted, label=True):
    """Mirror a binding-energy axis along the top as kinetic energy
    (KE = hν − BE)."""
    def flip(x):
        return hv - x
    sec = ax.secondary_xaxis("top", functions=(flip, flip))
    sec.spines["top"].set_visible(True)
    sec.spines["top"].set_color(muted)
    sec.tick_params(labelsize=8)
    if label:
        sec.set_xlabel("Kinetic Energy (eV)", fontsize=8, color=muted)
    return sec


def draw_stack(ax, regs, offset=0.6, norm="None", cursor=None, colours=None,
               title="", subtitle="", selected=(), multi_file=False,
               first_col=True, bottom_row=True, accent="#0F6B8C",
               muted="#56636E", scale="Binding", ke_top=False,
               top_row=False):
    """Draw one panel: a single spectrum plain, several stacked by y offset.

    Stacked panels drop the (meaningless) y ticks for a scale bar and label
    each trace at its right-hand end, in the trace colour, with labels nudged
    apart. ``selected`` holds ``id(region)`` of spectra to draw heavier."""
    normed = [[y / norm_factor(r, norm, cursor) for y in r.counts]
              for r in regs]
    n = len(regs)
    stacked = n > 1
    spans = [(max(v) - min(v)) for v in normed if v]
    step = offset * (max(spans) if spans else 1.0) if stacked else 0.0
    r0 = regs[0]
    axes_x = [viewdata.energy_axis(r, scale) for r in regs]
    a0 = axes_x[0]
    binding = a0.invert
    show_name = len({normalise_name(r.name) for r in regs}) > 1
    label_every = max(1, math.ceil(n / 12))
    ends = []
    for i, (r, v) in enumerate(zip(regs, normed)):
        yoff = [y + i * step for y in v]
        col = colours[i] if colours else None
        sel = id(r) in selected
        ax.plot(axes_x[i].x, yoff, color=col,
                lw=1.9 if sel else (0.8 if n > 12 else 1.1),
                zorder=3 if sel else 2)
        if stacked and i % label_every == 0:
            xs = axes_x[i].x
            j = (min if binding else max)(range(len(xs)), key=xs.__getitem__)
            lo, hi = max(0, j - 2), min(len(yoff), j + 3)
            ends.append((sum(yoff[lo:hi]) / (hi - lo),
                         trace_label(r, multi_file, show_name), col))
    if norm == "At cursor" and cursor is not None:
        cx = (r0.photon_energy - cursor
              if a0.label == "Kinetic Energy" else cursor)
        ax.axvline(cx, color=accent, ls="--", lw=0.9)
    ax.margins(x=0.02, y=0.06)
    ax.relim()
    ax.autoscale_view()
    y0, y1 = ax.get_ylim()
    yspan = (y1 - y0) or 1.0
    yaxis_tf = ax.get_yaxis_transform()          # x: axes fraction, y: data
    if stacked:
        ax.set_yticks([])
        ax.spines["left"].set_visible(False)
        # scale bar to the left of the axes replaces the y axis
        bar = nice_step(yspan * 0.22)
        base = y0 + yspan * 0.06
        ax.plot([-0.018, -0.018], [base, base + bar], transform=yaxis_tf,
                color=muted, lw=1.6, solid_capstyle="butt", clip_on=False)
        unit = "" if norm != "None" else f" {r0.count_units}"
        ax.text(-0.03, base + bar / 2,
                (f"{bar:,.0f}" if bar >= 1 else f"{bar:g}") + unit,
                transform=yaxis_tf, rotation=90, ha="right", va="center",
                fontsize=8, color=muted, clip_on=False)
        pos = dodge([e[0] for e in ends], 0.062 * yspan)
        for (_y, text, col), yy in zip(ends, pos):
            t = ax.text(1.012, yy, text, transform=yaxis_tf, color=col,
                        fontsize=8, va="center", ha="left", clip_on=False)
            t.set_in_layout(False)      # the page reserves the gutter itself
    ax.set_title(title, loc="left")
    if subtitle:
        ax.set_title(subtitle, loc="right", fontsize=8, fontweight="normal",
                     color=muted)
    if bottom_row:
        ax.set_xlabel(f"{a0.label.capitalize()} ({a0.units})")
    if first_col and not stacked:
        ax.set_ylabel(f"{r0.count_label} ({r0.count_units})" if norm == "None"
                      else f"{r0.count_label} (normalised)")
    if binding:
        ax.invert_xaxis()
    if ke_top and binding and top_row and viewdata.photon_energy(regs):
        add_ke_axis(ax, viewdata.photon_energy(regs), muted)


def _titles(ax, title, subtitle, muted):
    ax.set_title(title, loc="left")
    if subtitle:
        ax.set_title(subtitle, loc="right", fontsize=8, fontweight="normal",
                     color=muted)


def draw_heatmap(fig, ax, regs, zi, norm="None", cmap=None, title="",
                 subtitle="", first_col=True, bottom_row=True, top_row=False,
                 muted="#56636E", scale="Binding", ke_top=False):
    """One panel as a heat map: energy across, ``zi`` (etch time / level,
    acquisition time or trace order, ascending downwards) down, intensity as
    colour. ``regs`` must already be in z order (see viewdata.z_sorted)."""
    import numpy as np
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.ticker import MaxNLocator
    axes_x = [viewdata.energy_axis(r, scale) for r in regs]
    a0, r0 = axes_x[0], regs[0]
    ys = [[y / norm_factor(r, norm) for y in r.counts] for r in regs]
    grid, rows = viewdata.build_matrix([a.x for a in axes_x], ys)
    if cmap is None:
        cmap = LinearSegmentedColormap.from_list("heat", ["#FFFFFF", "#000000"])
    cmap = cmap.with_extremes(bad=(0, 0, 0, 0))   # outside a trace's range
    mesh = ax.pcolormesh(viewdata.edges(list(grid)),
                         viewdata.edges(list(zi.values)),
                         np.ma.masked_invalid(rows), cmap=cmap,
                         shading="flat", rasterized=True)
    ax.set_xlim(grid[0], grid[-1])
    ax.set_ylim(max(viewdata.edges(list(zi.values))),
                min(viewdata.edges(list(zi.values))))     # first trace on top
    if a0.invert:
        ax.invert_xaxis()
    if len(regs) == 1:
        ax.set_yticks([zi.values[0]])
    elif zi.mode in ("Trace order", "Etch level"):
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_ylabel(zi.label)
    _titles(ax, title, subtitle, muted)
    if bottom_row:
        ax.set_xlabel(f"{a0.label.capitalize()} ({a0.units})")
    cb = fig.colorbar(mesh, ax=ax, pad=0.02, fraction=0.05, aspect=24)
    cb.outline.set_visible(False)
    cb.ax.tick_params(labelsize=7, length=2)
    cb.set_label("Normalised" if norm != "None"
                 else f"{r0.count_label} ({r0.count_units})", fontsize=8)
    if ke_top and a0.invert and top_row and viewdata.photon_energy(regs):
        add_ke_axis(ax, viewdata.photon_energy(regs), muted)
    return mesh


def draw_waterfall3d(ax, regs, zi, norm="None", colours=None, title="",
                     subtitle="", pal=None, scale="Binding"):
    """One panel as a 3-D waterfall: energy (x), trace z (y), intensity
    (vertical). ``ax`` must be a 3-D axes; ``regs`` in z order."""
    from matplotlib.collections import PolyCollection
    from matplotlib.colors import to_rgba
    pal = pal or themes.PALETTES[themes.DEFAULT]
    axes_x = [viewdata.energy_axis(r, scale) for r in regs]
    a0, r0 = axes_x[0], regs[0]
    ys = [[y / norm_factor(r, norm) for y in r.counts] for r in regs]
    floor = min(min(v) for v in ys if v)
    n = len(regs)
    for i, (a, v, z) in enumerate(zip(axes_x, ys, zi.values)):
        col = colours[i] if colours else None
        verts = [(a.x[0], floor)] + list(zip(a.x, v)) + [(a.x[-1], floor)]
        ax.add_collection3d(
            PolyCollection([verts], facecolors=[to_rgba(col or "#888", 0.10)],
                           edgecolors="none"), zs=z, zdir="y")
        ax.plot(a.x, [z] * len(a.x), v, color=col,
                lw=0.8 if n > 12 else 1.1)
    xs = [x for a in axes_x for x in a.x]
    ax.set_xlim(min(xs), max(xs))
    zlo, zhi = min(zi.values), max(zi.values)
    pad = 0.5 if zhi == zlo else 0.0
    ax.set_ylim(zlo - pad, zhi + pad)
    ax.set_zlim(floor, max(max(v) for v in ys if v))
    if a0.invert:
        ax.invert_xaxis()
    _titles(ax, title, subtitle, pal["muted"])
    ax.set_xlabel(f"{a0.label.capitalize()} ({a0.units})", labelpad=2)
    ax.set_ylabel(zi.label, labelpad=2)
    ax.text2D(0.0, 0.9, "Normalised" if norm != "None"
              else f"{r0.count_label} ({r0.count_units})",
              transform=ax.transAxes, fontsize=8, color=pal["muted"])
    ax.tick_params(labelsize=7, pad=0)
    ax.view_init(elev=24, azim=-58)
    try:                                   # fill the panel (matplotlib >= 3.3)
        ax.set_box_aspect((1.5, 1.0, 0.75), zoom=1.1)
    except Exception:
        pass
    for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        try:
            axis.set_pane_color(to_rgba(pal["plot_bg"], 0.0))
            axis.label.set_color(pal["plot_fg"])
            axis._axinfo["grid"]["color"] = to_rgba(pal["plot_grid"])
            axis._axinfo["axisline"]["color"] = to_rgba(pal["muted"])
        except Exception:
            pass
    ax.tick_params(colors=pal["muted"])


class CalibrationPanel(ttk.LabelFrame):
    """Inline camera-to-stage calibration form (lives in the Images tab)."""

    def __init__(self, master, on_save, on_close, current=None):
        super().__init__(master, text="Camera calibration", padding=8)
        self.on_save = on_save
        self.on_close = on_close
        c = current or {"centre_x_mm": 0.0, "centre_y_mm": 0.0,
                        "mm_per_px": 0.02, "flip_x": False, "flip_y": False,
                        "rotation_deg": 0.0}
        ttk.Label(self, wraplength=230, justify="left", font=("", 8),
                  text="Maps stage coordinates (mm) onto the holder photo. "
                       "Centre X/Y = stage position at the photo centre; "
                       "mm per pixel = image width in mm ÷ pixel width. "
                       "Flip/rotate until the markers land on the samples."
                  ).grid(row=0, column=0, columnspan=2, sticky="w",
                         pady=(0, 6))
        self.vars = {}
        r = 1
        for label, key in [("Centre X (mm)", "centre_x_mm"),
                           ("Centre Y (mm)", "centre_y_mm"),
                           ("mm per pixel", "mm_per_px"),
                           ("Rotation (deg)", "rotation_deg")]:
            ttk.Label(self, text=label).grid(row=r, column=0, sticky="e",
                                             padx=(0, 6), pady=2)
            v = tk.StringVar(value=str(c.get(key, 0.0)))
            ttk.Entry(self, textvariable=v, width=10).grid(row=r, column=1,
                                                           sticky="w")
            self.vars[key] = v
            r += 1
        self.flip_x = tk.BooleanVar(value=c.get("flip_x", False))
        self.flip_y = tk.BooleanVar(value=c.get("flip_y", False))
        ttk.Checkbutton(self, text="Flip X", variable=self.flip_x).grid(
            row=r, column=0, sticky="w")
        ttk.Checkbutton(self, text="Flip Y", variable=self.flip_y).grid(
            row=r, column=1, sticky="w")
        r += 1
        btns = ttk.Frame(self)
        btns.grid(row=r, column=0, columnspan=2, pady=(8, 0))
        ttk.Button(btns, text="Apply", command=self._save).pack(side="left",
                                                               padx=4)
        ttk.Button(btns, text="Close", command=on_close).pack(side="left")

    def _save(self):
        try:
            calib = {k: float(v.get()) for k, v in self.vars.items()}
            calib["flip_x"] = self.flip_x.get()
            calib["flip_y"] = self.flip_y.get()
            if calib["mm_per_px"] == 0:
                raise ValueError("mm per pixel cannot be zero.")
        except ValueError as exc:
            messagebox.showerror("Invalid calibration", str(exc))
            return
        save_calibration(calib)
        self.on_save(calib)


class Tooltip:
    """Small hover hint for a widget (Tk has none built in). Coloured from the
    live theme via ``palette_fn``; shown after a short pause, hidden on leave,
    click or key."""

    def __init__(self, widget, text, palette_fn, delay=550):
        self.widget, self.text, self.palette_fn = widget, text, palette_fn
        self.delay, self._job, self._tip = delay, None, None
        widget.bind("<Enter>", self._arm, add="+")
        for ev in ("<Leave>", "<ButtonPress>", "<KeyPress>"):
            widget.bind(ev, self._hide, add="+")

    def _arm(self, _e=None):
        self._hide()
        self._job = self.widget.after(self.delay, self._show)

    def _show(self):
        self._job = None
        p = self.palette_fn()
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.configure(bg=p["border"])
        tk.Label(tip, text=self.text, justify="left", padx=8, pady=4,
                 bg=p["panel"], fg=p["fg"], wraplength=300).pack(padx=1, pady=1)
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        tip.wm_geometry(f"+{x}+{y}")
        self._tip = tip

    def _hide(self, _e=None):
        if self._job is not None:
            self.widget.after_cancel(self._job)
            self._job = None
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


class Workspace:
    """The single main window: file tree with tick boxes (left), stacked-plot
    area (top right) and a Metadata / Images / Stage-map notebook (bottom
    right). Ticked spectra are plotted; spectra sharing an element name (or
    x-range) are stacked with a y offset on one panel."""

    PANEL_CHOICES = ["Auto", "1", "2", "4", "6", "9", "12", "16"]
    TRACE_CHOICES = ["All", "3", "5", "10", "20", "50", "100"]
    NORM_MODES = ["None", "Max = 1", "Area = 1", "At cursor"]
    GROUP_MODES = {"Element name": "name", "Energy range": "range",
                   "Element, per sample": "sample",
                   "Element, per file": "file"}
    VIEW_MODES = ["Stack", "Waterfall 3D", "Heatmap"]

    def __init__(self, root):
        self.root = root
        root.title("ESCApe Explorer")
        self.cfg = load_config()
        h = min(780, max(560, root.winfo_screenheight() - 140))
        w = min(1400, max(1000, root.winfo_screenwidth() - 40))
        root.geometry(self.cfg.get("geometry") or f"{w}x{h}")
        root.minsize(900, 560)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.font_family = fonts.apply_tk_fonts(root)
        tkfont.Font(root=root, name="AppSection", family=self.font_family,
                    size=fonts.SIZE["section"], weight="bold")
        if HAVE_MPL:
            themes.MPL_FAMILY = fonts.register_matplotlib()
        self.themes = ThemeManager(root)
        ax_choice = self.cfg.get("axis_colour", "Theme default")
        self.axis_choice = (ax_choice if ax_choice in themes.AXIS_CHOICES
                            else "Theme default")
        self.axis_custom = self.cfg.get("axis_colour_custom")
        self.theme_name = self.cfg.get("theme", "Light")
        if self.theme_name not in THEME_NAMES:
            self.theme_name = "Light"
        self.palette = self.themes.apply(self.theme_name)
        self._apply_mpl_theme()

        self.docs = []              # loaded SpectrumFile readers
        self.node_map = {}          # tree iid -> (parser, TreeNode)
        self.leaf_ids = {}          # tree iid -> frozenset(id(region)) it holds
        self.box_state = {}         # tree iid -> last drawn tick state
        self.region_parser = {}     # id(region) -> owning parser
        self.checked = set()        # id(region) of ticked spectra
        self.sel_regions = []       # regions under the highlighted rows
        self.panel_start = 0        # first visible panel (row-aligned)
        self.trace_start = 0        # first visible trace of long stacks
        self._scale_guard = False
        self.cursors = {}           # group key -> "At cursor" energy
        self.calib = load_calibration()
        self._open = {}             # id(node) -> expanded?
        self._render_job = None
        self._axmap = {}
        self._axhv = {}
        self._view_notes = []
        self._thumb_imgs = []
        self._view_photo = None
        self._cur_image = None
        self.swatches = SwatchCache(self.palette)
        self.blank_img = self.swatches.blank
        self.trace_color = {}       # id(region) -> colour used on the plot
        self.color_slot = {}        # id(region) -> stable palette slot
        self.leaf_region = {}       # tree iid -> its Region (leaf rows)
        # experiment workbook (.xpscontainer) session
        self.details = {k: "" for k in wbk.DETAIL_FIELDS}
        self.logo = ""              # letterhead image (local path)
        self.figures = []           # [{id, name, caption, state}]
        self.wb_path = None         # file the workbook was opened from/saved to
        self.wb_dir = None          # temp folder holding an opened workbook
        self.wb_extra = {}          # unknown manifest keys, kept on re-save
        self.wb_created = ""
        self._wb_sig = None         # signature at the last save / open
        self.file_ids = {}          # id(parser) -> workbook file id
        self.file_origin = {}       # id(parser) -> path it was first added from
        self._fid_used = set()      # file ids handed out this session
        self._sha_cache = {}

        self._build_menu()
        self._build_body()
        self.set_theme(self.theme_name, save=False)
        root.after(80, self._restore_layout)

    # -- construction ---------------------------------------------------
    def _build_menu(self):
        bar = tk.Menu(self.root)
        filem = tk.Menu(bar, tearoff=0)
        self.themes.register_menu(bar)
        self.themes.register_menu(filem)
        filem.add_command(label="Open spectra file(s)…",
                          command=self.open_files)
        filem.add_command(label="Open folder…", command=self.open_folder)
        filem.add_command(label="Close all files", command=self.close_all)
        filem.add_command(label="Ask about .avg / .vgd duplicates again",
                          command=self._forget_dup_choice)
        filem.add_separator()
        filem.add_command(label="Export ticked spectra → CSV…",
                          command=lambda: self.export_ticked("csv"))
        filem.add_command(label="Export ticked spectra → VAMAS…",
                          command=lambda: self.export_ticked("vamas"))
        filem.add_command(label="Export spectra (choose regions/levels)…",
                          command=self.open_export)
        filem.add_separator()
        filem.add_command(label="Export metadata → CSV…",
                          command=self.export_meta_csv)
        filem.add_command(label="Export metadata → PDF…",
                          command=self.export_meta_pdf)
        filem.add_separator()
        filem.add_command(label="Preview spectra PDF…",
                          command=self.preview_spectra)
        filem.add_command(label="Preview metadata PDF…",
                          command=self.preview_metadata)
        filem.add_separator()
        filem.add_command(label="Quit", command=self._on_close)
        bar.add_cascade(label="File", menu=filem)
        wbm = tk.Menu(bar, tearoff=0)
        self.themes.register_menu(wbm)
        wbm.add_command(label="New workbook", command=self.new_workbook)
        wbm.add_command(label="Open workbook…", command=self.open_workbook)
        wbm.add_command(label="Save workbook   (Ctrl+S)",
                        command=self.save_workbook)
        wbm.add_command(label="Save workbook as…",
                        command=lambda: self.save_workbook(as_new=True))
        wbm.add_separator()
        wbm.add_command(label="Details and notes…", command=self.edit_details)
        wbm.add_command(label="Figures…", command=self.edit_figures)
        wbm.add_separator()
        wbm.add_command(label="Experiment report — preview…",
                        command=self.preview_report)
        wbm.add_command(label="Experiment report — save PDF…",
                        command=self.save_report)
        wbm.add_command(label="Export PowerPoint…",
                        command=self.export_powerpoint)
        bar.add_cascade(label="Workbook", menu=wbm)
        viewm = tk.Menu(bar, tearoff=0)
        self.themes.register_menu(viewm)
        viewm.add_command(label="Expand all", command=lambda: self._expand(True))
        viewm.add_command(label="Collapse all",
                          command=lambda: self._expand(False))
        viewm.add_command(label="Untick all", command=self.untick_all)
        viewm.add_separator()
        viewm.add_command(label="Show/hide file tree",
                          command=lambda: self._toggle_pane("tree"))
        viewm.add_command(label="Show/hide info column",
                          command=lambda: self._toggle_pane("info"))
        viewm.add_command(label="Focus plot   (F11)", command=self.toggle_focus)
        viewm.add_separator()
        themem = tk.Menu(viewm, tearoff=0)
        self.themes.register_menu(themem)
        self.theme_var = tk.StringVar(value=self.theme_name)
        for name in THEME_NAMES:
            themem.add_radiobutton(label=name, value=name,
                                   variable=self.theme_var,
                                   command=lambda n=name: self.set_theme(n))
        viewm.add_cascade(label="Colour theme", menu=themem)
        bar.add_cascade(label="View", menu=viewm)
        self.view_menu = viewm
        self.menubar = bar
        self.root.config(menu=bar)

    def _build_body(self):
        self.status = ttk.Label(self.root, anchor="w", style="Status.TLabel",
                                text="No files loaded. Use Open to add spectra.")
        self.status.pack(side="bottom", fill="x")
        ttk.Separator(self.root).pack(side="bottom", fill="x")
        self._build_toolbar()

        self.outer = ttk.PanedWindow(self.root, orient="horizontal")
        self.outer.pack(fill="both", expand=True)
        self.tree_pane = ttk.Frame(self.outer)
        self.center = ttk.Frame(self.outer)
        self.center.grid_rowconfigure(0, weight=1)
        self.center.grid_columnconfigure(0, weight=1)
        self.plot_pane = ttk.Frame(self.center)
        self.plot_pane.grid(row=0, column=0, sticky="nsew")
        self.preview = PdfPreview(self.center, on_close=self.close_preview)
        self.preview.grid(row=0, column=0, sticky="nsew")
        self.preview.grid_remove()
        self._pdf_dir = None
        self.info_pane = ttk.PanedWindow(self.outer, orient="vertical")
        self.outer.add(self.tree_pane, weight=0)
        self.outer.add(self.center, weight=1)
        self.outer.add(self.info_pane, weight=0)

        self._build_tree_pane(self.tree_pane)
        self._build_plot_pane(self.plot_pane)
        self.meta_frame = ttk.Frame(self.info_pane)
        self.nb = ttk.Notebook(self.info_pane)
        self.info_pane.add(self.meta_frame, weight=3)
        self.info_pane.add(self.nb, weight=2)
        self._build_meta_table(self.meta_frame)
        self._build_side_tabs()
        self._panes = {"tree": self.tree_pane, "info": self.info_pane}
        self._hidden = {}           # pane name -> width when hidden
        self._restore_widths = {}   # pane name -> width to re-apply once shown
        self.root.bind("<F11>", lambda e: self.toggle_focus())
        self.root.bind("<Control-s>", lambda e: self.save_workbook())

    def _build_toolbar(self):
        tb = ttk.Frame(self.root)
        tb.pack(side="top", fill="x", padx=8, pady=(6, 4))

        def menubutton(text, items):
            btn = ttk.Button(tb, text=f"{text} ▾", style="Tool.TButton")
            m = tk.Menu(btn, tearoff=0)
            for it in items:
                if it is None:
                    m.add_separator()
                else:
                    m.add_command(label=it[0], command=it[1])

            def drop():
                try:
                    m.tk_popup(btn.winfo_rootx(),
                               btn.winfo_rooty() + btn.winfo_height())
                finally:
                    m.grab_release()
            btn.configure(command=drop)
            btn.pack(side="left", padx=(0, 2))
            self.themes.register_menu(m)

        menubutton("Open", [("Spectra files…", self.open_files),
                            ("Folder…", self.open_folder), None,
                            ("Close all files", self.close_all)])
        menubutton("Export", [
            ("Ticked spectra to CSV…", lambda: self.export_ticked("csv")),
            ("Ticked spectra to VAMAS…", lambda: self.export_ticked("vamas")),
            ("Regions and levels…", self.open_export), None,
            ("Metadata to CSV…", self.export_meta_csv),
            ("Metadata to PDF…", self.export_meta_pdf)])
        menubutton("PDF", [("Preview spectra", self.preview_spectra),
                           ("Save spectra as PDF…", self.save_pdf), None,
                           ("Preview metadata", self.preview_metadata),
                           ("Save metadata as PDF…", self.export_meta_pdf)])

        right = ttk.Frame(tb)
        right.pack(side="right")
        self.show_vars = {"tree": tk.BooleanVar(value=True),
                          "info": tk.BooleanVar(value=True)}
        focus = ttk.Button(right, text="Focus", style="Tool.TButton",
                           command=self.toggle_focus)
        focus.pack(side="right", padx=(2, 0))
        Tooltip(focus, "Hide the file tree and details so the plot fills the "
                       "window (F11).", lambda: self.palette)
        for key, text, tip in (("info", "Details",
                                "Show or hide the details column."),
                               ("tree", "Files",
                                "Show or hide the file tree.")):
            cb = ttk.Checkbutton(right, text=text, style="Toolbutton",
                                 variable=self.show_vars[key],
                                 command=lambda k=key: self._toggle_pane(k))
            cb.pack(side="right", padx=(2, 0))
            Tooltip(cb, tip, lambda: self.palette)
        tcb = ttk.Combobox(right, width=14, state="readonly",
                           values=THEME_NAMES, textvariable=self.theme_var)
        tcb.pack(side="right", padx=(0, 12))
        tcb.bind("<<ComboboxSelected>>",
                 lambda e: self.set_theme(self.theme_var.get()))
        ttk.Label(right, text="Theme", style="Muted.TLabel").pack(
            side="right", padx=(12, 6))

    # -- theme --------------------------------------------------------------
    def _plot_palette(self, pal=None, paper=False):
        """``(palette, note)`` for drawing: the theme (or ``pal``) with the
        chosen axis colour applied. On paper (PDF) "White" is ignored."""
        pal = pal or self.palette
        if paper and self.axis_choice == "White":
            return pal, ""
        return themes.with_axis_colour(pal, self.axis_choice,
                                       self.axis_custom)

    def _apply_mpl_theme(self):
        if HAVE_MPL:
            matplotlib.rcParams.update(mpl_rc(self._plot_palette()[0]))

    def set_theme(self, name, save=True):
        """Switch the colour theme live (widgets, tick boxes, plots)."""
        if name not in THEME_NAMES:
            return
        self.theme_name = name
        self.theme_var.set(name)
        self.palette = self.themes.apply(name)
        self._apply_mpl_theme()
        self._restyle_details()
        self.swatches = SwatchCache(self.palette)
        self.blank_img = self.swatches.blank
        self.box_state.clear()
        self._populate_tree()
        if HAVE_MPL:
            self.fig.set_facecolor(self.palette["plot_bg"])
            self.canvas.get_tk_widget().configure(bg=self.palette["plot_bg"])
            self._make_toolbar()
        self._render()
        self._redraw_viewer()
        if save:
            self.cfg["theme"] = name

    def _menu(self, parent):
        """A popup menu coloured for the current theme."""
        m = tk.Menu(parent, tearoff=0)
        self.themes.register_menu(m)
        self.themes.recolor_tk(self.root)
        return m

    # -- panes: collapse / focus / remembered sizes ----------------------
    def _toggle_pane(self, name):
        pane = self._panes[name]
        if name in self._hidden:                     # show again
            width = self._hidden.pop(name)
            if name == "tree":
                self.outer.insert(0, pane, weight=0)
            else:
                self.outer.add(pane, weight=0)
            self._restore_widths[name] = width
            self.root.after_idle(self._apply_widths)
        else:                                        # hide
            self._hidden[name] = max(150, pane.winfo_width())
            self.outer.forget(pane)
        self.show_vars[name].set(name not in self._hidden)

    def _apply_widths(self, retry=True):
        """Put re-shown panes back at their old widths in one pass (tree
        first, then info) once the paned window has laid the panes out."""
        if not self._restore_widths:
            return
        try:
            self.outer.update_idletasks()
            total = self.outer.winfo_width()
            n = len(self.outer.panes())
            if "tree" in self._restore_widths:
                self.outer.sashpos(0, self._restore_widths["tree"])
            if "info" in self._restore_widths:
                self.outer.sashpos(n - 2, total - self._restore_widths["info"])
        except tk.TclError:
            pass
        if retry:                    # layout may still be settling; apply again
            self.root.after(60, lambda: self._apply_widths(False))
        else:
            self._restore_widths.clear()

    def toggle_focus(self):
        """Hide tree + info column so the plot fills the window (and back)."""
        if self._hidden:
            for name in list(self._hidden):
                self._toggle_pane(name)
        else:
            for name in ("tree", "info"):
                self._toggle_pane(name)

    def _restore_layout(self):
        cfg = self.cfg
        try:
            self.outer.update_idletasks()
            total = self.outer.winfo_width()
            tree_w = int(cfg.get("sash_tree", 0)) or 0
            info_w = int(cfg.get("sash_info", 0)) or 0
            if not tree_w:
                tree_w = 430 if total >= 1300 else 340
            if not info_w:
                info_w = 380 if total >= 1300 else 300
            self.outer.sashpos(0, tree_w)
            self.outer.sashpos(1, total - info_w)
            h = self.info_pane.winfo_height()
            if h > 100:
                self.info_pane.sashpos(0, int(cfg.get("sash_info_v", 0)) or
                                       int(h * 0.64))
        except tk.TclError:
            pass

    def _on_close(self):
        if not self._confirm_discard():
            return
        self._drop_wb_dir()
        cfg = self.cfg
        try:
            cfg["geometry"] = self.root.winfo_geometry()
            visible = not self._hidden
            if visible:
                cfg["sash_tree"] = self.outer.sashpos(0)
                cfg["sash_info"] = (self.outer.winfo_width()
                                    - self.outer.sashpos(1))
                cfg["sash_info_v"] = self.info_pane.sashpos(0)
        except tk.TclError:
            pass
        self.preview.close_document()
        if self._pdf_dir:
            shutil.rmtree(self._pdf_dir, ignore_errors=True)
        cfg["colour_scale"] = self.colscale_var.get()
        cfg["colour_reverse"] = bool(self.colrev_var.get())
        cfg["axis_colour"] = self.axis_choice
        cfg["axis_colour_custom"] = self.axis_custom
        cfg["view_mode"] = self.view_var.get()
        cfg["energy_scale"] = self.scale_var.get()
        cfg["ke_top"] = bool(self.ke_var.get())
        cfg["z_axis"] = self.z_var.get()
        cfg["group_by"] = self.group_var.get()
        cfg["norm"] = self.norm_var.get()
        cfg["offset"] = float(self.offset_var.get())
        cfg["panels_per_page"] = self.panels_var.get()
        cfg["traces_per_panel"] = self.traces_var.get()
        save_config(cfg)
        self.root.quit()

    def _build_tree_pane(self, parent):
        top = ttk.Frame(parent)
        top.pack(side="top", fill="x", padx=10, pady=(8, 2))
        ttk.Label(top, text="Files", style="Section.TLabel").pack(side="left")
        for text, cmd in (("Clear ticks", self.untick_all),
                          ("Collapse", lambda: self._expand(False)),
                          ("Expand", lambda: self._expand(True))):
            ttk.Button(top, text=text, style="Tool.TButton",
                       command=cmd).pack(side="right")

        fb = ttk.Frame(parent)
        fb.pack(side="top", fill="x", padx=10, pady=(2, 6))
        ttk.Label(fb, text="Filter").pack(side="left")
        self.filter_var = tk.StringVar()
        ent = ttk.Entry(fb, textvariable=self.filter_var)
        ent.pack(side="left", fill="x", expand=True, padx=(6, 4))
        ent.bind("<KeyRelease>", lambda e: self._populate_tree())
        ttk.Button(fb, text="Clear", style="Tool.TButton",
                   command=lambda: (self.filter_var.set(""),
                                    self._populate_tree())).pack(side="left")

        holder = ttk.Frame(parent)
        holder.pack(side="top", fill="both", expand=True)
        cols = ("detail", "pts", "pe", "etch")
        self.tree = ttk.Treeview(holder, columns=cols,
                                 show="tree headings", selectmode="extended")
        self.tree.heading("#0", text="Name", anchor="w")
        self.tree.heading("detail", text="Range", anchor="w")
        self.tree.heading("pts", text="Points", anchor="e")
        self.tree.heading("pe", text="Pass (eV)", anchor="e")
        self.tree.heading("etch", text="Etch", anchor="e")
        self.tree.column("#0", width=230, stretch=True, minwidth=140)
        self.tree.column("detail", width=104, anchor="w", stretch=False)
        self.tree.column("pts", width=52, anchor="e", stretch=False)
        self.tree.column("pe", width=66, anchor="e", stretch=False)
        self.tree.column("etch", width=56, anchor="e", stretch=False)
        sb = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", expand=True, fill="both")
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<space>", self._on_tree_space)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<<TreeviewOpen>>", lambda e: self._note_open(True))
        self.tree.bind("<<TreeviewClose>>", lambda e: self._note_open(False))
        self.tree.bind("<Button-3>", self._context_menu)   # right-click
        self.tree.bind("<Button-2>", self._context_menu)   # mac right-click

    def _build_plot_pane(self, parent):
        cfg = self.cfg
        tip = lambda w, t: Tooltip(w, t, lambda: self.palette)      # noqa: E731
        # one view row: how spectra are combined
        ctl = ttk.Frame(parent)
        ctl.pack(side="top", fill="x", padx=10, pady=(8, 2))
        ttk.Label(ctl, text="Group by").pack(side="left")
        self.group_var = tk.StringVar(value=cfg.get("group_by", "Element name"))
        gb = ttk.Combobox(ctl, textvariable=self.group_var, width=17,
                          state="readonly", values=list(self.GROUP_MODES))
        gb.pack(side="left", padx=(6, 12))
        gb.bind("<<ComboboxSelected>>",
                lambda e: self._schedule_render(reset_page=True))
        tip(gb, "Which spectra share a panel: the same element name, "
                "overlapping energy ranges, or the same element within one "
                "sample / file (one depth or time series each).")

        ttk.Label(ctl, text="Normalise").pack(side="left")
        self.norm_var = tk.StringVar(value=cfg.get("norm", "None"))
        nb = ttk.Combobox(ctl, textvariable=self.norm_var, width=9,
                          state="readonly", values=self.NORM_MODES)
        nb.pack(side="left", padx=(6, 12))
        nb.bind("<<ComboboxSelected>>", lambda e: self._schedule_render())
        tip(nb, "Scale every spectrum: to its maximum, its area, or to match "
                "at an energy you click on the plot.")

        ttk.Label(ctl, text="Offset").pack(side="left")
        self.offset_var = tk.DoubleVar(value=float(cfg.get("offset", 0.6)))
        self.offset_lbl = ttk.Label(ctl, text="", width=4,
                                    style="Muted.TLabel")
        sc = ttk.Scale(ctl, from_=0.0, to=3.0, variable=self.offset_var,
                       orient="horizontal", length=72,
                       command=self._on_offset)
        sc.pack(side="left", padx=(6, 2))
        self.offset_lbl.pack(side="left", padx=(0, 10))
        tip(sc, "Vertical gap between stacked spectra. 0 overlays them.")
        self.offset_lbl.config(text=f"{self.offset_var.get():.1f}×")
        self.offset_sc = sc

        # second view row: how the traces are drawn, and the axes
        ctl2 = ttk.Frame(parent)
        ctl2.pack(side="top", fill="x", padx=10, pady=(0, 2))
        ttk.Label(ctl2, text="View").pack(side="left")
        view = cfg.get("view_mode", "Stack")
        self.view_var = tk.StringVar(
            value=view if view in self.VIEW_MODES else "Stack")
        vb = ttk.Combobox(ctl2, textvariable=self.view_var, width=12,
                          state="readonly", values=self.VIEW_MODES)
        vb.pack(side="left", padx=(6, 12))
        vb.bind("<<ComboboxSelected>>", lambda e: self._on_view_changed())
        tip(vb, "Stack: offset traces. Waterfall 3D: energy, trace and "
                "intensity in a rotatable 3-D plot. Heatmap: intensity as "
                "colour against energy and trace.")

        ttk.Label(ctl2, text="Energy").pack(side="left")
        scale = cfg.get("energy_scale", "Binding")
        self.scale_var = tk.StringVar(
            value=scale if scale in viewdata.ENERGY_SCALES else "Binding")
        eb = ttk.Combobox(ctl2, textvariable=self.scale_var, width=8,
                          state="readonly", values=list(viewdata.ENERGY_SCALES))
        eb.pack(side="left", padx=(6, 8))
        eb.bind("<<ComboboxSelected>>", lambda e: self._on_view_changed())
        tip(eb, "Plot against binding energy or kinetic energy "
                "(KE = photon energy − BE). Needs the photon energy.")
        self.ke_var = tk.BooleanVar(value=bool(cfg.get("ke_top", False)))
        self.ke_cb = ttk.Checkbutton(ctl2, text="KE top axis",
                                     variable=self.ke_var,
                                     command=self._on_view_changed)
        self.ke_cb.pack(side="left", padx=(0, 12))
        tip(self.ke_cb, "Mirror the binding-energy axis along the top as "
                        "kinetic energy.")

        ttk.Label(ctl2, text="Z axis").pack(side="left")
        z = cfg.get("z_axis", "Auto")
        self.z_var = tk.StringVar(
            value=z if z in viewdata.Z_MODES else "Auto")
        self.z_cb = ttk.Combobox(ctl2, textvariable=self.z_var, width=15,
                                 state="readonly",
                                 values=list(viewdata.Z_MODES))
        self.z_cb.pack(side="left", padx=(6, 0))
        self.z_cb.bind("<<ComboboxSelected>>",
                       lambda e: self._on_view_changed())
        tip(self.z_cb, "What the third axis of a waterfall / heatmap shows. "
                       "Auto uses etch time, then level, then acquisition "
                       "time, then trace order.")
        self._sync_view_controls()

        # third view row: colours
        ctl3 = ttk.Frame(parent)
        ctl3.pack(side="top", fill="x", padx=10, pady=(0, 2))
        ttk.Label(ctl3, text="Colour").pack(side="left")
        sc_name = cfg.get("colour_scale", "Theme default")
        self.colscale_var = tk.StringVar(
            value=sc_name if sc_name in themes.SCALE_NAMES
            else "Theme default")
        cb = ttk.Combobox(ctl3, textvariable=self.colscale_var, width=13,
                          state="readonly", values=themes.SCALE_NAMES)
        cb.pack(side="left", padx=(6, 6))
        cb.bind("<<ComboboxSelected>>", lambda e: self._schedule_render())
        tip(cb, "Colour scale for the heatmap and for the traces of a stack "
                "or waterfall (spread along the series). Theme default keeps "
                "the colours of the current theme.")
        self.colrev_var = tk.BooleanVar(value=bool(cfg.get("colour_reverse")))
        rev = ttk.Checkbutton(ctl3, text="Reverse", variable=self.colrev_var,
                              command=self._schedule_render)
        rev.pack(side="left", padx=(0, 12))
        tip(rev, "Flip the colour scale.")
        ttk.Label(ctl3, text="Axes").pack(side="left")
        self.axis_var = tk.StringVar(value=self.axis_choice)
        ab = ttk.Combobox(ctl3, textvariable=self.axis_var, width=13,
                          state="readonly", values=themes.AXIS_CHOICES)
        ab.pack(side="left", padx=(6, 0))
        ab.bind("<<ComboboxSelected>>", lambda e: self._on_axis_changed())
        tip(ab, "Colour of the axis lines, ticks and labels. Black or white "
                "are ignored where they would be hard to see.")

        # canvas + toolbar + contextual footer (bottom widgets are packed in
        # _layout_bottom so they can be shown and hidden in order)
        self.fig = self.canvas = self.toolbar = None
        self._trace_bar_on = False
        self._sb_on = False
        self.footer = ttk.Frame(parent)
        ttk.Label(self.footer, text="Panels").pack(side="left")
        self.panels_var = tk.StringVar(value=cfg.get("panels_per_page", "Auto"))
        pb = ttk.Combobox(self.footer, textvariable=self.panels_var, width=5,
                          state="readonly", values=self.PANEL_CHOICES)
        pb.pack(side="left", padx=(6, 14))
        pb.bind("<<ComboboxSelected>>",
                lambda e: self._schedule_render(reset_page=True))
        tip(pb, "How many panels to show at once. The mouse wheel scrolls "
                "through the rest.")
        ttk.Label(self.footer, text="Traces").pack(side="left")
        self.traces_var = tk.StringVar(value=cfg.get("traces_per_panel", "All"))
        tbx = ttk.Combobox(self.footer, textvariable=self.traces_var, width=5,
                           values=self.TRACE_CHOICES)
        tbx.pack(side="left", padx=(6, 14))
        tbx.bind("<<ComboboxSelected>>", lambda e: self._on_traces_changed())
        tbx.bind("<Return>", lambda e: self._on_traces_changed())
        tbx.bind("<FocusOut>", lambda e: self._on_traces_changed())
        tip(tbx, "Show only this many spectra per stack (type your own "
                 "number). Shift + mouse wheel scrolls through the rest.")
        self.reverse = tk.BooleanVar(value=False)
        rv = ttk.Checkbutton(self.footer, text="Reverse stack",
                             variable=self.reverse,
                             command=self._schedule_render)
        rv.pack(side="left", padx=(0, 14))
        tip(rv, "Stack the spectra in the opposite order.")
        self.prev_btn = ttk.Button(self.footer, text="◀", width=3,
                                   style="Tool.TButton",
                                   command=self.prev_page, state="disabled")
        self.prev_btn.pack(side="left")
        self.next_btn = ttk.Button(self.footer, text="▶", width=3,
                                   style="Tool.TButton",
                                   command=self.next_page, state="disabled")
        self.next_btn.pack(side="left", padx=(2, 8))
        tip(self.prev_btn, "Previous panels")
        tip(self.next_btn, "Next panels")
        self.page_lbl = ttk.Label(self.footer, text="", style="Muted.TLabel")
        self.page_lbl.pack(side="left")
        self.hint = ttk.Label(self.footer, style="Hint.TLabel")
        self.hint.pack(side="right")

        if HAVE_MPL:
            self.fig = Figure(figsize=(6, 3.5), dpi=100)
            self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
            self.trace_bar = ttk.Frame(parent)
            self.trace_lbl = ttk.Label(self.trace_bar, text="", width=22,
                                       style="Muted.TLabel")
            self.trace_lbl.pack(side="left")
            self.trace_scale = ttk.Scale(
                self.trace_bar, from_=0, to=1, orient="horizontal",
                command=self._on_trace_scale)
            self.trace_scale.pack(side="left", fill="x", expand=True)
            self.panel_sb = ttk.Scrollbar(parent, orient="vertical",
                                          command=self._panel_scroll)
            self._make_toolbar()
            w = self.canvas.get_tk_widget()
            w.pack(side="top", expand=True, fill="both")
            self.canvas.mpl_connect("button_press_event", self._on_plot_click)
            w.bind("<MouseWheel>", self._on_wheel)
            w.bind("<Button-4>", lambda e: self._on_wheel(e, 120))
            w.bind("<Button-5>", lambda e: self._on_wheel(e, -120))
            w.bind("<Enter>", lambda e: w.focus_set())
            for key, fn in (("<Prior>", self.prev_page), ("<Next>", self.next_page),
                            ("<Home>", lambda: self._jump(0)),
                            ("<End>", lambda: self._jump(10 ** 9))):
                w.bind(key, lambda e, fn=fn: fn())
        else:
            self.footer.pack(side="bottom", fill="x", padx=10, pady=(2, 6))
            ttk.Label(parent, justify="left", padding=20,
                      text="matplotlib is not installed, so spectra cannot be "
                           "plotted.\n\n    pip install matplotlib").pack()

    def _on_axis_changed(self):
        if self.axis_var.get() == "Custom…":
            from tkinter import colorchooser
            _rgb, hexc = colorchooser.askcolor(
                color=self.axis_custom or "#000000", parent=self.root,
                title="Axis colour")
            if not hexc:                       # cancelled: keep the old choice
                self.axis_var.set(self.axis_choice)
                return
            self.axis_custom = hexc.upper()
        self.axis_choice = self.axis_var.get()
        self._apply_mpl_theme()
        self._schedule_render()

    def _on_view_changed(self):
        self._sync_view_controls()
        self._schedule_render(reset_page=True)

    def _sync_view_controls(self):
        """Enable only the controls that act in the current view."""
        stack = self.view_var.get() == "Stack"
        self.offset_sc.state(["!disabled"] if stack else ["disabled"])
        self.z_cb.state(["disabled"] if stack else ["!disabled", "readonly"])
        self.ke_cb.state(["disabled"] if self.scale_var.get() == "Kinetic"
                         else ["!disabled"])

    def _on_offset(self, value):
        self.offset_lbl.config(text=f"{float(value):.1f}×")
        self._schedule_render()

    def _layout_bottom(self):
        """(Re)pack the widgets under the plot in order: matplotlib toolbar
        (lowest), trace slider (only when it can act), footer."""
        for w in (self.toolbar, self.trace_bar, self.footer):
            w.pack_forget()
        self.toolbar.pack(side="bottom", fill="x")
        if self._trace_bar_on:
            self.trace_bar.pack(side="bottom", fill="x", padx=10)
        self.footer.pack(side="bottom", fill="x", padx=10, pady=(2, 6))

    def _set_scrollbar(self, on):
        if on == self._sb_on:
            return
        self._sb_on = on
        if on:
            self.panel_sb.pack(side="right", fill="y",
                               before=self.canvas.get_tk_widget())
        else:
            self.panel_sb.pack_forget()

    def _make_toolbar(self):
        """(Re)create the matplotlib navigation toolbar under the plot,
        coloured for the current theme."""
        if self.toolbar is not None:
            self.toolbar.destroy()
        self.toolbar = NavigationToolbar2Tk(self.canvas, self.plot_pane,
                                            pack_toolbar=False)
        # Windows paints disabled image buttons in the system grey, which
        # breaks dark themes: keep Back/Forward enabled (no-ops when empty)
        self.toolbar.set_history_buttons = lambda: None
        for name in ("Back", "Forward"):
            btn = self.toolbar._buttons.get(name)
            if btn is not None:
                btn.configure(state="normal")
        self.themes.recolor_mpl_toolbar(self.toolbar)
        self._layout_bottom()

    def _build_meta_table(self, parent):
        ttk.Label(parent, text="Details", style="Section.TLabel").pack(
            side="top", anchor="w", padx=12, pady=(8, 2))
        body = ttk.Frame(parent)
        body.pack(side="top", fill="both", expand=True)
        indent = 132                          # px: field names | values
        self.meta = tk.Text(body, wrap="word", relief="flat", borderwidth=0,
                            highlightthickness=0, padx=12, pady=2,
                            cursor="arrow", exportselection=False,
                            state="disabled", width=30, height=8,
                            font="TkDefaultFont")
        self.meta.configure(tabs=(indent + 12,))
        self.meta.tag_configure("row", lmargin1=0, lmargin2=indent + 12,
                                spacing1=3)
        self.meta.tag_configure("h", spacing1=12, spacing3=2,
                                font="AppSection")
        sb = ttk.Scrollbar(body, command=self.meta.yview)
        self.meta.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.meta.pack(side="left", expand=True, fill="both")
        self.meta_hint = ttk.Label(
            body, style="Muted.TLabel", wraplength=300, justify="left",
            text="Select a spectrum in the tree to see how it was acquired.\n\n"
                 "Ticking its box plots it.")
        self._restyle_details()
        self._update_metadata()

    def _restyle_details(self):
        p = self.palette
        self.meta.configure(bg=p["bg"], fg=p["fg"], insertbackground=p["fg"],
                            selectbackground=p["select_bg"],
                            selectforeground=p["select_fg"])
        self.meta.tag_configure("k", foreground=p["muted"])

    def _build_side_tabs(self):
        self.tab_images = ttk.Frame(self.nb)
        self.tab_map = ttk.Frame(self.nb)
        self.nb.add(self.tab_images, text="Images")
        self.nb.add(self.tab_map, text="Stage map")

        # images: horizontal thumbnail strip on top, viewer below
        strip = ttk.Frame(self.tab_images)
        strip.pack(side="top", fill="x")
        self.thumb_canvas = tk.Canvas(strip, height=98, highlightthickness=0)
        tsb = ttk.Scrollbar(strip, orient="horizontal",
                            command=self.thumb_canvas.xview)
        self.thumb_canvas.configure(xscrollcommand=tsb.set)
        tsb.pack(side="bottom", fill="x")
        self.thumb_canvas.pack(side="top", fill="x")
        self.thumb_inner = ttk.Frame(self.thumb_canvas)
        self.thumb_canvas.create_window((0, 0), window=self.thumb_inner,
                                        anchor="nw")
        self.thumb_inner.bind(
            "<Configure>",
            lambda e: self.thumb_canvas.configure(
                scrollregion=self.thumb_canvas.bbox("all")))

        bar = ttk.Frame(self.tab_images)
        bar.pack(side="top", fill="x", padx=6, pady=2)
        ttk.Button(bar, text="Calibrate…", command=self._toggle_calib).pack(
            side="left")
        self.overlay_var = tk.BooleanVar(value=False)
        self.overlay_cb = ttk.Checkbutton(
            bar, variable=self.overlay_var, command=self._toggle_overlay,
            text="Overlay positions")
        self.overlay_cb.pack(side="left", padx=8)
        self.calib_holder = ttk.Frame(self.tab_images)
        self.viewer = ttk.Frame(self.tab_images)
        self.viewer.pack(side="top", fill="both", expand=True)
        self._refresh_images()

        # stage map (rendered lazily when its tab is shown)
        self.map_frame = ttk.Frame(self.tab_map)
        self.map_frame.pack(fill="both", expand=True)
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self._refresh_side())

    # -- file handling --------------------------------------------------
    @staticmethod
    def _open_filetypes():
        fmts = supported_patterns()
        allpats = " ".join(p for _n, pats in fmts for p in pats)
        return ([("All supported spectra files", allpats + " *" + wbk.EXT),
                 ("Experiment workbook", "*" + wbk.EXT)]
                + [(n, " ".join(p)) for n, p in fmts]
                + [("All files", "*.*")])

    def open_files(self):
        paths = filedialog.askopenfilenames(filetypes=self._open_filetypes())
        books = [p for p in paths if p.lower().endswith(wbk.EXT)]
        if books:
            if len(books) == 1 and len(paths) == 1:
                self.open_workbook(books[0])
            else:
                messagebox.showinfo(
                    "Open", "Open an experiment workbook on its own, not "
                            "together with other files.")
            return
        self._add_files(paths)

    def open_folder(self):
        folder = filedialog.askdirectory(title="Open all spectra files in folder")
        if not folder:
            return
        paths = []
        for name in sorted(os.listdir(folder)):
            p = os.path.join(folder, name)
            if os.path.isfile(p):
                try:
                    reader_for(p)
                except (UnsupportedFormat, OSError):
                    continue
                paths.append(p)
        if not paths:
            messagebox.showinfo("Open folder",
                                "No recognised spectra files in that folder.")
            return
        self._add_files(paths)

    def _add_files(self, paths):
        """Load several files, reporting problems once at the end."""
        paths = self._resolve_duplicate_formats(list(paths))
        if paths is None:                       # import cancelled
            return
        problems = []
        for path in paths:
            problems += self._add_file(path)
        if problems:
            shown = problems[:12]
            more = f"\n… and {len(problems) - 12} more" if len(problems) > 12 else ""
            messagebox.showwarning("Some files need attention",
                                   "\n\n".join(shown) + more)

    def _resolve_duplicate_formats(self, paths):
        """Drop the redundant copy when a dataset is present as both .avg and
        .vgd (the data are the same). Asks unless a choice was remembered;
        returns the paths to load, or None if the user cancelled."""
        pairs = importplan.find_pairs(paths)
        if not pairs:
            return paths
        pref = self.cfg.get("dup_format")
        if pref in importplan.CHOICES:
            return importplan.apply_choice(paths, pairs, pref)
        dlg = workbook_ui.DuplicateFormatDialog(self.root, self, pairs, "avg")
        self.root.wait_window(dlg)
        if dlg.result is None:
            return None
        choice, remember = dlg.result
        if remember and isinstance(choice, str):
            self.cfg["dup_format"] = choice
            save_config(self.cfg)
        return importplan.apply_choice(paths, pairs, choice)

    def _forget_dup_choice(self):
        self.cfg.pop("dup_format", None)
        save_config(self.cfg)
        messagebox.showinfo("Duplicate formats",
                            "You will be asked again when a folder holds the "
                            "same data as .avg and .vgd.")

    def _add_file(self, path, file_id=None, origin=""):
        """Load one file into the tree. Returns a list of problem strings."""
        name = os.path.basename(path)
        if any(p.path == path for p in self.docs):
            return [f"{name}: already loaded."]
        try:
            parser = load_file(path)
        except UnsupportedFormat as exc:
            return [str(exc)]
        except Exception as exc:
            return [f"{name}: could not be read ({exc})"]
        self.docs.append(parser)
        fid = file_id or wbk.new_id(self._fid_used, "f")
        self._fid_used.add(fid)
        self.file_ids[id(parser)] = fid
        self.file_origin[id(parser)] = origin or path
        for r in parser.regions:
            self.region_parser[id(r)] = parser
        self._recompute_colours()
        self._populate_tree()
        self._refresh_images()
        self._schedule_render(reset_page=True)
        problems = []
        if parser.corruption["corrupted"]:
            problems.append(f"{name}: {parser.corruption['message']}")
        problems += [f"{name}: {w}" for w in parser.warnings]
        return problems

    def _recompute_colours(self):
        self.color_slot = colour_slots(self.docs)

    def trace_colours(self, regs, pal=None):
        pal = pal or self.palette
        if HAVE_MPL:
            along = themes.scale_colours(self.colscale_var.get(),
                                         bool(self.colrev_var.get()),
                                         len(regs), pal)
            if along is not None:           # a colour scale, not the theme's
                return along
        return stack_colours([self.color_slot.get(id(r), 0) for r in regs],
                             pal["cycle"], pal["plot_bg"])

    def _assign_colours(self, groups):
        self.trace_color = {}
        for _key, rs in groups:
            for r, c in zip(rs, self.trace_colours(rs)):
                self.trace_color[id(r)] = c

    def _remove_doc(self, parser):
        for r in parser.regions:
            self.checked.discard(id(r))
            self.region_parser.pop(id(r), None)
        self.docs.remove(parser)
        self.file_ids.pop(id(parser), None)
        self.file_origin.pop(id(parser), None)
        self._recompute_colours()
        self.sel_regions = []
        if self._cur_image and self._cur_image[0] is parser:
            self._cur_image = None
        self._populate_tree()
        self._refresh_images()
        self._update_metadata()
        self._schedule_render(reset_page=True)

    def close_all(self):
        for p in list(self.docs):
            self._remove_doc(p)

    # -- tree -----------------------------------------------------------
    def _populate_tree(self):
        self.tree.delete(*self.tree.get_children())
        self.node_map.clear()
        self.leaf_ids.clear()
        self.leaf_region.clear()
        self.box_state.clear()
        flt = self.filter_var.get().strip().lower()

        def matches(node):
            if not flt:
                return True
            hay = (node.label + " " + " ".join(str(c) for c in node.cols)).lower()
            return flt in hay or any(matches(c) for c in node.children)

        def add(parent, parser, node, depth, n_samples):
            if not matches(node):
                return
            leaves = [r for r in regions_under(node) if r.decodable and r.counts]
            ids = frozenset(id(r) for r in leaves)
            opened = True if flt else self._open.get(
                id(node), depth == 0 or (depth == 1 and n_samples <= 3))
            cols = tuple(node.cols) if node.cols else ("", "", "", "")
            state = tick_state(ids, self.checked)
            colour = (self.trace_color.get(id(node.region))
                      if state == 2 and node.region is not None else None)
            iid = self.tree.insert(
                parent, "end", text=" " + node.label, open=opened, values=cols,
                image=self.swatches.get(state, colour) if ids
                else self.blank_img)
            self.node_map[iid] = (parser, node)
            if ids:
                self.leaf_ids[iid] = ids
                self.box_state[iid] = (state, colour)
                if node.region is not None:
                    self.leaf_region[iid] = node.region
            for c in node.children:
                add(iid, parser, c, depth + 1, n_samples)

        for p in self.docs:
            if p.tree:
                add("", p, p.tree, 0, len(p.tree.children))
        show_etch = any(p.depth_profile.get("is_profile") for p in self.docs)
        self.tree.configure(displaycolumns=(
            ("detail", "pts", "pe", "etch") if show_etch
            else ("detail", "pts", "pe")))

    def _note_open(self, opened):
        iid = self.tree.focus()
        item = self.node_map.get(iid)
        if item:
            self._open[id(item[1])] = opened

    def _expand(self, opened):
        for iid, (_p, node) in self.node_map.items():
            self.tree.item(iid, open=opened)
            self._open[id(node)] = opened

    def _refresh_boxes(self):
        for iid, ids in self.leaf_ids.items():
            st = tick_state(ids, self.checked)
            colour = None
            if st == 2 and iid in self.leaf_region:
                colour = self.trace_color.get(id(self.leaf_region[iid]))
            if self.box_state.get(iid) != (st, colour):
                self.box_state[iid] = (st, colour)
                self.tree.item(iid, image=self.swatches.get(st, colour))

    def _toggle(self, iids, force=None):
        ids = set()
        for i in iids:
            ids |= self.leaf_ids.get(i, set())
        if not ids:
            return
        if force is None:
            force = not ids <= self.checked
        if force:
            self.checked |= ids
        else:
            self.checked -= ids
        self._refresh_boxes()
        self._schedule_render()

    def untick_all(self):
        self.checked.clear()
        self._refresh_boxes()
        self._schedule_render(reset_page=True)

    def _on_tree_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid or iid not in self.leaf_ids:
            return
        try:
            elem = self.tree.identify_element(event.x, event.y)
        except tk.TclError:
            elem = ""
        if elem != "image":
            return
        self._toggle([iid])
        return "break"          # tick without changing the row selection

    def _on_tree_space(self, _event):
        sel = list(self.tree.selection())
        if sel:
            self._toggle(sel)
        return "break"

    def _regions_of(self, iids):
        regs, seen = [], set()
        for iid in iids:
            item = self.node_map.get(iid)
            if item is None:
                continue
            for r in regions_under(item[1]):
                if id(r) not in seen:
                    seen.add(id(r))
                    regs.append(r)
        return regs

    def _on_select(self, _event=None):
        sel = self.tree.selection()
        self.sel_regions = self._regions_of(sel)
        images = [(p, n.image) for p, n in
                  (self.node_map[i] for i in sel if i in self.node_map)
                  if n.image is not None]
        if len(images) == 1 and not self.sel_regions:
            self._show_image(*images[0])
        self._update_metadata()
        self._refresh_side()

    def _context_menu(self, event):
        row = self.tree.identify_row(event.y)
        if not row:
            return
        if row not in self.tree.selection():
            self.tree.selection_set(row)
        sel = list(self.tree.selection())
        regions = [r for r in self._regions_of(sel) if r.decodable and r.counts]
        n = len(regions)
        menu = self._menu(self.tree)
        if n:
            menu.add_command(label=f"Tick ({n})",
                             command=lambda: self._toggle(sel, True))
            menu.add_command(label=f"Untick ({n})",
                             command=lambda: self._toggle(sel, False))
            menu.add_separator()
            exp = self._menu(menu)
            exp.add_command(label="CSV…",
                            command=lambda: self._write_export(regions, "csv"))
            exp.add_command(label="VAMAS…",
                            command=lambda: self._write_export(regions, "vamas"))
            menu.add_cascade(label=f"Export from here down ({n})", menu=exp)
        else:
            menu.add_command(label="(no decodable spectra here)",
                             state="disabled")
        item = self.node_map.get(row)
        if item and item[1] is item[0].tree:
            menu.add_separator()
            menu.add_command(label="Remove this file",
                             command=lambda p=item[0]: self._remove_doc(p))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # -- plotting -------------------------------------------------------
    def _ticked_regions(self):
        out = []
        for p in self.docs:
            if p.tree:
                out += [r for r in regions_under(p.tree)
                        if id(r) in self.checked and r.decodable and r.counts]
        return out

    def _date_of(self, r):
        p = self.region_parser.get(id(r))
        return p.date_for_region(r) if p else r.date

    def _groups(self):
        groups = group_regions(self._ticked_regions(),
                               self.GROUP_MODES[self.group_var.get()])
        if self.view_var.get() != "Stack":
            # series views read in z order (surface first / earliest first)
            out = []
            for k, rs in groups:
                order, _z = viewdata.z_sorted(rs, self.z_var.get(),
                                              self._date_of)
                out.append((k, [rs[i] for i in order]))
            return out
        if self.reverse.get():
            groups = [(k, rs[::-1]) for k, rs in groups]
        return groups

    # -- view window: panels per page / traces per panel ----------------
    def _panels_per_page(self, n_groups):
        try:
            n = max(1, min(16, int(self.panels_var.get())))
        except ValueError:                       # "Auto"
            n = min(16, max(1, n_groups))
        return max(1, min(n, max(1, n_groups)))

    def _traces_limit(self):
        try:
            n = int(str(self.traces_var.get()).strip())
        except ValueError:
            return None                          # "All"
        return n if n > 0 else None

    def _on_traces_changed(self):
        if self._traces_limit() is None:
            self.traces_var.set("All")
        self._schedule_render()

    def _schedule_render(self, reset_page=False):
        if reset_page:
            self.panel_start = 0
            self.trace_start = 0
        if self._render_job is None:
            self._render_job = self.root.after_idle(self._render)

    def _cols(self, n_groups):
        return _grid_dims(self._panels_per_page(n_groups))[1]

    def _jump(self, idx):
        self.panel_start = max(0, idx)           # clamped (and row-aligned)
        self._schedule_render()

    def prev_page(self):
        n = len(self._groups())
        self._jump(self.panel_start - self._panels_per_page(n))

    def next_page(self):
        n = len(self._groups())
        self._jump(self.panel_start + self._panels_per_page(n))

    def _panel_scroll(self, *args):
        n = len(self._groups())
        cols = self._cols(n)
        if args[0] == "moveto":
            self.panel_start = int(float(args[1]) * n)
        elif args[0] == "scroll":
            unit = cols if args[2] == "units" else self._panels_per_page(n)
            self.panel_start += int(args[1]) * unit
        self._schedule_render()

    def _on_wheel(self, event, delta=None):
        d = delta if delta is not None else event.delta
        step = -1 if d > 0 else 1
        if event.state & 0x0001:                 # Shift: slide the trace window
            limit = self._traces_limit()
            if limit:
                self.trace_start += step * max(1, limit // 5)
                self._schedule_render()
        else:                                    # wheel: move by a row of panels
            self.panel_start += step * self._cols(len(self._groups()))
            self._schedule_render()
        return "break"

    def _on_trace_scale(self, val):
        if self._scale_guard:
            return
        v = int(round(float(val)))
        if v != self.trace_start:
            self.trace_start = v
            self._schedule_render()

    def _update_trace_controls(self, limit, longest):
        max_start = max(0, longest - limit) if limit else 0
        self.trace_start = max(0, min(self.trace_start, max_start))
        if not HAVE_MPL:
            return
        self._scale_guard = True
        try:
            self.trace_scale.configure(to=max(1, max_start))
            self.trace_scale.set(self.trace_start)
        finally:
            self._scale_guard = False
        on = max_start > 0
        if on:
            a = self.trace_start + 1
            self.trace_lbl.config(
                text=f"Traces {a}–{min(a + limit - 1, longest)} of {longest}")
        if on != self._trace_bar_on:
            self._trace_bar_on = on
            self._layout_bottom()

    def _render(self):
        self._render_job = None
        groups = self._groups()
        self._assign_colours(groups)
        self._refresh_boxes()
        n_groups = len(groups)
        n_spec = sum(len(rs) for _k, rs in groups)
        npp = self._panels_per_page(n_groups)
        cols = _grid_dims(npp)[1]
        max_start = max(0, n_groups - npp)
        self.panel_start = max(0, min(self.panel_start, max_start))
        self.panel_start -= self.panel_start % cols       # row-aligned
        chunk = groups[self.panel_start:self.panel_start + npp]
        limit = self._traces_limit()
        self._update_trace_controls(
            limit, max((len(rs) for _k, rs in groups), default=0))
        self._counts = (n_spec, n_groups)
        self.prev_btn.config(
            state="normal" if self.panel_start > 0 else "disabled")
        self.next_btn.config(
            state="normal" if self.panel_start + npp < n_groups else "disabled")
        shown = len(chunk)
        self.page_lbl.config(
            text=(f"Panels {self.panel_start + 1}–{self.panel_start + shown} "
                  f"of {n_groups}") if n_groups > npp else "")
        self.hint.config(
            text="Click a panel to set the energy to match at."
            if (self.norm_var.get() == "At cursor" and n_spec
                and self.view_var.get() == "Stack") else "")
        self._set_scrollbar(HAVE_MPL and n_groups > npp)
        if HAVE_MPL:
            self.fig.clear()
            self._axmap = {}
            if chunk:
                self._axmap = self._draw_page(self.fig, chunk, limit,
                                              self.trace_start)
            else:
                self.fig.text(0.5, 0.5,
                              "Tick spectra in the tree to plot them here.\n"
                              "Spectra with the same element name are "
                              "stacked on one panel.",
                              ha="center", va="center",
                              color=self.palette["muted"])
            self.fig.set_facecolor(self.palette["plot_bg"])
            self.canvas.draw()
            if n_groups:
                self.panel_sb.set(self.panel_start / n_groups,
                                  (self.panel_start + shown) / n_groups)
            else:
                self.panel_sb.set(0, 1)
        self._update_status()
        self._refresh_side()
        self._update_title()

    def _draw_page(self, fig, chunk, limit=None, start=0, pal=None,
                   rect=None):
        """Draw one page of panels onto fig; returns {axes: group key}.
        ``limit``/``start`` show a window of long stacks; ``pal`` overrides the
        colours (PDFs pass the white 'print' palette)."""
        base = pal or self.palette          # theme colours (trace colours)
        pal, axis_note = self._plot_palette(base, paper=pal is not None)
        rows, cols = _grid_dims(len(chunk))
        multi = len(self.docs) > 1
        norm = self.norm_var.get()
        offset = float(self.offset_var.get())
        view = self.view_var.get()
        scale = self.scale_var.get()
        ke_top = bool(self.ke_var.get()) and scale == "Binding"
        selected = {id(r) for r in self.sel_regions}
        axmap, stacked_axes, axhv = {}, [], {}
        notes = []
        if fig is self.fig:
            self._view_notes = notes
            if axis_note:
                notes.append(axis_note)
        cmap_name = self.colscale_var.get()
        reverse = bool(self.colrev_var.get())
        for i, (key, rs) in enumerate(chunk):
            s = min(start, len(rs) - limit) if limit and len(rs) > limit else 0
            vis = rs[s:s + limit] if limit and len(rs) > limit else rs
            colours = self.trace_colours(rs, base)[s:s + len(vis)]
            if scale == "Kinetic" and not all(
                    viewdata.energy_axis(r, scale).ok for r in vis):
                notes.append("no photon energy for some spectra: shown "
                             "as binding energy")
            if ke_top and viewdata.mixed_photon_energy(vis):
                notes.append("photon energies differ: KE axis uses the first")
            if len(rs) == 1:
                title = rs[0].name
                subtitle = rs[0].sample
            else:
                title = key
                subtitle = (f"{len(rs)} spectra" if len(vis) == len(rs)
                            else f"{s + 1}–{s + len(vis)} of {len(rs)}")
            top_row = i < cols
            if view != "Stack":
                # groups arrive z-sorted (_groups), so this order is the
                # identity and ``vis`` lines up with the z values
                _order, zi = viewdata.z_sorted(rs, self.z_var.get(),
                                               self._date_of)
                zvis = viewdata.ZInfo(zi.values[s:s + len(vis)], zi.label,
                                      zi.mode)
                want = self.z_var.get()
                if want != "Auto" and zi.mode != want:
                    notes.append(f"'{want}' not usable for {key}: showing "
                                 f"{zi.mode.lower()}")
                if view == "Heatmap":
                    ax = fig.add_subplot(rows, cols, i + 1)
                    draw_heatmap(fig, ax, vis, zvis, norm,
                                 themes.scale_colourmap(cmap_name, reverse,
                                                        base), title,
                                 subtitle, first_col=(i % cols == 0),
                                 bottom_row=(i + cols >= len(chunk)),
                                 top_row=top_row, muted=pal["muted"],
                                 scale=scale, ke_top=ke_top)
                else:
                    ax = fig.add_subplot(rows, cols, i + 1, projection="3d")
                    draw_waterfall3d(ax, vis, zvis, norm, colours, title,
                                     subtitle, pal, scale)
                axmap[ax] = key
                continue
            ax = fig.add_subplot(rows, cols, i + 1)
            cur = None
            if norm == "At cursor":
                cur = self.cursors.get(key)
                if cur is None:
                    e = vis[0].energy
                    cur = self.cursors[key] = (e[0] + e[-1]) / 2.0
            draw_stack(ax, vis, offset, norm, cur, colours, title, subtitle,
                       selected, multi, first_col=(i % cols == 0),
                       bottom_row=(i + cols >= len(chunk)),
                       accent=pal["accent"], muted=pal["muted"],
                       scale=scale, ke_top=ke_top, top_row=top_row)
            axmap[ax] = key
            axhv[ax] = viewdata.photon_energy(vis)
            if len(vis) > 1:
                stacked_axes.append(ax)
        if fig is self.fig:
            self._axhv = axhv
        if rect is not None:            # leave room for a heading / caption
            fig.tight_layout(rect=rect)
        else:
            fig.tight_layout()
        # make room for the end-of-trace labels to the right of stacked axes
        gutter = 78 / 72.0 / fig.get_figwidth()
        for ax in stacked_axes:
            b = ax.get_position()
            ax.set_position([b.x0, b.y0, max(0.05, b.width - gutter), b.height])
        return axmap

    def _on_plot_click(self, event):
        if (self.norm_var.get() != "At cursor" or event.inaxes is None
                or event.xdata is None or self.view_var.get() != "Stack"):
            return
        if str(getattr(self.toolbar, "mode", "")):
            return              # zoom / pan tool is active
        key = self._axmap.get(event.inaxes)
        if key is not None:
            x = float(event.xdata)
            hv = self._axhv.get(event.inaxes)
            if self.scale_var.get() == "Kinetic" and hv:
                x = hv - x              # cursors are kept as binding energy
            self.cursors[key] = x
            self._schedule_render()

    # -- experiment workbook (.xpscontainer) --------------------------------
    STATE_CHOICES = {
        "group_by": ("group_var", None), "norm": ("norm_var", None),
        "view_mode": ("view_var", None), "energy_scale": ("scale_var", None),
        "z_axis": ("z_var", None), "colour_scale": ("colscale_var", None),
        "panels_per_page": ("panels_var", None),
    }

    def capture_state(self):
        """The current look as JSON-able data: view settings plus the ticked
        spectra as stable references (not ``id(region)``)."""
        ticked = []
        for p in self.docs:
            fid = self.file_ids.get(id(p))
            for pos, r in enumerate(p.regions):
                if id(r) in self.checked:
                    ticked.append(wbk.region_ref(fid, pos, r))
        return {
            "group_by": self.group_var.get(), "norm": self.norm_var.get(),
            "offset": round(float(self.offset_var.get()), 4),
            "reverse": bool(self.reverse.get()),
            "view_mode": self.view_var.get(),
            "energy_scale": self.scale_var.get(),
            "ke_top": bool(self.ke_var.get()), "z_axis": self.z_var.get(),
            "colour_scale": self.colscale_var.get(),
            "colour_reverse": bool(self.colrev_var.get()),
            "axis_colour": self.axis_choice,
            "axis_colour_custom": self.axis_custom,
            "panels_per_page": self.panels_var.get(),
            "traces_per_panel": self.traces_var.get(),
            "panel_start": int(self.panel_start),
            "trace_start": int(self.trace_start),
            "cursors": {k: float(v) for k, v in self.cursors.items()},
            "ticked": ticked,
        }

    def apply_state(self, st, render=True):
        """Restore a look saved by ``capture_state``. Unknown or invalid
        values keep the current setting. Returns how many saved spectra could
        not be found in the loaded files."""
        allowed = {
            "group_by": self.GROUP_MODES, "norm": self.NORM_MODES,
            "view_mode": self.VIEW_MODES,
            "energy_scale": viewdata.ENERGY_SCALES,
            "z_axis": viewdata.Z_MODES, "colour_scale": themes.SCALE_NAMES,
            "panels_per_page": self.PANEL_CHOICES,
        }
        for key, (var, _x) in self.STATE_CHOICES.items():
            v = st.get(key)
            if v in allowed[key]:
                getattr(self, var).set(v)
        try:
            self.offset_var.set(max(0.0, min(3.0, float(st["offset"]))))
            self.offset_lbl.config(text=f"{self.offset_var.get():.1f}×")
        except (KeyError, TypeError, ValueError):
            pass
        for key, var in (("reverse", self.reverse), ("ke_top", self.ke_var),
                         ("colour_reverse", self.colrev_var)):
            if isinstance(st.get(key), bool):
                var.set(st[key])
        tr = str(st.get("traces_per_panel", "")).strip()
        if tr == "All" or (tr.isdigit() and int(tr) > 0):
            self.traces_var.set(tr)
        ax = st.get("axis_colour")
        if ax in themes.AXIS_CHOICES:
            self.axis_choice = ax
            self.axis_var.set(ax)
        custom = st.get("axis_colour_custom")
        if custom is None or re.fullmatch(r"#[0-9A-Fa-f]{6}", str(custom)):
            self.axis_custom = custom
        for key, attr in (("panel_start", "panel_start"),
                          ("trace_start", "trace_start")):
            if isinstance(st.get(key), int) and st[key] >= 0:
                setattr(self, attr, st[key])
        cur = st.get("cursors")
        if isinstance(cur, dict):
            self.cursors = {str(k): float(v) for k, v in cur.items()
                            if isinstance(v, (int, float))}
        missing = 0
        if isinstance(st.get("ticked"), list):
            by_file = {self.file_ids.get(id(p)): p.regions for p in self.docs}
            regs, missing = wbk.resolve_refs(st["ticked"], by_file)
            self.checked = {id(r) for r in regs}
        self._apply_mpl_theme()
        self._sync_view_controls()
        if render:
            self._schedule_render()
        return missing

    @contextlib.contextmanager
    def _temp_state(self, st):
        """Apply a saved look for a moment (e.g. to draw a report figure),
        then put the live view back exactly as it was."""
        keep = self.capture_state()
        keep_checked, keep_cursors = set(self.checked), dict(self.cursors)
        self.apply_state(st, render=False)
        try:
            yield
        finally:
            self.apply_state(keep, render=False)
            self.checked, self.cursors = keep_checked, keep_cursors

    def _wb_active(self):
        return bool(self.wb_path or self.figures or self.logo
                    or any(self.details.values()))

    def _signature(self):
        st = self.capture_state()
        st.pop("panel_start", None)         # scrolling is not an edit
        st.pop("trace_start", None)
        files = sorted(f"{self.file_ids.get(id(p))}:{os.path.basename(p.path)}"
                       for p in self.docs)
        return json.dumps({"d": self.details, "l": self.logo,
                           "f": self.figures, "s": st, "files": files},
                          sort_keys=True, default=str)

    def _wb_dirty(self):
        return self._wb_active() and self._signature() != self._wb_sig

    def _update_title(self):
        title = "ESCApe Explorer"
        if self._wb_active():
            name = (os.path.basename(self.wb_path) if self.wb_path
                    else "Unsaved workbook")
            title = f"{'* ' if self._wb_dirty() else ''}{name} — {title}"
        if self.root.title() != title:
            self.root.title(title)

    def wb_touch(self):
        self._update_title()

    def _confirm_discard(self):
        """Before leaving the current workbook: offer to save unsaved changes.
        Returns False if the user cancelled."""
        if not self._wb_dirty():
            return True
        name = (os.path.basename(self.wb_path) if self.wb_path
                else "the workbook")
        ans = messagebox.askyesnocancel(
            "Unsaved changes", f"Save changes to {name} before continuing?")
        if ans is None:
            return False
        if ans:
            return self.save_workbook()
        return True

    def _drop_wb_dir(self):
        if self.wb_dir:
            shutil.rmtree(self.wb_dir, ignore_errors=True)
            self.wb_dir = None

    def _reset_workbook(self):
        self.details = {k: "" for k in wbk.DETAIL_FIELDS}
        self.logo, self.figures = "", []
        self.wb_path, self.wb_extra, self.wb_created = None, {}, ""
        self._fid_used = set()

    def new_workbook(self):
        if not self._confirm_discard():
            return
        self.close_all()
        self.untick_all()
        self._reset_workbook()
        self._drop_wb_dir()
        self._wb_sig = self._signature()
        self._update_title()

    def _metadata_snapshot(self):
        snap = {}
        for p in self.docs:
            fid = self.file_ids.get(id(p))
            snap[fid] = {"file": os.path.basename(p.path or ""),
                         "format": p.format_name,
                         "samples": [{"sample": s, "regions": rows}
                                     for s, rows in p.samples_metadata()]}
        return snap

    def save_workbook(self, as_new=False):
        """Write the workbook. Returns True on success."""
        path = self.wb_path
        if as_new or not path:
            stem = re.sub(r"[^\w.\- ]+", "_",
                          self.details.get("title") or "experiment").strip()
            path = filedialog.asksaveasfilename(
                title="Save experiment workbook",
                defaultextension=wbk.EXT, initialfile=(stem or "experiment")
                + wbk.EXT,
                filetypes=[("Experiment workbook", "*" + wbk.EXT)])
            if not path:
                return False
        entries = []
        for p in self.docs:
            entries.append(wbk.FileEntry(
                id=self.file_ids[id(p)], name=os.path.basename(p.path),
                path=p.path, original_path=self.file_origin.get(id(p), p.path)))
        total = sum(os.path.getsize(e.path) for e in entries
                    if os.path.isfile(e.path))
        if total > 500 * 1024 * 1024 and not messagebox.askokcancel(
                "Large workbook",
                f"The data files add up to {total / 1048576:.0f} MB and will "
                f"be copied into the workbook. Continue?"):
            return False
        preview = None
        if HAVE_MPL and self.fig is not None:
            try:
                buf = io.BytesIO()
                self.fig.savefig(buf, format="png", dpi=60)
                preview = buf.getvalue()
            except Exception:
                preview = None
        book = wbk.Workbook(
            details=dict(self.details), state=self.capture_state(),
            figures=copy.deepcopy(self.figures), files=entries,
            logo=self.logo, metadata=self._metadata_snapshot(),
            created=self.wb_created, extra=dict(self.wb_extra))
        self.root.config(cursor="watch")
        self.root.update_idletasks()
        try:
            wbk.save(path, book, preview)
        except (wbk.WorkbookError, OSError) as exc:
            messagebox.showerror("Could not save workbook", str(exc))
            return False
        finally:
            self.root.config(cursor="")
        self.wb_path, self.wb_created = path, book.created
        self._wb_sig = self._signature()
        self._update_title()
        return True

    def open_workbook(self, path=None):
        if not self._confirm_discard():
            return
        path = path or filedialog.askopenfilename(
            title="Open experiment workbook",
            filetypes=[("Experiment workbook", "*" + wbk.EXT),
                       ("All files", "*.*")])
        if not path:
            return
        folder = tempfile.mkdtemp(prefix="xpsc_")
        self.root.config(cursor="watch")
        self.root.update_idletasks()
        try:
            book = wbk.load(path, folder)
        except wbk.WorkbookError as exc:
            shutil.rmtree(folder, ignore_errors=True)
            messagebox.showerror("Could not open workbook", str(exc))
            return
        finally:
            self.root.config(cursor="")
        self.close_all()
        self.untick_all()
        self._drop_wb_dir()
        self._reset_workbook()
        self.wb_dir = folder
        self._fid_used = {f.id for f in book.files}
        problems = list(book.warnings)
        for f in book.files:
            problems += self._add_file(f.path, file_id=f.id,
                                       origin=f.original_path)
        self.details, self.logo = book.details, book.logo
        self.figures = book.figures
        self.wb_path, self.wb_extra = path, book.extra
        self.wb_created = book.created
        missing = self.apply_state(book.state)
        if missing:
            problems.append(f"{missing} ticked spectrum(s) could not be "
                            f"found in the loaded files.")
        self._wb_sig = self._signature()
        self._update_title()
        if problems:
            messagebox.showwarning("Workbook opened with warnings",
                                   "\n\n".join(problems[:12]))

    def edit_details(self):
        def apply(details, logo):
            self.details, self.logo = details, logo
            self.wb_touch()
        workbook_ui.DetailsDialog(self.root, self, self.details, self.logo,
                                  apply)

    def edit_figures(self):
        workbook_ui.FiguresDialog(self.root, self)

    # -- experiment report ---------------------------------------------------
    def _sha(self, path):
        try:
            st = os.stat(path)
        except OSError:
            return ""
        key = (path, st.st_mtime_ns, st.st_size)
        if key not in self._sha_cache:
            self._sha_cache[key] = wbk.sha256_file(path)
        return self._sha_cache[key]

    def _report_file_rows(self):
        rows = []
        for p in self.docs:
            try:
                size = os.path.getsize(p.path)
            except OSError:
                size = 0
            rows.append({"name": os.path.basename(p.path or ""),
                         "format": p.format_name, "regions": len(p.regions),
                         "size": size, "sha256": self._sha(p.path)})
        return rows

    def _render_figure_pages(self, fig, consume, size=(11.7, 8.3),
                             rect=(0.0, 0.17, 1.0, 0.94), decorate=True,
                             number=1, dpi=150):
        """Draw a saved figure with its own look (then restore the live
        view) and hand every page, still under the print style, to
        ``consume(page)``. Returns the list of its results. With
        ``decorate`` the heading and caption are drawn onto the page."""
        out = []
        with self._temp_state(fig["state"]):
            groups = self._groups()
            if not groups:
                return out
            per = self._pdf_per_page()
            limit, start = self._traces_limit(), self.trace_start
            pages = (len(groups) + per - 1) // per
            paper = self._plot_palette(PRINT, paper=True)[0]
            caption = textwrap.fill((fig.get("caption") or "").strip(), 150,
                                    replace_whitespace=False)
            with matplotlib.rc_context(mpl_rc(paper)):
                for pg in range(pages):
                    page = Figure(figsize=size, dpi=dpi)
                    self._draw_page(page, groups[pg * per:(pg + 1) * per],
                                    limit, start, pal=PRINT, rect=rect)
                    if decorate:
                        head = f"Figure {number} — {fig.get('name', '')}"
                        if pg:
                            head += " (continued)"
                        page.text(0.03, 0.975, head, fontsize=12,
                                  fontweight="bold", va="top")
                        if caption and pg == 0:
                            page.text(0.03, 0.145, caption, fontsize=9,
                                      va="top", linespacing=1.4)
                    out.append(consume(page))
        return out

    def _report_figure_pages(self, pdf, number, fig):
        """Draw one saved figure (all its pages) onto a PdfPages."""
        def consume(page):
            pdf.savefig(page)
            return 1
        return len(self._render_figure_pages(fig, consume, number=number))

    def _build_report(self, path, sections):
        figures = self.figures or ([{
            "name": "Current view", "caption": "",
            "state": self.capture_state()}] if self._groups() else [])
        if not HAVE_MPL:
            sections = tuple(s for s in sections if s != "figures")
        return report.build_report(
            path, self.details, self.logo, self._report_file_rows(),
            self.docs, figures, self._report_figure_pages, sections)

    def _report_ready(self):
        if not self.docs:
            messagebox.showinfo("Experiment report", "Open some spectra "
                                                     "files first.")
            return False
        return True

    def _deck_images(self, number, fig):
        """PNG bytes of each page of a saved figure, sized for a slide."""
        def consume(page):
            buf = io.BytesIO()
            page.savefig(buf, format="png", dpi=200)
            return buf.getvalue()
        return self._render_figure_pages(
            fig, consume, size=pptx_export.FIGURE_SIZE, rect=None,
            decorate=False, number=number)

    def _build_deck(self, path, sections):
        figures = self.figures or ([{
            "name": "Current view", "caption": "",
            "state": self.capture_state()}] if self._groups() else [])
        if not HAVE_MPL:
            sections = tuple(s for s in sections if s != "figures")
        return pptx_export.build_deck(
            path, self.details, self.logo, self._report_file_rows(),
            self.docs, figures, self._deck_images, sections)

    def export_powerpoint(self):
        if not self._report_ready():
            return

        def go(sections):
            stem = re.sub(r"[^\w.\- ]+", "_", self.details.get("title")
                          or "experiment").strip()
            path = filedialog.asksaveasfilename(
                title="Export PowerPoint", defaultextension=".pptx",
                initialfile=(stem or "experiment") + ".pptx",
                filetypes=[("PowerPoint presentation", "*.pptx")])
            if not path:
                return
            self.root.config(cursor="watch")
            self.root.update_idletasks()
            try:
                n = self._build_deck(path, sections)
            except pptx_export.PptxError as exc:
                messagebox.showerror("PowerPoint", str(exc))
                return
            except Exception as exc:
                messagebox.showerror("PowerPoint export failed", str(exc))
                return
            finally:
                self.root.config(cursor="")
            messagebox.showinfo("Saved",
                                f"Presentation ({n} slides) saved to\n{path}")

        workbook_ui.SectionsDialog(
            self.root, self, "Export PowerPoint",
            [("title", "Title and summary"), ("files", "Data files"),
             ("metadata", "Acquisition metadata"),
             ("figures", "Figures (one slide each)")], go)

    def save_report(self):
        if not self._report_ready():
            return
        stem = re.sub(r"[^\w.\- ]+", "_",
                      self.details.get("title") or "experiment report").strip()
        path = filedialog.asksaveasfilename(
            title="Save experiment report", defaultextension=".pdf",
            initialfile=(stem or "experiment report") + ".pdf",
            filetypes=[("PDF", "*.pdf")])
        if not path:
            return
        self.root.config(cursor="watch")
        self.root.update_idletasks()
        try:
            n = self._build_report(path, report.SECTIONS)
        except report.ReportError as exc:
            messagebox.showerror("Report", str(exc))
            return
        except Exception as exc:
            messagebox.showerror("Report failed", str(exc))
            return
        finally:
            self.root.config(cursor="")
        messagebox.showinfo("Saved", f"Report ({n} pages) saved to\n{path}")

    def preview_report(self):
        if not self._report_ready():
            return
        pv = self.preview
        pv.clear_options()
        self._rp_sections = {
            "cover": tk.BooleanVar(value=True),
            "metadata": tk.BooleanVar(value=True),
            "figures": tk.BooleanVar(value=True)}
        ttk.Label(pv.options, text="Include").pack(side="left")
        for key, text in (("cover", "Cover and notes"),
                          ("metadata", "Metadata"), ("figures", "Figures")):
            ttk.Checkbutton(pv.options, text=text, variable=self._rp_sections[
                key], command=self._regen_report_preview).pack(
                side="left", padx=(10, 0))
        self.themes.recolor_tk(pv)
        if not self._regen_report_preview():
            return
        self._show_preview()

    def _regen_report_preview(self):
        chosen = tuple(k for k, v in self._rp_sections.items() if v.get())
        if not chosen:
            messagebox.showinfo("Report", "Choose at least one section.")
            return False
        path = self._pdf_tmp("report.pdf")
        self.root.config(cursor="watch")
        self.root.update_idletasks()
        try:
            self._build_report(path, chosen)
        except report.ReportError as exc:
            messagebox.showerror("Report", str(exc))
            return False
        except Exception as exc:
            messagebox.showerror("Report failed", str(exc))
            return False
        finally:
            self.root.config(cursor="")
        return self._open_preview(path, "Experiment report",
                                  "experiment_report.pdf", keep_page=True)

    # -- PDF output: shared builder, save, and in-app preview --------------
    def _pdf_per_page(self):
        try:
            return max(1, min(16, int(self.panels_var.get())))
        except ValueError:
            return 6

    def build_spectra_pdf(self, path, per_page, landscape=True,
                          windowed=False):
        """Write every panel to a PDF (white 'paper' style, any theme)."""
        from matplotlib.backends.backend_pdf import PdfPages
        groups = self._groups()
        limit = self._traces_limit() if windowed else None
        size = (11.7, 8.3) if landscape else (8.3, 11.7)
        paper = self._plot_palette(PRINT, paper=True)[0]
        with matplotlib.rc_context(mpl_rc(paper)), PdfPages(path) as pdf:
            for p in range((len(groups) + per_page - 1) // per_page):
                fig = Figure(figsize=size, dpi=150)
                self._draw_page(fig, groups[p * per_page:(p + 1) * per_page],
                                limit, self.trace_start, pal=PRINT)
                pdf.savefig(fig)
        return len(groups)

    def save_pdf(self):
        if not self._groups():
            messagebox.showinfo("Save PDF", "Tick some spectra first.")
            return
        if not HAVE_MPL:
            messagebox.showinfo("PDF", "matplotlib is required to make a PDF.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
            initialfile="spectra.pdf")
        if not path:
            return
        try:
            self.build_spectra_pdf(path, self._pdf_per_page())
        except Exception as exc:
            messagebox.showerror("PDF failed", str(exc))
            return
        messagebox.showinfo("Saved", f"Plot saved to\n{path}")

    def _pdf_tmp(self, name):
        if self._pdf_dir is None or not os.path.isdir(self._pdf_dir):
            self._pdf_dir = tempfile.mkdtemp(prefix="escape_explorer_pdf_")
        return os.path.join(self._pdf_dir, name)

    def _show_preview(self):
        self.plot_pane.grid_remove()
        self.preview.grid()
        self.themes.recolor_tk(self.center)
        self.preview.update_idletasks()
        self.preview.refresh()          # re-fit now that the canvas has a size

    def close_preview(self):
        self.preview.grid_remove()
        self.plot_pane.grid()
        self.preview.close_document()

    def preview_spectra(self):
        if not HAVE_MPL:
            messagebox.showinfo("PDF", "matplotlib is required to make a PDF.")
            return
        if not self._groups():
            messagebox.showinfo("Preview PDF", "Tick some spectra first.")
            return
        pv = self.preview
        pv.clear_options()
        self._pv_panels = tk.StringVar(value=str(self._pdf_per_page()))
        self._pv_orient = tk.StringVar(value="Landscape")
        self._pv_window = tk.BooleanVar(value=False)
        ttk.Label(pv.options, text="Panels per page").pack(side="left")
        cb = ttk.Combobox(pv.options, textvariable=self._pv_panels, width=4,
                          state="readonly",
                          values=["1", "2", "4", "6", "9", "12", "16"])
        cb.pack(side="left", padx=(6, 16))
        cb.bind("<<ComboboxSelected>>", lambda e: self._regen_spectra_preview())
        ttk.Label(pv.options, text="Page").pack(side="left")
        ob = ttk.Combobox(pv.options, textvariable=self._pv_orient, width=9,
                          state="readonly", values=["Landscape", "Portrait"])
        ob.pack(side="left", padx=(6, 16))
        ob.bind("<<ComboboxSelected>>", lambda e: self._regen_spectra_preview())
        if self._traces_limit():
            ttk.Checkbutton(
                pv.options, variable=self._pv_window,
                text="Only the traces currently in view",
                command=self._regen_spectra_preview).pack(side="left")
        self.themes.recolor_tk(pv)
        if not self._regen_spectra_preview():
            return
        self._show_preview()

    def _regen_spectra_preview(self):
        path = self._pdf_tmp("spectra.pdf")
        try:
            self.build_spectra_pdf(
                path, int(self._pv_panels.get()),
                self._pv_orient.get() == "Landscape", self._pv_window.get())
        except Exception as exc:
            messagebox.showerror("PDF failed", str(exc))
            return False
        return self._open_preview(path, "Spectra PDF", "spectra.pdf",
                                  keep_page=True)

    def preview_metadata(self):
        parser = self._metadata_doc()
        if parser is None:
            return
        path = self._pdf_tmp("metadata.pdf")
        try:
            export_metadata_pdf(parser, path)
        except Exception as exc:
            messagebox.showerror("PDF failed", str(exc))
            return
        self.preview.clear_options()
        ttk.Label(self.preview.options, style="Hint.TLabel",
                  text=f"Metadata report for {os.path.basename(parser.path or '')}"
                  ).pack(side="left")
        if self._open_preview(path, "Metadata PDF", "metadata.pdf"):
            self._show_preview()

    def _open_preview(self, path, title, save_name, keep_page=False):
        """Show ``path`` in the preview, or in the system viewer if PyMuPDF
        is missing. Returns True when shown in-app."""
        if not HAVE_PDF:
            messagebox.showinfo(
                "PDF preview",
                "In-app preview needs the 'pymupdf' package "
                "(pip install pymupdf). Opening the PDF in your default "
                "viewer instead.")
            try:
                open_external(path)
            except Exception as exc:
                messagebox.showerror("Could not open", str(exc))
            return False
        try:
            self.preview.show(path, title, save_name, keep_page=keep_page)
        except Exception as exc:
            messagebox.showerror("Preview failed", str(exc))
            return False
        return True

    def _update_status(self):
        if not self.docs:
            self.status.config(text="No files loaded. Use Open to add spectra.")
            return
        n_spec, n_groups = getattr(self, "_counts", (0, 0))
        nf = len(self.docs)
        text = f"{nf} {'file' if nf == 1 else 'files'} loaded, "
        if n_spec:
            text += (f"{n_spec} {'spectrum' if n_spec == 1 else 'spectra'} "
                     f"ticked on {n_groups} "
                     f"{'panel' if n_groups == 1 else 'panels'}")
        else:
            text += "nothing ticked"
        notes = list(dict.fromkeys(self._view_notes))
        if notes and n_spec:
            text += "  ·  " + "; ".join(notes)
        self.status.config(text=text)

    # -- side panels ----------------------------------------------------
    def _current_tab(self):
        try:
            return self.nb.select()
        except tk.TclError:
            return ""

    def _refresh_side(self):
        tab = self._current_tab()
        if tab == str(self.tab_map):
            self._render_stage_map()
        elif tab == str(self.tab_images) and self.overlay_var.get():
            self._redraw_viewer()

    def _highlight_samples(self, parser):
        regs = self.sel_regions + self._ticked_regions()
        return {r.sample for r in regs if self.region_parser.get(id(r)) is parser}

    def _update_metadata(self):
        t = self.meta
        t.config(state="normal")
        t.delete("1.0", "end")
        regs = self.sel_regions
        if not regs:
            self.meta_hint.place(x=12, y=8)
            t.config(state="disabled")
            return
        self.meta_hint.place_forget()

        def head(txt):
            t.insert("end", txt + "\n", "h")

        def row(k, v):
            t.insert("end", k, ("row", "k"))
            t.insert("end", f"\t{v}\n", "row")

        parser = self.region_parser.get(id(regs[0]))
        if len(regs) == 1:
            base = parser.region_metadata(regs[0])

            def section(title, keys):
                items = [(k, base[k]) for k in keys if base.get(k)]
                if items:
                    head(title)
                    for k, v in items:
                        row(k, v)

            section("Sample", ["Sample", "Source file", "File format"])
            section("Acquisition", [
                "Date acquired", "Etch level", "Etch time (s)", "Instrument",
                "Operator", "Acquisition computer", "X-ray source", "Anode",
                "Photon energy (eV)", "Source power (W)", "Charge neutraliser",
                "Ion gun / sputtering"])
            r = regs[0]
            section("Region", [
                "Region", "Pass energy (eV)", "Lens mode", "Aperture",
                "BE start (eV)", "BE end (eV)", "Step (eV)", "Dwell (s)",
                "Points", "Quality"])
            if r.note:
                row("Note", r.note)
        else:
            self._metadata_many(regs, head, row)
        t.config(state="disabled")

    def _metadata_many(self, regs, head, row):
        """Details for several spectra: say what is the same for all of them
        once, and for settings that differ, which regions share each value."""
        rows = []
        for r in regs:
            p = self.region_parser.get(id(r))
            if p is not None:
                rows.append((r.name, p.region_metadata(r)))
        samples = sorted({(r.source, r.sample) for r in regs})
        head(f"{len(regs)} spectra" + (f" from {len(samples)} samples"
                                       if len(samples) > 1 else ""))
        ms = metasummary
        ident, _ = ms.summarise(rows, ms.IDENT_FIELDS)
        if ident:
            head("Sample" if len(samples) == 1 else "Shared")
            for k, v in ident:
                row(k, v)
        run, run_var = ms.summarise(rows, [f for f in ms.RUN_FIELDS
                                           if f != "Date acquired"])
        when = ms.date_range(rows)
        if run or when:
            head("Acquisition")
            if when:
                row("Date acquired", when)
            for k, v in run:
                row(k, v)
            for k, groups in run_var:              # e.g. two X-ray anodes
                for i, (v, labels) in enumerate(groups):
                    row(k if i == 0 else "",
                        f"{v}  ·  {ms.compact_labels(labels)}")
        common, varying = ms.summarise(rows, ms.SETTING_FIELDS)
        if common or varying:
            head("Scan settings")
            for k, v in common:
                row(k, f"{v}  ·  all")
            for k, groups in varying:
                for i, (v, labels) in enumerate(groups):
                    row(k if i == 0 else "",
                        f"{v}  ·  {ms.compact_labels(labels)}")
        if len(samples) == 1:
            head("Regions")
            row("", ms.compact_labels([r.name for r in regs], limit=12))
        else:
            head("Samples")
            for src, s in samples[:80]:
                rs = [r for r in regs if (r.source, r.sample) == (src, s)]
                label = s or src or "(unnamed)"
                if len(self.docs) > 1 and s:
                    label = f"{s} in {src}"
                row(label, ", ".join(dict.fromkeys(r.name for r in rs)))
            if len(samples) > 80:
                row("…", f"and {len(samples) - 80} more samples")

    # -- images tab -----------------------------------------------------
    def _refresh_info(self):
        """Show the Images / Stage-map notebook only when a loaded file has
        images or stage positions; otherwise Details gets the full height."""
        has_img = any(p.images for p in self.docs)
        has_pos = any(p.sample_positions() for p in self.docs)
        show = has_img or has_pos
        on = str(self.nb) in [str(x) for x in self.info_pane.panes()]
        if show and not on:
            self.info_pane.add(self.nb, weight=2)
        elif on and not show:
            self.info_pane.forget(self.nb)
        self.nb.tab(self.tab_images, state="normal" if has_img else "hidden")
        self.nb.tab(self.tab_map, state="normal" if has_pos else "hidden")
        if has_pos and not has_img:
            self.nb.select(self.tab_map)
        elif has_img:
            self.nb.select(self.tab_images)

    def _refresh_images(self):
        for w in self.thumb_inner.winfo_children():
            w.destroy()
        self._thumb_imgs = []
        items = [(p, b) for p in self.docs for b in p.images]
        if not items:
            self._cur_image = None
            self._redraw_viewer()
            self._refresh_info()
            return
        multi = len(self.docs) > 1
        for n, (p, blob) in enumerate(items, 1):
            cell = ttk.Frame(self.thumb_inner)
            cell.pack(side="top", padx=4, pady=4)
            thumb = self._make_thumb(p, blob)
            cmd = lambda p=p, b=blob: self._show_image(p, b)
            if thumb is not None:
                btn = ttk.Button(cell, image=thumb, command=cmd)
                btn.image = thumb
                self._thumb_imgs.append(thumb)
            else:
                btn = ttk.Button(cell, text="[image\nunavailable]", width=12,
                                 command=cmd)
            btn.pack()
            label = blob.name if not multi else \
                f"{blob.name} — {os.path.basename(p.path or '')}"
            ttk.Label(cell, text=label, font=("TkDefaultFont", 8),
                      wraplength=170).pack()
        if self._cur_image is None:
            self._redraw_viewer()
        self._refresh_info()

    def _make_thumb(self, parser, blob, size=(150, 100)):
        if not HAVE_PIL:
            return None
        jpeg = parser.extract_jpeg(blob)
        if jpeg is None:
            return None
        try:
            import io
            img = Image.open(io.BytesIO(jpeg))
            img.thumbnail(size)
            return ImageTk.PhotoImage(img)
        except Exception:
            return None

    def _show_image(self, parser, blob):
        self._cur_image = (parser, blob)
        self.nb.select(self.tab_images)
        self._redraw_viewer()

    def _redraw_viewer(self):
        for w in self.viewer.winfo_children():
            w.destroy()
        if not self._cur_image:
            self.overlay_cb.config(state="disabled")
            ttk.Label(self.viewer, padding=20,
                      text="Select an image above to view it.").pack()
            return
        parser, blob = self._cur_image
        positions = parser.sample_positions()
        self.overlay_cb.config(
            state="normal" if positions and HAVE_MPL else "disabled")
        if (self.overlay_var.get() and self.calib and HAVE_MPL and positions):
            self._render_photo_overlay(parser, blob, positions)
        else:
            self._render_plain_photo(parser, blob)

    def _render_plain_photo(self, parser, blob):
        parent = self.viewer
        if not HAVE_PIL:
            ttk.Label(parent, padding=20,
                      text="Pillow is not installed.\n\n  pip install pillow"
                      ).pack()
            return
        jpeg = parser.extract_jpeg(blob)
        if jpeg is None:
            ttk.Label(parent, padding=20,
                      text=f"Image cannot be displayed.\n\n{blob.note}").pack()
            return
        try:
            import io
            img = Image.open(io.BytesIO(jpeg))
            w = max(300, parent.winfo_width() - 10)
            h = max(200, parent.winfo_height() - 10)
            img.thumbnail((w, h))
            self._view_photo = ImageTk.PhotoImage(img)
            ttk.Label(parent, image=self._view_photo).pack()
        except Exception as exc:
            ttk.Label(parent, padding=20, text=f"Could not render:\n{exc}").pack()

    def _render_photo_overlay(self, parser, blob, positions):
        """Photo with analysis markers placed via the saved calibration."""
        parent = self.viewer
        jpeg = parser.extract_jpeg(blob)
        if jpeg is None or not HAVE_PIL:
            self._render_plain_photo(parser, blob)
            return
        import io
        img = Image.open(io.BytesIO(jpeg)).convert("RGB")
        w, h = img.size
        hot_samples = self._highlight_samples(parser)
        fig = Figure(figsize=(7.2, 4.6), dpi=100)
        ax = fig.add_subplot(111)
        ax.imshow(img, extent=[0, w, h, 0])   # top-left origin
        for sample, (x_mm, y_mm) in positions.items():
            px, py = stage_to_pixel(x_mm, y_mm, w, h, self.calib)
            hot = sample in hot_samples
            ax.scatter([px], [py], s=160 if hot else 90, facecolors="none",
                       edgecolors="#ff2d2d" if hot else "#19e0ff",
                       linewidths=2.2 if hot else 1.6, zorder=3)
            ax.annotate(sample, (px, py), textcoords="offset points",
                        xytext=(7, -7), fontsize=8,
                        color="#ff2d2d" if hot else "#19e0ff",
                        fontweight="bold" if hot else "normal")
        ax.set_xlim(0, w)
        ax.set_ylim(h, 0)
        ax.set_axis_off()
        fig.tight_layout()
        canvas = FigureCanvasTkAgg(fig, master=parent)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        canvas.draw()

    def _toggle_overlay(self):
        if self.overlay_var.get() and not self.calib:
            self.overlay_var.set(False)
            if messagebox.askyesno(
                    "Calibration needed",
                    "Overlaying markers on the photo needs a one-time camera "
                    "calibration. Set it now?"):
                self._toggle_calib()
            return
        self._redraw_viewer()

    def _toggle_calib(self):
        if self.calib_holder.winfo_ismapped():
            self._hide_calib()
            return
        for w in self.calib_holder.winfo_children():
            w.destroy()
        CalibrationPanel(self.calib_holder, self._calib_saved,
                         self._hide_calib, current=self.calib).pack(
            fill="x", padx=6, pady=4)
        self.calib_holder.pack(side="bottom", fill="x", before=self.viewer)

    def _hide_calib(self):
        self.calib_holder.pack_forget()

    def _calib_saved(self, calib):
        self.calib = calib
        self.overlay_var.set(True)
        self._redraw_viewer()

    # -- stage map tab --------------------------------------------------
    def _render_stage_map(self):
        parent = self.map_frame
        for w in parent.winfo_children():
            w.destroy()
        if not HAVE_MPL:
            ttk.Label(parent, padding=20,
                      text="matplotlib is required for the stage map.").pack()
            return
        focus = (self.sel_regions + self._ticked_regions())
        parser = (self.region_parser.get(id(focus[0])) if focus
                  else (self.docs[0] if self.docs else None))
        positions = parser.sample_positions() if parser else {}
        if not positions:
            ttk.Label(parent, padding=20,
                      text="Select or tick a spectrum to see where its "
                           "sample sat on the holder.").pack()
            return
        hot_samples = self._highlight_samples(parser)
        fig = Figure(figsize=(5.4, 3.6), dpi=100)
        ax = fig.add_subplot(111)
        for sample, (x, y) in positions.items():
            hot = sample in hot_samples
            ax.scatter([x], [y], s=120 if hot else 70,
                       c="#d33" if hot else "#3a6ea5",
                       edgecolors="black", zorder=3)
            ax.annotate(sample, (x, y), textcoords="offset points",
                        xytext=(6, 5), fontsize=8,
                        fontweight="bold" if hot else "normal")
        ax.set_xlabel("Stage X (mm)")
        ax.set_ylabel("Stage Y (mm)")
        ax.set_title("Analysis positions — "
                     + os.path.basename(parser.path or ""), fontsize=9)
        ax.grid(True, ls=":", alpha=0.5)
        ax.set_aspect("equal", adjustable="datalim")
        fig.tight_layout()
        canvas = FigureCanvasTkAgg(fig, master=parent)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        canvas.draw()

    # -- export ---------------------------------------------------------
    def _write_export(self, regions, fmt, include_tf=True):
        """Ask for a path and write regions as CSV/VAMAS. True on success."""
        regions = [r for r in regions if r.decodable and r.counts]
        if not regions:
            messagebox.showinfo("Export", "No decodable spectra to export.")
            return False
        if fmt == "csv":
            path = filedialog.asksaveasfilename(
                defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        else:
            path = filedialog.asksaveasfilename(
                defaultextension=".vms",
                filetypes=[("VAMAS", "*.vms"), ("VAMAS", "*.vamas")])
        if not path:
            return False
        parser = self.region_parser.get(id(regions[0]))
        inst = parser.instrument if parser else {}
        try:
            if fmt == "csv":
                n = export_csv(regions, path)
            else:
                n = export_vamas(
                    regions, path,
                    instrument=inst.get("Instrument", ""),
                    operator=inst.get("Acquisition computer", ""),
                    experiment_id=os.path.basename(
                        (parser.path if parser else "") or ""),
                    include_transmission=include_tf)
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))
            return False
        messagebox.showinfo("Exported", f"{n} spectra written to\n{path}")
        return True

    def export_ticked(self, fmt):
        regs = self._ticked_regions()
        if not regs:
            messagebox.showinfo("Export", "Tick the spectra you want to "
                                         "export first.")
            return
        self._write_export(regs, fmt)

    def open_export(self):
        if not any(p.regions for p in self.docs):
            messagebox.showinfo("Nothing to export",
                                "Open a spectra file first.")
            return
        ExportDialog(self.root, self)

    # -- metadata export ------------------------------------------------
    def _metadata_doc(self):
        """Which loaded file a metadata export should use (None = ask user)."""
        if not self.docs:
            messagebox.showinfo("No metadata", "Open a spectra file first.")
            return None
        if len(self.docs) == 1:
            return self.docs[0]
        owners = {id(p): p for p in
                  (self.node_map[i][0] for i in self.tree.selection()
                   if i in self.node_map)}
        if len(owners) == 1:
            return next(iter(owners.values()))
        messagebox.showinfo("Choose a file",
                            "Several files are loaded. Select a row belonging "
                            "to the file whose metadata you want, then try "
                            "again.")
        return None

    def export_meta_csv(self):
        parser = self._metadata_doc()
        if parser is None:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")],
            initialfile="metadata.csv")
        if not path:
            return
        try:
            n = export_metadata_csv(parser, path)
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))
            return
        messagebox.showinfo("Exported", f"Wrote metadata for {n} region(s) "
                                        f"to:\n{path}")

    def export_meta_pdf(self):
        parser = self._metadata_doc()
        if parser is None:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
            initialfile="metadata.pdf")
        if not path:
            return
        try:
            n = export_metadata_pdf(parser, path)
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))
            return
        messagebox.showinfo("Exported",
                            f"Wrote a metadata report for {n} sample(s) "
                            f"to:\n{path}")


class _ExportSection(ttk.Frame):
    """Region/level choices for one loaded file inside the export dialog."""

    def __init__(self, master, parser, checked, title=None):
        super().__init__(master)
        self.parser = parser
        self.profile = parser.depth_profile
        self.vars = []           # (BooleanVar, region): per-region ticks
        self.type_vars = {}      # region name -> BooleanVar (depth profiles)
        any_ticked = any(id(r) in checked for r in parser.regions)
        if title:
            ttk.Label(self, text=title, font=("", 10, "bold")).pack(
                anchor="w", pady=(10, 2))
        if self.profile.get("is_profile"):
            self._build_profile(any_ticked, checked)
        else:
            order, groups = [], {}
            for r in parser.regions:
                groups.setdefault(r.sample, []).append(r)
                if r.sample not in order:
                    order.append(r.sample)
            for sample in order:
                ttk.Label(self, text=sample or "Sample",
                          font=("", 9, "bold")).pack(anchor="w", pady=(8, 1))
                for r in groups[sample]:
                    on = (id(r) in checked) if any_ticked else r.decodable
                    v = tk.BooleanVar(value=bool(on and r.decodable))
                    ttk.Checkbutton(
                        self, variable=v,
                        state="normal" if r.decodable else "disabled",
                        text=f"   {r.name}  [{r.n_points} pts]"
                             f"{'' if r.decodable else '   (no data)'}"
                        ).pack(anchor="w")
                    self.vars.append((v, r))

    def _build_profile(self, any_ticked, checked):
        dp = self.profile
        ttk.Label(self, justify="left", font=("", 9),
                  text=(f"Depth profile: {dp['n_levels']} levels, "
                        f"{dp['regions_per_level']} regions/level\n"
                        f"Etch: {dp['etch_source']}\n"
                        f"Total etch time: {dp['total_etch_time']:g} s "
                        f"({dp['total_etch_time'] / 60.0:g} min)")
                  ).pack(anchor="w", pady=(4, 8))
        ttk.Label(self, text="Regions to include:",
                  font=("", 9, "bold")).pack(anchor="w")
        names = []
        for r in self.parser.regions:
            if r.name not in names:
                names.append(r.name)
        for name in names:
            on = (not any_ticked) or any(
                id(r) in checked for r in self.parser.regions if r.name == name)
            v = tk.BooleanVar(value=on)
            ttk.Checkbutton(self, variable=v, text=f"   {name}").pack(
                anchor="w")
            self.type_vars[name] = v

        ttk.Label(self, text="Levels to include:", font=("", 9, "bold")
                  ).pack(anchor="w", pady=(10, 1))
        self.level_mode = tk.StringVar(value="all")
        nlev = dp["n_levels"]
        for val, txt in [("all", f"All {nlev} levels"),
                         ("first", "First N levels"),
                         ("every", "Every Nth level"),
                         ("range", "Level range")]:
            ttk.Radiobutton(self, text=txt, value=val,
                            variable=self.level_mode).pack(anchor="w")
        spin = ttk.Frame(self)
        spin.pack(anchor="w", pady=4)
        ttk.Label(spin, text="N / step:").pack(side="left")
        self.n_spin = tk.IntVar(value=min(61, nlev))
        ttk.Spinbox(spin, from_=1, to=nlev, width=6,
                    textvariable=self.n_spin).pack(side="left", padx=4)
        ttk.Label(spin, text="range:").pack(side="left", padx=(10, 2))
        self.range_from = tk.IntVar(value=0)
        self.range_to = tk.IntVar(value=nlev - 1)
        ttk.Spinbox(spin, from_=0, to=nlev - 1, width=5,
                    textvariable=self.range_from).pack(side="left")
        ttk.Label(spin, text="–").pack(side="left")
        ttk.Spinbox(spin, from_=0, to=nlev - 1, width=5,
                    textvariable=self.range_to).pack(side="left")

    def selected_regions(self):
        if not self.profile.get("is_profile"):
            return [r for v, r in self.vars if v.get()]
        types = {n for n, v in self.type_vars.items() if v.get()}
        mode = self.level_mode.get()
        n = max(1, self.n_spin.get())
        lo, hi = self.range_from.get(), self.range_to.get()

        def level_ok(lvl):
            if lvl is None or mode == "all":
                return True
            if mode == "first":
                return lvl < n
            if mode == "every":
                return lvl % n == 0
            if mode == "range":
                return lo <= lvl <= hi
            return True

        return [r for r in self.parser.regions
                if r.decodable and r.name in types and level_ok(r.etch_level)]

    def set_all(self, value):
        for v, r in self.vars:
            if r.decodable:
                v.set(value)
        for v in self.type_vars.values():
            v.set(value)


class ExportDialog(tk.Toplevel):
    """Choose regions (or depth-profile levels) from every loaded file and a
    format. Pre-selects the currently ticked spectra."""

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.title("Export data")
        self.geometry("470x640")
        self.transient(master)
        self.grab_set()

        top = ttk.Frame(self)
        top.pack(fill="x", padx=12, pady=(12, 4))
        ttk.Label(top, text="Select regions to export:",
                  font=("", 10, "bold")).pack(side="left")
        ttk.Button(top, text="None", width=6,
                   command=lambda: self._set_all(False)).pack(side="right")
        ttk.Button(top, text="All", width=6,
                   command=lambda: self._set_all(True)).pack(side="right",
                                                             padx=4)

        canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        frame = ttk.Frame(canvas)
        sb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="top", fill="both", expand=True, padx=12)
        canvas.create_window((0, 0), window=frame, anchor="nw")
        frame.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        # mouse-wheel scrolling only while the pointer is over this list
        wheel = lambda e: canvas.yview_scroll(int(-e.delta / 120), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        self.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>")
                  if e.widget is self else None)

        multi = len(app.docs) > 1
        self.sections = []
        for p in app.docs:
            sec = _ExportSection(
                frame, p, app.checked,
                title=os.path.basename(p.path or "") if multi else None)
            sec.pack(fill="x", anchor="w")
            self.sections.append(sec)

        fmt_frame = ttk.LabelFrame(self, text="Format")
        fmt_frame.pack(fill="x", padx=12, pady=10)
        self.fmt = tk.StringVar(value="csv")
        ttk.Radiobutton(fmt_frame, text="CSV (.csv)", value="csv",
                        variable=self.fmt).pack(anchor="w", padx=8, pady=2)
        ttk.Radiobutton(fmt_frame, text="VAMAS / ISO 14976 (.vms)",
                        value="vamas", variable=self.fmt).pack(anchor="w",
                                                               padx=8, pady=2)
        self.incl_tf = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            fmt_frame, variable=self.incl_tf,
            text="Include spectrometer transmission function (VAMAS, "
                 "CasaXPS-compatible)").pack(anchor="w", padx=24, pady=(0, 4))

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(btns, text="Export", command=self.do_export).pack(
            side="right")
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(
            side="right", padx=6)

        if any(p.corruption["corrupted"] for p in app.docs):
            ttk.Label(self, foreground="#a00", wraplength=430, justify="left",
                      text="A loaded file's numeric data is corrupted, so its "
                           "regions cannot be exported. See the loader "
                           "warning.").pack(padx=12, pady=(0, 10))

    def _set_all(self, value):
        for s in self.sections:
            s.set_all(value)

    def do_export(self):
        chosen = [r for s in self.sections for r in s.selected_regions()]
        if not chosen:
            messagebox.showwarning("Nothing selected",
                                   "Select at least one region to export.")
            return
        if self.app._write_export(chosen, self.fmt.get(),
                                  include_tf=self.incl_tf.get()):
            self.destroy()


def main():
    fonts.register_process_fonts()          # before Tk enumerates fonts
    root = tk.Tk()
    app = Workspace(root)
    args = [a for a in sys.argv[1:] if a.lower().endswith(wbk.EXT)]
    if args:                                 # e.g. double-clicking a workbook
        root.after(300, lambda: app.open_workbook(os.path.abspath(args[0])))
    root.mainloop()


if __name__ == "__main__":
    main()
