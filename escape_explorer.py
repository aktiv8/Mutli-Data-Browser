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
import csv
import shutil
import tempfile
import json
import math

import tkinter as tk
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
from themes import (ThemeManager, THEME_NAMES, PRINT, mpl_rc,
                    make_box_images)
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


def region_label(r, with_source=False, show_name=True):
    """Concise label for a trace: depth level/time if a profile, else the
    sample (plus the region name when ``show_name``); prefixed with the file
    name when several files are loaded."""
    if r.etch_level is not None:
        base = (f"L{r.etch_level} ({r.etch_time:g} s)"
                if r.etch_time is not None else f"L{r.etch_level}")
    else:
        parts = [r.sample] if r.sample else []
        if show_name or not parts:
            parts.append(r.name)
        base = " ".join(parts)
    if with_source and r.source:
        base = f"{r.source} · {base}"
    return base if len(base) <= 44 else base[:41] + "…"


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
    Returns an ordered list of (label, [regions]); order is first appearance.
    """
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


def draw_stack(ax, regs, offset=0.6, norm="None", cursor=None,
               with_source=False, title="", compact=False):
    """Draw one panel: a single spectrum plain, several stacked by y offset."""
    normed = [[y / norm_factor(r, norm, cursor) for y in r.counts]
              for r in regs]
    stacked = len(regs) > 1
    spans = [(max(n) - min(n)) for n in normed if n]
    step = offset * (max(spans) if spans else 1.0) if stacked else 0.0
    label_every = max(1, math.ceil(len(regs) / 25))
    show_name = len({normalise_name(r.name) for r in regs}) > 1
    for i, (r, n) in enumerate(zip(regs, normed)):
        yoff = [y + i * step for y in n]
        line, = ax.plot(r.energy, yoff, lw=0.8 if compact else 0.9)
        if stacked and i % label_every == 0:
            ax.annotate(region_label(r, with_source, show_name),
                        (r.energy[0], yoff[0]),
                        textcoords="offset points", xytext=(4, 3),
                        fontsize=6 if compact else 7,
                        color=line.get_color())
    if norm == "At cursor" and cursor is not None:
        ax.axvline(cursor, color="#c00", ls="--", lw=0.8)
    r0 = regs[0]
    ax.set_title(title, fontsize=8 if compact else 11)
    if compact:
        ax.tick_params(labelsize=6)
    else:
        ax.set_xlabel(f"{r0.energy_label} ({r0.energy_units})")
        ylab = (f"{r0.count_label} ({r0.count_units})" if norm == "None"
                else f"{r0.count_label} (normalised)")
        ax.set_ylabel(ylab + (", stacked" if step else ""))
    if r0.energy_label.lower().startswith("binding"):
        ax.invert_xaxis()


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


class Workspace:
    """The single main window: file tree with tick boxes (left), stacked-plot
    area (top right) and a Metadata / Images / Stage-map notebook (bottom
    right). Ticked spectra are plotted; spectra sharing an element name (or
    x-range) are stacked with a y offset on one panel."""

    PANEL_CHOICES = ["Auto", "1", "2", "4", "6", "9", "12", "16"]
    TRACE_CHOICES = ["All", "3", "5", "10", "20", "50", "100"]
    NORM_MODES = ["None", "Max = 1", "Area = 1", "At cursor"]
    GROUP_MODES = {"Element name": "name", "Energy range": "range"}

    def __init__(self, root):
        self.root = root
        root.title("ESCApe Explorer")
        self.cfg = load_config()
        h = min(800, max(560, root.winfo_screenheight() - 110))
        w = min(1400, max(1000, root.winfo_screenwidth() - 40))
        root.geometry(self.cfg.get("geometry") or f"{w}x{h}")
        root.minsize(900, 560)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.themes = ThemeManager(root)
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
        self._thumb_imgs = []
        self._view_photo = None
        self._cur_image = None
        self.box_imgs, self.blank_img = make_box_images(self.palette)

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
        self.status = ttk.Label(self.root, anchor="w", relief="sunken",
                                text="Open a spectra file to begin.")
        self.status.pack(side="bottom", fill="x")
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
        self.meta_frame = ttk.LabelFrame(self.info_pane, text="Metadata")
        self.nb = ttk.Notebook(self.info_pane)
        self.info_pane.add(self.meta_frame, weight=3)
        self.info_pane.add(self.nb, weight=2)
        self._build_meta_table(self.meta_frame)
        self._build_side_tabs()
        self._panes = {"tree": self.tree_pane, "info": self.info_pane}
        self._hidden = {}           # pane name -> width when hidden
        self.root.bind("<F11>", lambda e: self.toggle_focus())

    def _build_toolbar(self):
        tb = ttk.Frame(self.root)
        tb.pack(side="top", fill="x", padx=4, pady=(4, 2))
        mb = ttk.Menubutton(tb, text="Open ▾")
        m = tk.Menu(mb, tearoff=0)
        m.add_command(label="Spectra file(s)…", command=self.open_files)
        m.add_command(label="Folder…", command=self.open_folder)
        m.add_separator()
        m.add_command(label="Close all files", command=self.close_all)
        mb["menu"] = m
        mb.pack(side="left")
        self.themes.register_menu(m)

        mb = ttk.Menubutton(tb, text="Export ▾")
        m = tk.Menu(mb, tearoff=0)
        m.add_command(label="Ticked spectra → CSV…",
                      command=lambda: self.export_ticked("csv"))
        m.add_command(label="Ticked spectra → VAMAS…",
                      command=lambda: self.export_ticked("vamas"))
        m.add_command(label="Choose regions / levels…", command=self.open_export)
        m.add_separator()
        m.add_command(label="Metadata → CSV…", command=self.export_meta_csv)
        m.add_command(label="Metadata → PDF…", command=self.export_meta_pdf)
        mb["menu"] = m
        mb.pack(side="left", padx=4)
        self.themes.register_menu(m)

        mb = ttk.Menubutton(tb, text="PDF ▾")
        m = tk.Menu(mb, tearoff=0)
        m.add_command(label="Preview spectra…", command=self.preview_spectra)
        m.add_command(label="Save spectra as PDF…", command=self.save_pdf)
        m.add_separator()
        m.add_command(label="Preview metadata…", command=self.preview_metadata)
        m.add_command(label="Save metadata as PDF…",
                      command=self.export_meta_pdf)
        mb["menu"] = m
        mb.pack(side="left")
        self.themes.register_menu(m)
        ttk.Button(tb, text="Metadata…", command=self.open_metadata).pack(
            side="left", padx=4)
        self.toolbar_right = ttk.Frame(tb)
        self.toolbar_right.pack(side="right")
        tcb = ttk.Combobox(self.toolbar_right, width=14, state="readonly",
                           values=THEME_NAMES, textvariable=self.theme_var)
        tcb.pack(side="right")
        tcb.bind("<<ComboboxSelected>>",
                 lambda e: self.set_theme(self.theme_var.get()))
        ttk.Label(self.toolbar_right, text="Theme").pack(side="right",
                                                         padx=(8, 4))
        self.focus_btn = ttk.Button(self.toolbar_right, text="Focus plot",
                                    command=self.toggle_focus)
        self.focus_btn.pack(side="right", padx=(6, 0))
        self.info_btn = ttk.Button(self.toolbar_right, text="Info ◨", width=7,
                                   command=lambda: self._toggle_pane("info"))
        self.info_btn.pack(side="right", padx=(6, 0))
        self.tree_btn = ttk.Button(self.toolbar_right, text="◧ Tree", width=7,
                                   command=lambda: self._toggle_pane("tree"))
        self.tree_btn.pack(side="right", padx=(6, 0))

    # -- theme --------------------------------------------------------------
    def _apply_mpl_theme(self):
        if HAVE_MPL:
            matplotlib.rcParams.update(mpl_rc(self.palette))

    def set_theme(self, name, save=True):
        """Switch the colour theme live (widgets, tick boxes, plots)."""
        if name not in THEME_NAMES:
            return
        self.theme_name = name
        self.theme_var.set(name)
        self.palette = self.themes.apply(name)
        self._apply_mpl_theme()
        self.box_imgs, self.blank_img = make_box_images(self.palette)
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
            self.root.after_idle(lambda: self._set_width(name, width))
        else:                                        # hide
            self._hidden[name] = max(150, pane.winfo_width())
            self.outer.forget(pane)

    def _set_width(self, name, width):
        try:
            if name == "tree":
                self.outer.sashpos(0, width)
            else:
                total = self.outer.winfo_width()
                self.outer.sashpos(len(self.outer.panes()) - 2, total - width)
        except tk.TclError:
            pass

    def toggle_focus(self):
        """Hide tree + info column so the plot fills the window (and back)."""
        if self._hidden:
            for name in list(self._hidden):
                self._toggle_pane(name)
            self.focus_btn.config(text="Focus plot")
        else:
            for name in ("tree", "info"):
                self._toggle_pane(name)
            self.focus_btn.config(text="Show panels")

    def _restore_layout(self):
        cfg = self.cfg
        try:
            self.outer.update_idletasks()
            total = self.outer.winfo_width()
            tree_w = int(cfg.get("sash_tree", 0)) or 0
            info_w = int(cfg.get("sash_info", 0)) or 0
            if not tree_w:
                tree_w = 360 if total >= 1300 else 300
            if not info_w:
                info_w = 380 if total >= 1300 else 300
            self.outer.sashpos(0, tree_w)
            self.outer.sashpos(1, total - info_w)
            h = self.info_pane.winfo_height()
            if h > 100:
                self.info_pane.sashpos(0, int(cfg.get("sash_info_v", 0)) or
                                       int(h * 0.55))
        except tk.TclError:
            pass

    def _on_close(self):
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
        cfg["group_by"] = self.group_var.get()
        cfg["norm"] = self.norm_var.get()
        cfg["offset"] = float(self.offset_var.get())
        cfg["panels_per_page"] = self.panels_var.get()
        cfg["traces_per_panel"] = self.traces_var.get()
        save_config(cfg)
        self.root.quit()

    def _build_tree_pane(self, parent):
        tb2 = ttk.Frame(parent)
        tb2.pack(side="top", fill="x", padx=4, pady=(2, 2))
        ttk.Button(tb2, text="Expand", width=8,
                   command=lambda: self._expand(True)).pack(side="left")
        ttk.Button(tb2, text="Collapse", width=8,
                   command=lambda: self._expand(False)).pack(side="left",
                                                            padx=4)
        ttk.Button(tb2, text="Untick all",
                   command=self.untick_all).pack(side="left")

        fb = ttk.Frame(parent)
        fb.pack(side="top", fill="x", padx=4, pady=(2, 4))
        ttk.Label(fb, text="Filter:").pack(side="left")
        self.filter_var = tk.StringVar()
        ent = ttk.Entry(fb, textvariable=self.filter_var)
        ent.pack(side="left", fill="x", expand=True, padx=4)
        ent.bind("<KeyRelease>", lambda e: self._populate_tree())
        ttk.Button(fb, text="Clear", width=6,
                   command=lambda: (self.filter_var.set(""),
                                    self._populate_tree())).pack(side="left")

        holder = ttk.Frame(parent)
        holder.pack(side="top", fill="both", expand=True)
        cols = ("detail", "pts", "pe", "etch")
        self.tree = ttk.Treeview(holder, columns=cols,
                                 show="tree headings", selectmode="extended")
        self.tree.heading("#0", text="Tick to plot")
        self.tree.heading("detail", text="Range / position")
        self.tree.heading("pts", text="Pts")
        self.tree.heading("pe", text="PE")
        self.tree.heading("etch", text="Etch")
        self.tree.column("#0", width=210, stretch=True, minwidth=120)
        self.tree.column("detail", width=95, anchor="w", stretch=False)
        self.tree.column("pts", width=42, anchor="e", stretch=False)
        self.tree.column("pe", width=38, anchor="e", stretch=False)
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
        # row 1: how spectra are combined
        ctl = ttk.Frame(parent)
        ctl.pack(side="top", fill="x", padx=6, pady=(4, 0))
        ttk.Label(ctl, text="Group by").pack(side="left")
        self.group_var = tk.StringVar(value=cfg.get("group_by", "Element name"))
        gb = ttk.Combobox(ctl, textvariable=self.group_var, width=14,
                          state="readonly", values=list(self.GROUP_MODES))
        gb.pack(side="left", padx=(2, 10))
        gb.bind("<<ComboboxSelected>>",
                lambda e: self._schedule_render(reset_page=True))

        ttk.Label(ctl, text="Normalise").pack(side="left")
        self.norm_var = tk.StringVar(value=cfg.get("norm", "None"))
        nb = ttk.Combobox(ctl, textvariable=self.norm_var, width=9,
                          state="readonly", values=self.NORM_MODES)
        nb.pack(side="left", padx=(2, 10))
        nb.bind("<<ComboboxSelected>>", lambda e: self._schedule_render())

        ttk.Label(ctl, text="Stack offset").pack(side="left")
        self.offset_var = tk.DoubleVar(value=float(cfg.get("offset", 0.6)))
        ttk.Scale(ctl, from_=0.0, to=3.0, variable=self.offset_var,
                  orient="horizontal", length=110,
                  command=lambda e: self._schedule_render()).pack(
            side="left", padx=4)

        self.reverse = tk.BooleanVar(value=False)
        ttk.Checkbutton(ctl, text="Reverse", variable=self.reverse,
                        command=self._schedule_render).pack(side="left",
                                                            padx=6)
        self.hint = ttk.Label(ctl, style="Hint.TLabel", font=("", 9))
        self.hint.pack(side="right", padx=8)

        # row 2: how many, and scrolling
        vw = ttk.Frame(parent)
        vw.pack(side="top", fill="x", padx=6, pady=(2, 0))
        ttk.Label(vw, text="Panels per page").pack(side="left")
        self.panels_var = tk.StringVar(value=cfg.get("panels_per_page", "Auto"))
        pb = ttk.Combobox(vw, textvariable=self.panels_var, width=5,
                          state="readonly", values=self.PANEL_CHOICES)
        pb.pack(side="left", padx=(2, 10))
        pb.bind("<<ComboboxSelected>>",
                lambda e: self._schedule_render(reset_page=True))

        ttk.Label(vw, text="Traces per panel").pack(side="left")
        self.traces_var = tk.StringVar(value=cfg.get("traces_per_panel", "All"))
        tbx = ttk.Combobox(vw, textvariable=self.traces_var, width=5,
                           values=self.TRACE_CHOICES)
        tbx.pack(side="left", padx=(2, 10))
        tbx.bind("<<ComboboxSelected>>", lambda e: self._on_traces_changed())
        tbx.bind("<Return>", lambda e: self._on_traces_changed())
        tbx.bind("<FocusOut>", lambda e: self._on_traces_changed())

        self.prev_btn = ttk.Button(vw, text="◀ Prev", width=7,
                                   command=self.prev_page, state="disabled")
        self.prev_btn.pack(side="left")
        self.next_btn = ttk.Button(vw, text="Next ▶", width=7,
                                   command=self.next_page, state="disabled")
        self.next_btn.pack(side="left", padx=(4, 8))
        self.page_lbl = ttk.Label(vw, text="")
        self.page_lbl.pack(side="left")
        self.count_lbl = ttk.Label(vw, text="")
        self.count_lbl.pack(side="right")

        self.fig = self.canvas = self.toolbar = None
        if HAVE_MPL:
            self.fig = Figure(figsize=(6, 3.5), dpi=100)
            self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
            self._make_toolbar()
            # trace-window slider (under the plot)
            self.trace_bar = ttk.Frame(parent)
            self.trace_bar.pack(side="bottom", fill="x", padx=6)
            self.trace_lbl = ttk.Label(self.trace_bar, text="", width=22)
            self.trace_lbl.pack(side="left")
            self.trace_var = tk.IntVar(value=0)
            self.trace_scale = ttk.Scale(
                self.trace_bar, from_=0, to=1, orient="horizontal",
                command=self._on_trace_scale, state="disabled")
            self.trace_scale.pack(side="left", fill="x", expand=True)
            ttk.Label(self.trace_bar, text="wheel: panels · Shift+wheel: traces",
                      font=("", 8)).pack(side="right", padx=(8, 0))
            self.panel_sb = ttk.Scrollbar(parent, orient="vertical",
                                          command=self._panel_scroll)
            self.panel_sb.pack(side="right", fill="y")
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
            ttk.Label(parent, justify="left", padding=20,
                      text="matplotlib is not installed, so spectra cannot be "
                           "plotted.\n\n    pip install matplotlib").pack()

    def _make_toolbar(self):
        """(Re)create the matplotlib navigation toolbar at the very bottom of
        the plot pane, coloured for the current theme."""
        if self.toolbar is not None:
            self.toolbar.destroy()
        self.toolbar = NavigationToolbar2Tk(self.canvas, self.plot_pane,
                                            pack_toolbar=False)
        kw = ({"before": self.trace_bar}
              if getattr(self, "trace_bar", None) else {})
        self.toolbar.pack(side="bottom", fill="x", **kw)
        self.themes.recolor_mpl_toolbar(self.toolbar)

    def _build_meta_table(self, parent):
        self.meta = ttk.Treeview(parent, columns=("field", "value"),
                                 show="headings", selectmode="extended",
                                 height=8)
        self.meta.heading("field", text="Field")
        self.meta.heading("value", text="Value")
        self.meta.column("field", width=125, stretch=False, minwidth=60)
        self.meta.column("value", width=200, stretch=True, minwidth=60)
        self.meta.tag_configure("head", font=("TkDefaultFont", 9, "bold"))
        sb = ttk.Scrollbar(parent, command=self.meta.yview)
        self.meta.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.meta.pack(side="left", expand=True, fill="both")
        self.meta.bind("<Control-c>", self._copy_meta)
        self.meta_hint = ttk.Label(
            parent, style="Muted.TLabel", wraplength=300, justify="left",
            text="Select a sample or spectrum in the tree to see its "
                 "acquisition metadata.\n\nTicking a box plots a spectrum; "
                 "selecting a row shows its details here.")
        self._update_metadata()

    def _copy_meta(self, _e=None):
        rows = self.meta.selection() or self.meta.get_children()
        text = "\n".join("\t".join(str(v) for v in self.meta.item(i, "values"))
                         for i in rows)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

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
        return ([("All supported spectra files", allpats)]
                + [(n, " ".join(p)) for n, p in fmts]
                + [("All files", "*.*")])

    def open_files(self):
        paths = filedialog.askopenfilenames(filetypes=self._open_filetypes())
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
        problems = []
        for path in paths:
            problems += self._add_file(path)
        if problems:
            shown = problems[:12]
            more = f"\n… and {len(problems) - 12} more" if len(problems) > 12 else ""
            messagebox.showwarning("Some files need attention",
                                   "\n\n".join(shown) + more)

    def _add_file(self, path):
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
        for r in parser.regions:
            self.region_parser[id(r)] = parser
        self._populate_tree()
        self._refresh_images()
        self._schedule_render(reset_page=True)
        problems = []
        if parser.corruption["corrupted"]:
            problems.append(f"{name}: {parser.corruption['message']}")
        problems += [f"{name}: {w}" for w in parser.warnings]
        return problems

    def _remove_doc(self, parser):
        for r in parser.regions:
            self.checked.discard(id(r))
            self.region_parser.pop(id(r), None)
        self.docs.remove(parser)
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
            iid = self.tree.insert(
                parent, "end", text=" " + node.label, open=opened, values=cols,
                image=self.box_imgs[state] if ids else self.blank_img)
            self.node_map[iid] = (parser, node)
            if ids:
                self.leaf_ids[iid] = ids
                self.box_state[iid] = state
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
            if self.box_state.get(iid) != st:
                self.box_state[iid] = st
                self.tree.item(iid, image=self.box_imgs[st])

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

    def _groups(self):
        groups = group_regions(self._ticked_regions(),
                               self.GROUP_MODES[self.group_var.get()])
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
            self.trace_scale.state(["!disabled"] if max_start > 0
                                   else ["disabled"])
        finally:
            self._scale_guard = False
        if limit and longest > limit:
            a = self.trace_start + 1
            self.trace_lbl.config(
                text=f"Traces {a}–{min(a + limit - 1, longest)} of {longest}")
        else:
            self.trace_lbl.config(text="All traces shown")

    def _render(self):
        self._render_job = None
        groups = self._groups()
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
        self.count_lbl.config(
            text="Nothing ticked" if not n_spec else
            f"{n_spec} spectr{'um' if n_spec == 1 else 'a'} in "
            f"{n_groups} panel{'' if n_groups == 1 else 's'}")
        self.prev_btn.config(
            state="normal" if self.panel_start > 0 else "disabled")
        self.next_btn.config(
            state="normal" if self.panel_start + npp < n_groups else "disabled")
        shown = len(chunk)
        self.page_lbl.config(
            text=(f"Panels {self.panel_start + 1}–{self.panel_start + shown} "
                  f"of {n_groups}") if n_groups > npp else "")
        self.hint.config(
            text="Click a panel to set the normalisation energy."
            if self.norm_var.get() == "At cursor" and n_spec else "")
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

    def _draw_page(self, fig, chunk, limit=None, start=0):
        """Draw one page of panels onto fig; returns {axes: group key}.
        ``limit``/``start`` show a window of long stacks."""
        rows, cols = _grid_dims(len(chunk))
        compact = len(chunk) > 1
        with_source = len(self.docs) > 1
        norm = self.norm_var.get()
        offset = float(self.offset_var.get())
        axmap = {}
        for i, (key, rs) in enumerate(chunk):
            ax = fig.add_subplot(rows, cols, i + 1)
            vis, span = rs, ""
            if limit and len(rs) > limit:
                s = min(start, len(rs) - limit)
                vis = rs[s:s + limit]
                span = f" ({s + 1}–{s + limit} of {len(rs)})"
            cur = None
            if norm == "At cursor":
                cur = self.cursors.get(key)
                if cur is None:
                    e = vis[0].energy
                    cur = self.cursors[key] = (e[0] + e[-1]) / 2.0
            r = vis[0]
            if len(rs) == 1:
                title = f"{r.sample} — {r.name}" if r.sample else r.name
            else:
                title = f"{key} — {len(vis)} spectra{span}"
            draw_stack(ax, vis, offset, norm, cur, with_source, title, compact)
            axmap[ax] = key
        fig.tight_layout()
        return axmap

    def _on_plot_click(self, event):
        if (self.norm_var.get() != "At cursor" or event.inaxes is None
                or event.xdata is None):
            return
        if str(getattr(self.toolbar, "mode", "")):
            return              # zoom / pan tool is active
        key = self._axmap.get(event.inaxes)
        if key is not None:
            self.cursors[key] = float(event.xdata)
            self._schedule_render()

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
        with matplotlib.rc_context(mpl_rc(PRINT)), PdfPages(path) as pdf:
            for p in range((len(groups) + per_page - 1) // per_page):
                fig = Figure(figsize=size, dpi=150)
                self._draw_page(fig, groups[p * per_page:(p + 1) * per_page],
                                limit, self.trace_start)
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
        cb.pack(side="left", padx=(2, 10))
        cb.bind("<<ComboboxSelected>>", lambda e: self._regen_spectra_preview())
        ttk.Label(pv.options, text="Page").pack(side="left")
        ob = ttk.Combobox(pv.options, textvariable=self._pv_orient, width=9,
                          state="readonly", values=["Landscape", "Portrait"])
        ob.pack(side="left", padx=(2, 10))
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
            self.status.config(text="Open a spectra file to begin.")
            return
        nreg = sum(len(p.regions) for p in self.docs)
        nimg = sum(len(p.images) for p in self.docs)
        self.status.config(
            text=f"{len(self.docs)} file(s) — {nreg} regions, {nimg} image(s) "
                 f"— {len(self.checked)} ticked")

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
        t.delete(*t.get_children())
        regs = self.sel_regions
        if not regs:
            self.meta_hint.place(relx=0.02, rely=0.02, relwidth=0.9)
            return
        self.meta_hint.place_forget()

        def head(txt):
            t.insert("", "end", values=(txt, ""), tags=("head",))

        def row(k, v):
            t.insert("", "end", values=(k, v))

        parser = self.region_parser.get(id(regs[0]))
        samples = sorted({(r.source, r.sample) for r in regs})
        if len(regs) == 1 or len(samples) == 1:
            base = parser.region_metadata(regs[0])
            order = ["Sample", "Source file", "File format", "Date acquired",
                     "Etch level", "Etch time (s)", "Instrument", "Operator",
                     "Acquisition computer", "X-ray source", "Anode",
                     "Photon energy (eV)", "Source power (W)",
                     "Charge neutraliser", "Ion gun / sputtering"]
            for k in order:
                if base.get(k):
                    row(k, base[k])
            if len(regs) == 1:
                r = regs[0]
                head("Region")
                for k in ["Region", "Pass energy (eV)", "Lens mode", "Aperture",
                          "BE start (eV)", "BE end (eV)", "Step (eV)",
                          "Dwell (s)", "Points", "Quality"]:
                    if base.get(k):
                        row(k, base[k])
                if r.note:
                    row("Note", r.note)
            else:
                head(f"{len(regs)} regions")
                for r in regs[:60]:
                    pe = f"PE {r.pass_energy:g} eV" if r.pass_energy else ""
                    row(r.name, pe)
                if len(regs) > 60:
                    row("…", f"and {len(regs) - 60} more")
        else:
            head(f"{len(regs)} spectra, {len(samples)} samples")
            for src, s in samples[:80]:
                rs = [r for r in regs if (r.source, r.sample) == (src, s)]
                label = s or src or "(unnamed)"
                if len(self.docs) > 1 and s:
                    label = f"{s} — {src}"
                row(label, ", ".join(dict.fromkeys(r.name for r in rs)))
            if len(samples) > 80:
                row("…", f"and {len(samples) - 80} more samples")

    # -- images tab -----------------------------------------------------
    def _refresh_images(self):
        for w in self.thumb_inner.winfo_children():
            w.destroy()
        self._thumb_imgs = []
        items = [(p, b) for p in self.docs for b in p.images]
        if not items:
            ttk.Label(self.thumb_inner, text="(no images loaded)",
                      padding=8).pack()
            self._cur_image = None
            self._redraw_viewer()
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
                      text="Click an image on the left, or select an image "
                           "node in the tree.").pack()
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
                      text="No stage positions recorded. Load a file (and "
                           "select or tick its spectra) to see where each "
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

    def open_metadata(self):
        if self._metadata_doc() is None:
            return
        choice = MetadataDialog(self.root)
        self.themes.recolor_tk(self.root)
        self.root.wait_window(choice)
        if choice.result == "csv":
            self.export_meta_csv()
        elif choice.result == "pdf":
            self.export_meta_pdf()

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


class MetadataDialog(tk.Toplevel):
    """Tiny chooser: export metadata as CSV or PDF."""

    def __init__(self, master):
        super().__init__(master)
        self.result = None
        self.title("Export metadata")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        ttk.Label(self, text="Export per-sample acquisition metadata as:",
                  padding=12).pack()
        btns = ttk.Frame(self)
        btns.pack(padx=12, pady=(0, 12))
        ttk.Button(btns, text="CSV", width=12,
                   command=lambda: self._pick("csv")).pack(side="left", padx=6)
        ttk.Button(btns, text="Formatted PDF", width=14,
                   command=lambda: self._pick("pdf")).pack(side="left", padx=6)

    def _pick(self, value):
        self.result = value
        self.destroy()


def main():
    root = tk.Tk()
    Workspace(root)
    root.mainloop()


if __name__ == "__main__":
    main()
