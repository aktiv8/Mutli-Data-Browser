"""Design tokens and colour themes for the whole UI: ttk widgets, classic Tk
widgets, tick-box swatches and matplotlib figures.

Chrome is deliberately quiet (cool greys, one desaturated accent used only for
focus, selection and primary actions); the **data palette** is the loud part.
Every theme except "System" uses ttk's fully recolourable ``clam`` engine;
"System" keeps the platform-native look. PDFs always render with
:data:`PRINT` (white paper) whatever theme is active.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

NATIVE = "System"
DEFAULT = "Light"

# Every palette must define every key (checked by tests/test_themes.py).
KEYS = ("bg", "panel", "fg", "muted", "accent", "entry", "select_bg",
        "select_fg", "border", "hint", "plot_bg", "plot_fg", "plot_grid",
        "cycle", "heat", "box_edge", "box_fill", "box_mark")

# Colour-blind-safe categorical data colours (Okabe-Ito derived); a
# luminance-lifted set for dark backgrounds.
DATA_LIGHT = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#B07A00",
              "#8A5CD1", "#6B6B6B"]
DATA_DARK = ["#5AB4EE", "#FF8A50", "#2FCB9E", "#E68FC0", "#F2B33D",
             "#B49CF2", "#B8C2CC"]
DATA_SOLARIZED = ["#268bd2", "#dc322f", "#859900", "#b58900", "#6c71c4",
                  "#2aa198", "#d33682", "#cb4b16"]
DATA_CONTRAST = ["#FFFF00", "#00FFFF", "#FF00FF", "#00FF00", "#FF8000",
                 "#FFFFFF", "#FF5555"]

# Sequential ramps for heat maps (low -> high intensity). Light backgrounds
# run light -> dark, dark backgrounds dark -> light, so weak signal always
# recedes into the plot background; lightness changes monotonically.
HEAT_LIGHT = ["#F3F7F9", "#BFDDE8", "#5FA8C7", "#1F6E9C", "#0B2F4F"]
HEAT_DARK = ["#0C1014", "#3B1F5E", "#8A2A6B", "#E0533F", "#FCC24A", "#FFF6D6"]
HEAT_MIDNIGHT = ["#0A1020", "#1D2A6B", "#2F6DB5", "#38BDF8", "#BDF0FF"]
HEAT_SOLARIZED = ["#FFFDF5", "#EEE8D5", "#93C5D8", "#268BD2", "#073642"]
HEAT_CONTRAST = ["#000000", "#3A00A0", "#D000D0", "#FFFF00", "#FFFFFF"]

PALETTES = {
    "Light": {
        "bg": "#ECEFF1", "panel": "#E1E6E9", "fg": "#1A2127", "muted": "#56636E",
        "accent": "#0F6B8C", "entry": "#FFFFFF", "select_bg": "#CFE6EE",
        "select_fg": "#0A2530", "border": "#C5CDD3", "hint": "#A8321F",
        "plot_bg": "#FFFFFF", "plot_fg": "#1A2127", "plot_grid": "#DDE3E7",
        "cycle": DATA_LIGHT, "heat": HEAT_LIGHT,
        "box_edge": "#56636E", "box_fill": "#FFFFFF",
        "box_mark": "#1A2127"},
    "Dark": {                                    # plot = recessed instrument screen
        "bg": "#12161A", "panel": "#1A2026", "fg": "#D7DEE4", "muted": "#8E9AA5",
        "accent": "#4CC2E0", "entry": "#0F1418", "select_bg": "#21495A",
        "select_fg": "#FFFFFF", "border": "#2A333B", "hint": "#FF8A80",
        "plot_bg": "#0C1014", "plot_fg": "#D7DEE4", "plot_grid": "#232B32",
        "cycle": DATA_DARK, "heat": HEAT_DARK,
        "box_edge": "#8E9AA5", "box_fill": "#0F1418",
        "box_mark": "#D7DEE4"},
    "Midnight": {
        "bg": "#0F172A", "panel": "#1E293B", "fg": "#E2E8F0", "muted": "#94A3B8",
        "accent": "#38BDF8", "entry": "#0B1224", "select_bg": "#1D4ED8",
        "select_fg": "#FFFFFF", "border": "#334155", "hint": "#FCA5A5",
        "plot_bg": "#0A1020", "plot_fg": "#E2E8F0", "plot_grid": "#1E2A44",
        "cycle": DATA_DARK, "heat": HEAT_MIDNIGHT,
        "box_edge": "#94A3B8", "box_fill": "#0B1224",
        "box_mark": "#E2E8F0"},
    "Solarized Light": {
        "bg": "#FDF6E3", "panel": "#EEE8D5", "fg": "#073642", "muted": "#586E75",
        "accent": "#268BD2", "entry": "#FFFDF5", "select_bg": "#D5E6EE",
        "select_fg": "#073642", "border": "#D3CBB6", "hint": "#C02A27",
        "plot_bg": "#FFFDF5", "plot_fg": "#073642", "plot_grid": "#E3DCC6",
        "cycle": DATA_SOLARIZED, "heat": HEAT_SOLARIZED,
        "box_edge": "#586E75", "box_fill": "#FFFDF5",
        "box_mark": "#073642"},
    "High contrast": {
        "bg": "#000000", "panel": "#101010", "fg": "#FFFFFF", "muted": "#CCCCCC",
        "accent": "#FFFF00", "entry": "#000000", "select_bg": "#FFFF00",
        "select_fg": "#000000", "border": "#FFFFFF", "hint": "#FF6060",
        "plot_bg": "#000000", "plot_fg": "#FFFFFF", "plot_grid": "#555555",
        "cycle": DATA_CONTRAST, "heat": HEAT_CONTRAST,
        "box_edge": "#FFFFFF", "box_fill": "#000000",
        "box_mark": "#FFFF00"},
    "System": {                                  # native ttk theme (Windows/macOS/Linux)
        "bg": "#F0F0F0", "panel": "#E6E6E6", "fg": "#1A1A1A", "muted": "#595959",
        "accent": "#0F6B8C", "entry": "#FFFFFF", "select_bg": "#CDE0F7",
        "select_fg": "#000000", "border": "#B5B5B5", "hint": "#AA0000",
        "plot_bg": "#FFFFFF", "plot_fg": "#222222", "plot_grid": "#CCCCCC",
        "cycle": DATA_LIGHT, "heat": HEAT_LIGHT,
        "box_edge": "#4A4A4A", "box_fill": "#FFFFFF",
        "box_mark": "#1A1A1A"},
}
THEME_NAMES = list(PALETTES)

# white "paper" style used for every PDF
PRINT = dict(PALETTES["Light"], plot_bg="#FFFFFF", plot_fg="#000000",
             plot_grid="#CCCCCC")

# Font family for matplotlib (set by the app once the bundled font is added)
MPL_FAMILY: str | None = None


# -- colour maths --------------------------------------------------------------
def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02X}" for c in rgb)


def luminance(h) -> float:
    """WCAG relative luminance of a #RRGGBB colour."""
    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b) -> float:
    """WCAG contrast ratio between two colours (1 = none, 21 = black/white)."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def mix(a, b, t) -> str:
    """Blend colour ``a`` toward ``b`` by fraction ``t`` (0 = a, 1 = b)."""
    ra, rb = _rgb(a), _rgb(b)
    return _hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


def ramp(colour, n, background):
    """``n`` shades of one hue, strongest first, fading toward the background.
    The fade grows with the stack (10 % per step, capped at 62 %, so every
    trace stays visible): a pair or trio is barely tinted, a long depth
    profile spans the whole range."""
    if n <= 1:
        return [colour]
    top = min(0.62, 0.10 * (n - 1))
    return [mix(colour, background, top * i / (n - 1)) for i in range(n)]


# -- colour scales (heat map intensity, and trace colours along a series) -------
# "Theme default" keeps the palette's own ``heat`` ramp / trace colours.
COLOUR_SCALES = {
    "Theme default": None, "Viridis": "viridis", "Plasma": "plasma",
    "Magma": "magma", "Inferno": "inferno", "Cividis": "cividis",
    "Turbo": "turbo", "Coolwarm": "coolwarm", "Greys": "Greys",
    "Blues": "Blues", "YlOrRd": "YlOrRd",
}
SCALE_NAMES = list(COLOUR_SCALES)
MIN_TRACE_CONTRAST = 2.0       # trace colour vs plot background (WCAG ratio)


def scale_colourmap(name, reverse, pal):
    """matplotlib Colormap for a scale name ("Theme default" = the palette's
    ``heat`` ramp). Always a private copy, so callers may ``set_bad``."""
    import copy
    import matplotlib
    from matplotlib.colors import LinearSegmentedColormap
    key = COLOUR_SCALES.get(name)
    if key is None:
        cmap = LinearSegmentedColormap.from_list("heat", list(pal["heat"]))
    else:
        cmap = copy.copy(matplotlib.colormaps[key])
    return cmap.reversed() if reverse else cmap


def _legible(colour, bg, fg, need=MIN_TRACE_CONTRAST):
    """``colour``, nudged toward ``fg`` until it stands out from ``bg``."""
    for step in range(11):
        c = mix(colour, fg, step / 10)
        if contrast(c, bg) >= need:
            return c
    return fg


def scale_colours(name, reverse, n, pal):
    """``n`` trace colours spread along a scale, or None for "Theme default"
    (the caller then keeps the theme's own trace colours).

    The ends of a scale that would vanish into the plot background (the pale
    end of Greys on white, the dark end of Magma on a dark plot) are trimmed,
    and any colour still too faint (the pale middle of Coolwarm) is nudged
    toward the foreground colour, so every trace stays visible. A lone trace
    takes the middle of the scale."""
    key = COLOUR_SCALES.get(name)
    if key is None or n < 1:
        return None
    import matplotlib
    cmap = matplotlib.colormaps[key]
    bg, fg = pal["plot_bg"], pal["plot_fg"]

    def at(t):
        return _hex(cmap(t)[:3])

    lo, hi = 0.0, 1.0
    while lo < 0.5 and contrast(at(lo), bg) < MIN_TRACE_CONTRAST:
        lo += 0.02
    while hi > 0.5 and contrast(at(hi), bg) < MIN_TRACE_CONTRAST:
        hi -= 0.02
    ts = ([(lo + hi) / 2] if n == 1
          else [lo + (hi - lo) * i / (n - 1) for i in range(n)])
    if reverse:
        ts = ts[::-1]
    return [_legible(at(t), bg, fg) for t in ts]


# -- axis colour (frame, ticks, labels) -----------------------------------------
AXIS_CHOICES = ["Theme default", "Black", "White", "Custom…"]
MIN_AXIS_CONTRAST = 3.0


def with_axis_colour(pal, choice, custom=None):
    """``(palette, note)``: a copy of ``pal`` whose frame / tick colour
    (``muted``) and axis text colour (``plot_fg``) are the chosen colour.

    "Theme default" (or an unset custom colour) returns the palette as is. A
    colour that would be hard to see on this plot background falls back to
    the theme colours, with ``note`` saying so."""
    colour = {"Black": "#000000", "White": "#FFFFFF",
              "Custom…": custom}.get(choice)
    if not colour:
        return pal, ""
    if contrast(colour, pal["plot_bg"]) < MIN_AXIS_CONTRAST:
        return pal, (f"{choice.rstrip('…').lower()} axes would be hard to "
                     f"see on this background: using the theme colour")
    return dict(pal, muted=colour, plot_fg=colour), ""


def mpl_rc(pal, family=None, style=None) -> dict:
    """matplotlib rcParams for a palette (use with ``matplotlib.rc_context``).
    ``style`` (a ``plotstyle`` dict) layers the user's fonts, sizes, ticks,
    grid and frame over the theme's colours."""
    fam = family or MPL_FAMILY
    rc = {
        "figure.facecolor": pal["plot_bg"], "savefig.facecolor": pal["plot_bg"],
        "axes.facecolor": pal["plot_bg"], "axes.edgecolor": pal["muted"],
        "axes.labelcolor": pal["plot_fg"], "axes.titlecolor": pal["plot_fg"],
        "text.color": pal["plot_fg"], "xtick.color": pal["muted"],
        "ytick.color": pal["muted"], "grid.color": pal["plot_grid"],
        "legend.facecolor": pal["plot_bg"], "legend.edgecolor": pal["plot_grid"],
        # design: open frame, small quiet type
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.linewidth": 0.8, "xtick.major.width": 0.8,
        "ytick.major.width": 0.8, "xtick.major.size": 3.5,
        "ytick.major.size": 3.5, "axes.titlelocation": "left",
        "axes.titleweight": "bold", "axes.titlesize": 10,
        "axes.labelsize": 9, "xtick.labelsize": 8, "ytick.labelsize": 8,
        "font.size": 9, "lines.linewidth": 1.1,
    }
    if fam:
        rc["font.family"] = [fam, "DejaVu Sans"]
    if style is not None:
        import plotstyle
        rc.update(plotstyle.rc_overrides(style, fam))
    try:
        from cycler import cycler
        rc["axes.prop_cycle"] = cycler(color=list(pal["cycle"]))
    except Exception:
        pass
    return rc


# -- tick boxes / swatches --------------------------------------------------------
def _fill(img, colour, x0, y0, x1, y1, rounded=True):
    """Filled rectangle [x0,x1) x [y0,y1); corners trimmed when ``rounded``."""
    for y in range(y0, y1):
        if rounded and y in (y0, y1 - 1):
            img.put(colour, to=(x0 + 1, y, x1 - 1, y + 1))
        else:
            img.put(colour, to=(x0, y, x1, y + 1))


class SwatchCache:
    """Tree tick boxes drawn as small rounded squares.

    A ticked spectrum is a *filled swatch in its trace colour* (so the tree is
    also the plot's legend); unticked is an outline; a partly ticked parent
    shows a bar. Images are generated lazily and cached per colour.
    """

    def __init__(self, pal):
        self.pal = pal
        self._cache = {}
        self.blank = tk.PhotoImage(width=16, height=16)

    def get(self, state, colour=None):
        """state: 0 none, 1 some, 2 all. ``colour`` only matters for state 2."""
        key = (state, colour if state == 2 else None)
        img = self._cache.get(key)
        if img is None:
            img = self._cache[key] = self._build(*key)
        return img

    def _build(self, state, colour):
        p = self.pal
        img = tk.PhotoImage(width=16, height=16)
        if state == 2 and colour:                # ticked spectrum: trace colour
            _fill(img, colour, 2, 2, 14, 14)
            return img
        _fill(img, p["box_edge"], 2, 2, 14, 14)
        _fill(img, p["box_fill"], 3, 3, 13, 13, rounded=False)
        if state == 2:                           # parent, everything ticked
            _fill(img, p["box_mark"], 5, 5, 11, 11, rounded=False)
        elif state == 1:                         # parent, some ticked
            _fill(img, p["box_mark"], 5, 7, 11, 9, rounded=False)
        return img


def make_box_images(pal):
    """Legacy helper: ([unticked, partial, ticked], blank) neutral swatches."""
    sw = SwatchCache(pal)
    return [sw.get(0), sw.get(1), sw.get(2)], sw.blank


# -- theme manager ---------------------------------------------------------------
class ThemeManager:
    """Applies a named palette to a Tk application."""

    def __init__(self, root):
        self.root = root
        self.style = ttk.Style(root)
        self.native = self.style.theme_use()
        self.name = DEFAULT
        self.palette = dict(PALETTES[DEFAULT])
        self._menus = []
        self._defaults = self._probe_defaults()

    def register_menu(self, menu):
        self._menus.append(menu)

    # -- ttk -------------------------------------------------------------
    def apply(self, name):
        """Switch theme; returns the palette (with the widget bg resolved)."""
        if name not in PALETTES:
            name = DEFAULT
        pal = dict(PALETTES[name])
        self.name = name
        st = self.style
        if name == NATIVE:
            st.theme_use(self.native)
            pal["bg"] = st.lookup("TFrame", "background") or pal["bg"]
            pal["fg"] = st.lookup("TLabel", "foreground") or pal["fg"]
        else:
            st.theme_use("clam")
            self._style_clam(pal)
        st.configure("Hint.TLabel", foreground=pal["hint"])
        st.configure("Muted.TLabel", foreground=pal["muted"])
        try:                                     # named font made by the app
            st.configure("Section.TLabel", font="AppSection")
        except tk.TclError:
            pass
        self.palette = pal
        self.root.configure(bg=(self._defaults["frame"][0]
                                if name == NATIVE else pal["bg"]))
        self.recolor_tk(self.root)
        return pal

    def _row_height(self):
        try:
            import tkinter.font as tkfont
            return tkfont.nametofont("TkDefaultFont").metrics("linespace") + 9
        except Exception:
            return 22

    def _style_clam(self, p):
        st = self.style
        bg, panel, fg, muted, entry, border = (
            p["bg"], p["panel"], p["fg"], p["muted"], p["entry"], p["border"])
        acc = p["accent"]
        st.configure(".", background=bg, foreground=fg, fieldbackground=entry,
                     bordercolor=border, lightcolor=bg, darkcolor=bg,
                     troughcolor=panel, focuscolor=acc,
                     selectbackground=p["select_bg"],
                     selectforeground=p["select_fg"], insertcolor=fg)
        st.map(".", foreground=[("disabled", muted)],
               background=[("disabled", bg)])
        # buttons: flat, one padding rhythm (10 x 5)
        st.configure("TButton", background=panel, foreground=fg,
                     padding=(10, 4), borderwidth=1, relief="flat",
                     bordercolor=border)
        st.map("TButton", background=[("pressed", p["select_bg"]),
                                      ("active", border)],
               foreground=[("disabled", muted)],
               bordercolor=[("focus", acc)])
        st.configure("Tool.TButton", background=bg, padding=(9, 4),
                     borderwidth=0)
        st.map("Tool.TButton", background=[("pressed", p["select_bg"]),
                                           ("active", panel)])
        st.configure("Toggle.TButton", background=bg, padding=(9, 4),
                     borderwidth=0)
        st.map("Toggle.TButton",
               background=[("pressed", p["select_bg"]), ("active", panel)])
        st.configure("Tool.TMenubutton", background=bg, foreground=fg,
                     padding=(9, 4), arrowcolor=muted, borderwidth=0)
        st.map("Tool.TMenubutton", background=[("active", panel)])
        st.configure("TMenubutton", background=panel, foreground=fg,
                     arrowcolor=muted, padding=(8, 4))
        st.map("TMenubutton", background=[("active", border)])
        st.configure("TEntry", fieldbackground=entry, foreground=fg,
                     insertcolor=fg, padding=(4, 3), bordercolor=border)
        st.map("TEntry", bordercolor=[("focus", acc)])
        st.configure("TCombobox", fieldbackground=entry, background=panel,
                     foreground=fg, arrowcolor=muted, padding=(4, 3),
                     bordercolor=border, selectbackground=entry,
                     selectforeground=fg)
        st.map("TCombobox", fieldbackground=[("readonly", entry)],
               foreground=[("readonly", fg)],
               selectbackground=[("readonly", entry)],
               selectforeground=[("readonly", fg)],
               bordercolor=[("focus", acc)])
        st.configure("TSpinbox", fieldbackground=entry, foreground=fg,
                     arrowcolor=muted)
        for w in ("TCheckbutton", "TRadiobutton"):
            st.configure(w, background=bg, foreground=fg,
                         indicatorbackground=entry, indicatorforeground=fg)
            st.map(w, background=[("active", bg)],
                   indicatorbackground=[("selected", acc), ("active", entry)],
                   foreground=[("disabled", muted)])
        st.configure("TLabelframe", background=bg, bordercolor=border)
        st.configure("TLabelframe.Label", background=bg, foreground=muted)
        st.configure("TNotebook", background=bg, bordercolor=border)
        st.configure("TNotebook.Tab", background=bg, foreground=muted,
                     padding=(12, 5), borderwidth=0)
        st.map("TNotebook.Tab", background=[("selected", bg)],
               foreground=[("selected", fg)])
        # tree + tables: airy rows, quiet flat headings
        st.configure("Treeview", background=entry, fieldbackground=entry,
                     foreground=fg, bordercolor=border, rowheight=self._row_height(),
                     borderwidth=0)
        st.map("Treeview", background=[("selected", p["select_bg"])],
               foreground=[("selected", p["select_fg"])])
        st.configure("Treeview.Heading", background=bg, foreground=muted,
                     bordercolor=border, relief="flat", padding=(6, 4))
        st.map("Treeview.Heading", background=[("active", panel)])
        for o in ("Vertical", "Horizontal"):
            st.configure(f"{o}.TScrollbar", background=panel, troughcolor=bg,
                         bordercolor=bg, arrowcolor=muted, relief="flat",
                         gripcount=0)
            st.map(f"{o}.TScrollbar", background=[("active", border)])
        st.configure("Horizontal.TScale", background=acc, troughcolor=border,
                     bordercolor=border, lightcolor=acc, darkcolor=acc)
        st.configure("Toolbutton", background=bg, padding=(9, 4),
                     borderwidth=0, relief="flat")
        st.map("Toolbutton", background=[("selected", p["select_bg"]),
                                         ("pressed", p["select_bg"]),
                                         ("active", panel)],
               foreground=[("selected", p["select_fg"])])
        # thin sashes without grip dots
        st.configure("Sash", sashthickness=5, gripcount=0, background=border,
                     bordercolor=border, lightcolor=border, darkcolor=border)
        st.configure("TPanedwindow", background=border)
        st.configure("TSeparator", background=border)
        st.configure("Status.TLabel", background=bg, foreground=muted,
                     padding=(10, 5))
        st.configure("Strong.TLabel", font="TkDefaultFont")

    # -- classic Tk widgets ------------------------------------------------
    def _probe_defaults(self):
        """Platform-native colours of classic Tk widgets (to restore System)."""
        d = {}
        for key, cls in (("frame", tk.Frame), ("label", tk.Label),
                         ("text", tk.Text)):
            w = cls(self.root)
            d[key] = (w.cget("bg"), w.cget("fg") if key != "frame" else "")
            w.destroy()
        return d

    def recolor_tk(self, widget):
        p, native, d = self.palette, self.name == NATIVE, self._defaults
        for child in widget.winfo_children():
            cls = child.winfo_class()
            try:
                if cls in ("Frame", "Toplevel", "Canvas"):
                    child.configure(bg=d["frame"][0] if native else p["bg"])
                elif cls in ("Label", "Button", "Checkbutton", "Radiobutton"):
                    child.configure(bg=d["label"][0] if native else p["bg"],
                                    fg=d["label"][1] if native else p["fg"])
                elif cls == "Text":
                    child.configure(bg=d["text"][0] if native else p["entry"],
                                    fg=d["text"][1] if native else p["fg"],
                                    insertbackground=d["text"][1] if native
                                    else p["fg"])
                elif cls == "TCombobox":
                    self._restyle_combobox(child)
            except tk.TclError:
                pass
            self.recolor_tk(child)
        for m in self._menus:
            try:
                if native:
                    m.configure(bg=d["label"][0], fg=d["label"][1],
                                activebackground=p["select_bg"],
                                activeforeground=p["select_fg"])
                else:
                    m.configure(bg=p["panel"], fg=p["fg"],
                                activebackground=p["select_bg"],
                                activeforeground=p["select_fg"],
                                relief="flat", borderwidth=0)
            except tk.TclError:
                pass

    def _restyle_combobox(self, cb):
        p = self.palette
        try:
            pop = cb.tk.call("ttk::combobox::PopdownWindow", str(cb))
            cb.tk.call(f"{pop}.f.l", "configure", "-background", p["entry"],
                       "-foreground", p["fg"], "-selectbackground",
                       p["select_bg"], "-selectforeground", p["select_fg"])
        except tk.TclError:
            pass

    def recolor_mpl_toolbar(self, toolbar):
        """Make the matplotlib Tk toolbar (and its icons) match the theme."""
        p = self.palette
        native = self.name == NATIVE
        d = self._defaults

        def cfg(widget, **opts):          # tolerate options a widget lacks
            for k, v in opts.items():
                try:
                    widget.configure(**{k: v})
                except tk.TclError:
                    pass

        bg = d["frame"][0] if native else p["bg"]
        fg = d["label"][1] if native else p["fg"]
        cfg(toolbar, bg=bg)
        for b in getattr(toolbar, "_buttons", {}).values():
            cfg(b, bg=bg, fg=fg, activebackground=p["panel"],
                highlightbackground=bg, selectcolor=p["panel"],
                relief="flat", borderwidth=0)
            try:
                toolbar._set_image_for_button(b)      # recolours the icon
            except Exception:
                pass
        for w in toolbar.winfo_children():
            cls = w.winfo_class()
            if cls == "Frame":                        # separators
                cfg(w, bg=p["border"])
            elif cls == "Label":                      # spacer + coordinate readout
                cfg(w, bg=bg, fg=p["muted"] if not native else fg)
