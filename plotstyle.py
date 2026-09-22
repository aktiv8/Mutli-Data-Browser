"""Plot style: one declarative list of the things a user may change about how
a spectrum plot looks (fonts, lines, ticks, grid, frame, legend, titles,
axis ranges, export size).

``FIELDS`` is the single source of truth. From it come

* the controls of the *Plot style* dialog (``plotstyle_ui``),
* validation of anything read back from disk (``sanitise``),
* the matplotlib rcParams (``rc_overrides``) and the per-panel helpers that
  ``plots`` calls, so the screen, the PDF/PowerPoint figure pages and the
  PNG/SVG export all draw from the same style dictionary.

A *style* is a plain ``{key: value}`` dict holding every field (see
``resolve``). It is stored in the user's config, in the workbook state and in
each saved figure. No Tk here, and matplotlib is only imported inside the
functions that need it, so this module is unit-testable on its own.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

THEME_FONT = "Theme font"


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str                    # choice | float | int | bool | text | optfloat
    default: object
    group: str
    tip: str = ""
    choices: tuple = ()          # for kind == "choice"
    lo: float | None = None      # numeric bounds (inclusive)
    hi: float | None = None
    step: float | None = None    # spinbox increment
    unit: str = ""


LINE_STYLES = {"Solid": "-", "Dashed": "--", "Dotted": ":",
               "Dash-dot": "-.", "None": "None"}
MARKERS = {"None": None, "Circle": "o", "Square": "s", "Triangle": "^",
           "Diamond": "D", "Plus": "+", "Cross": "x", "Dot": "."}
GRID_MODES = ("Off", "Vertical", "Horizontal", "Both")
Y_UNITS = ("Auto", "Counts", "Counts / s", "Arbitrary units (a.u.)", "None")
LEGEND_LOCS = ("best", "upper right", "upper left", "lower right",
               "lower left", "center right", "center left")
FONTS = (THEME_FONT, "DejaVu Sans", "Arial", "Helvetica", "Calibri",
         "Times New Roman", "Georgia", "Courier New")

FIELDS: tuple[Field, ...] = (
    # -- text --------------------------------------------------------------
    Field("font", "Font", "choice", THEME_FONT, "Text",
          "Typeface for every label. A font that is not installed falls "
          "back to the theme font.", choices=FONTS),
    Field("font_size", "Axis label size", "int", 9, "Text",
          lo=5, hi=32, step=1, unit="pt"),
    Field("title_size", "Panel title size", "int", 10, "Text",
          lo=5, hi=36, step=1, unit="pt"),
    Field("tick_size", "Tick and note size", "int", 8, "Text",
          "Tick numbers, trace labels, the legend and peak markers.",
          lo=4, hi=28, step=1, unit="pt"),
    Field("title_bold", "Bold panel titles", "bool", True, "Text"),
    # -- traces ------------------------------------------------------------
    Field("line_width", "Line width", "float", 1.1, "Traces",
          lo=0.2, hi=6.0, step=0.1, unit="pt"),
    Field("line_style", "Line style", "choice", "Solid", "Traces",
          "'None' draws markers only.", choices=tuple(LINE_STYLES)),
    Field("marker", "Marker", "choice", "None", "Traces",
          choices=tuple(MARKERS)),
    Field("marker_size", "Marker size", "float", 3.0, "Traces",
          lo=0.5, hi=16, step=0.5, unit="pt"),
    Field("fill_under", "Fill under each trace", "bool", False, "Traces",
          "Shade from each trace down to its own lowest point."),
    Field("fill_alpha", "Fill opacity", "float", 0.15, "Traces",
          lo=0.02, hi=0.9, step=0.05),
    # -- axes --------------------------------------------------------------
    Field("frame", "Frame", "choice", "Open", "Axes",
          "Open: left and bottom lines only. Box: all four sides.",
          choices=("Open", "Box")),
    Field("spine_width", "Axis line width", "float", 0.8, "Axes",
          lo=0.2, hi=3.0, step=0.1, unit="pt"),
    Field("tick_direction", "Tick direction", "choice", "out", "Axes",
          choices=("out", "in", "inout")),
    Field("tick_length", "Tick length", "float", 3.5, "Axes",
          lo=0.0, hi=12.0, step=0.5, unit="pt"),
    Field("minor_ticks", "Minor ticks", "bool", False, "Axes"),
    Field("grid", "Grid", "choice", "Off", "Axes", choices=GRID_MODES),
    Field("grid_style", "Grid line style", "choice", "Dotted", "Axes",
          choices=("Solid", "Dashed", "Dotted")),
    Field("grid_alpha", "Grid opacity", "float", 0.5, "Axes",
          lo=0.05, hi=1.0, step=0.05),
    Field("y_scale", "Y axis scale", "choice", "Linear", "Axes",
          "Log shows weak peaks alongside strong ones on a survey; values "
          "at or below zero are not shown.", choices=("Linear", "Log")),
    # -- titles and labels ---------------------------------------------------
    Field("show_title", "Panel titles", "bool", True, "Labels"),
    Field("show_subtitle", "Sample / count subtitle", "bool", True, "Labels"),
    Field("title_text", "Title (every panel)", "text", "", "Labels",
          "Replaces the automatic panel title. Leave empty for the "
          "element name."),
    Field("xlabel", "X axis label", "text", "", "Labels",
          "Empty keeps 'Binding Energy (eV)'."),
    Field("ylabel", "Y axis label", "text", "", "Labels",
          "Empty keeps the instrument's own label."),
    Field("y_units", "Y units", "choice", "Auto", "Labels",
          "Unit shown in the y label, the scale bar and the colour bar. "
          "Auto uses the file's own unit.", choices=Y_UNITS),
    # -- ranges --------------------------------------------------------------
    Field("x_min", "Energy from", "optfloat", None, "Ranges",
          "Lowest energy shown, in the units of the energy axis (empty = "
          "automatic). Panels the window does not reach keep their own "
          "range.", unit="eV"),
    Field("x_max", "Energy to", "optfloat", None, "Ranges",
          "Highest energy shown (empty = automatic).", unit="eV"),
    Field("y_min", "Intensity from", "optfloat", None, "Ranges",
          "Stack view only, on every panel (empty = automatic)."),
    Field("y_max", "Intensity to", "optfloat", None, "Ranges",
          "Stack view only, on every panel (empty = automatic)."),
    # -- legend --------------------------------------------------------------
    Field("labels", "Trace labels", "choice", "End labels", "Legend",
          "End labels: name at the right-hand end of each trace. Legend: a "
          "legend box. None: no labels.",
          choices=("End labels", "Legend", "None")),
    Field("legend_loc", "Legend position", "choice", "best", "Legend",
          choices=LEGEND_LOCS),
    Field("legend_frame", "Legend frame", "bool", False, "Legend"),
    # -- figure (export) -----------------------------------------------------
    Field("fig_width", "Image width", "float", 0.0, "Figure",
          "Used by Save plot image. 0 = 8 in. Reports and slides use their "
          "own page size.", lo=0.0, hi=40.0, step=0.5, unit="in"),
    Field("fig_height", "Image height", "float", 0.0, "Figure",
          "0 = 5 in.", lo=0.0, hi=40.0, step=0.5, unit="in"),
    Field("fig_dpi", "Image resolution", "int", 300, "Figure",
          lo=50, hi=1200, step=50, unit="dpi"),
)

BY_KEY = {f.key: f for f in FIELDS}
GROUPS = tuple(dict.fromkeys(f.group for f in FIELDS))
DEFAULTS = {f.key: f.default for f in FIELDS}


# -- presets ------------------------------------------------------------------
BUILTIN_PRESETS: dict[str, dict] = {
    "Default": {},
    "Journal (compact)": {
        "font_size": 8, "title_size": 9, "tick_size": 7, "line_width": 0.8,
        "spine_width": 0.6, "tick_direction": "in", "tick_length": 3.0,
        "minor_ticks": True, "title_bold": False, "frame": "Box",
        "fig_width": 3.4, "fig_height": 2.7, "fig_dpi": 600},
    "Presentation (large)": {
        "font_size": 14, "title_size": 16, "tick_size": 12,
        "line_width": 2.0, "spine_width": 1.3, "tick_length": 5.0,
        "fig_width": 10.0, "fig_height": 5.6, "fig_dpi": 200},
    "Data points": {
        "line_style": "None", "marker": "Circle", "marker_size": 3.0},
    "Filled peaks": {
        "fill_under": True, "fill_alpha": 0.25, "line_width": 1.4},
}


# -- validation ------------------------------------------------------------------
def _coerce(f: Field, value):
    """``value`` as a valid value of field ``f``; ``ValueError`` if it is not
    usable. Numbers are clamped into range."""
    if f.kind == "bool":
        if isinstance(value, bool):
            return value
        raise ValueError
    if f.kind == "choice":
        if value in f.choices:
            return value
        raise ValueError
    if f.kind == "text":
        if isinstance(value, str):
            return value.strip()[:200]
        raise ValueError
    if f.kind == "optfloat":
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
    if f.kind in ("float", "int", "optfloat"):
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError
        x = float(value)
        if not math.isfinite(x):
            raise ValueError
        if f.lo is not None:
            x = max(f.lo, x)
        if f.hi is not None:
            x = min(f.hi, x)
        return int(round(x)) if f.kind == "int" else x
    raise ValueError


def sanitise(style) -> dict:
    """A complete, valid style from anything (a saved dict, a partial preset,
    ``None``): unknown keys are dropped, invalid or missing values take the
    default. Never raises."""
    out = dict(DEFAULTS)
    if isinstance(style, dict):
        for key, value in style.items():
            f = BY_KEY.get(key)
            if f is None:
                continue
            try:
                out[key] = _coerce(f, value)
            except (ValueError, TypeError):
                pass
    a, b = out["x_min"], out["x_max"]
    if a is not None and b is not None and a > b:
        out["x_min"], out["x_max"] = b, a
    a, b = out["y_min"], out["y_max"]
    if a is not None and b is not None and a > b:
        out["y_min"], out["y_max"] = b, a
    return out


def resolve(style) -> dict:
    """Every field present (drawing code calls this on what it is given; it
    trusts values already passed through ``sanitise``)."""
    if style is None:
        return dict(DEFAULTS)
    if style.keys() == DEFAULTS.keys():
        return style
    return {**DEFAULTS, **{k: v for k, v in style.items() if k in DEFAULTS}}


def changed(style) -> dict:
    """Only the values that differ from the defaults (compact form for the
    config file)."""
    s = sanitise(style)
    return {k: v for k, v in s.items() if v != DEFAULTS[k]}


def parse_field(f: Field, text):
    """Value of a text entry for field ``f``, or ``ValueError``. Empty text
    means "automatic" for an optional number and "empty" for text."""
    if f.kind == "text":
        return _coerce(f, text)
    if f.kind == "optfloat":
        return _coerce(f, text if str(text).strip() else None)
    return _coerce(f, str(text).strip())


# -- presets ---------------------------------------------------------------------------
def preset_names(user_presets=None) -> list[str]:
    """Built-in names first, then the user's own (sorted)."""
    return list(BUILTIN_PRESETS) + sorted(
        n for n in (user_presets or {}) if n not in BUILTIN_PRESETS)


def preset_style(name, user_presets=None):
    """The complete style of a preset, or None if there is no such preset."""
    if name in BUILTIN_PRESETS:
        return sanitise(BUILTIN_PRESETS[name])
    if user_presets and name in user_presets:
        return sanitise(user_presets[name])
    return None


def clean_presets(raw) -> dict:
    """User presets read from the config: ``{name: compact style}``."""
    out = {}
    if isinstance(raw, dict):
        for name, st in raw.items():
            if (isinstance(name, str) and name.strip()
                    and name not in BUILTIN_PRESETS and isinstance(st, dict)):
                out[name.strip()[:60]] = changed(st)
    return out


def matching_preset(style, user_presets=None):
    """Name of the preset ``style`` equals, or None."""
    s = sanitise(style)
    for name in preset_names(user_presets):
        if preset_style(name, user_presets) == s:
            return name
    return None


# -- export size --------------------------------------------------------------------------
def export_size(style, default=(8.0, 5.0)):
    """``(width_in, height_in, dpi)`` for Save plot image."""
    s = resolve(style)
    return (s["fig_width"] or default[0], s["fig_height"] or default[1],
            s["fig_dpi"])


# -- matplotlib -----------------------------------------------------------------------------
def rc_overrides(style, theme_family=None) -> dict:
    """rcParams that carry the style, layered over ``themes.mpl_rc``.

    ``theme_family`` is the bundled UI font (used for "Theme font")."""
    s = resolve(style)
    if s["font"] != THEME_FONT:
        family = [s["font"], "DejaVu Sans"]
    elif theme_family:
        family = [theme_family, "DejaVu Sans"]
    else:
        family = ["DejaVu Sans"]
    box = s["frame"] == "Box"
    grid = s["grid"] != "Off"
    rc = {
        "font.family": family, "font.size": s["font_size"],
        "axes.labelsize": s["font_size"], "axes.titlesize": s["title_size"],
        "axes.titleweight": "bold" if s["title_bold"] else "normal",
        "xtick.labelsize": s["tick_size"], "ytick.labelsize": s["tick_size"],
        "legend.fontsize": s["tick_size"],
        "legend.frameon": bool(s["legend_frame"]),
        "axes.linewidth": s["spine_width"],
        "xtick.major.width": s["spine_width"],
        "ytick.major.width": s["spine_width"],
        "xtick.minor.width": s["spine_width"] * 0.75,
        "ytick.minor.width": s["spine_width"] * 0.75,
        "axes.spines.top": box, "axes.spines.right": box,
        "xtick.direction": s["tick_direction"],
        "ytick.direction": s["tick_direction"],
        "xtick.major.size": s["tick_length"],
        "ytick.major.size": s["tick_length"],
        "xtick.minor.size": s["tick_length"] * 0.55,
        "ytick.minor.size": s["tick_length"] * 0.55,
        "xtick.minor.visible": bool(s["minor_ticks"]),
        "ytick.minor.visible": bool(s["minor_ticks"]),
        "axes.grid": grid,
        "grid.linestyle": {"Solid": "-", "Dashed": "--",
                           "Dotted": ":"}[s["grid_style"]],
        "grid.alpha": s["grid_alpha"],
    }
    if grid:
        rc["axes.grid.axis"] = {"Vertical": "x", "Horizontal": "y",
                                "Both": "both"}[s["grid"]]
    else:
        rc["axes.grid.axis"] = "both"
    return rc


def line_kwargs(style, n_traces, selected=False) -> dict:
    """``Axes.plot`` keywords for one trace of a panel of ``n_traces``."""
    s = resolve(style)
    base = s["line_width"]
    lw = base + 0.8 if selected else (base * 0.73 if n_traces > 12 else base)
    kw = {"lw": lw, "ls": LINE_STYLES[s["line_style"]]}
    mk = MARKERS[s["marker"]]
    if mk:
        kw.update(marker=mk, ms=s["marker_size"])
        if mk in "+x.":
            kw["mew"] = max(0.6, base * 0.7)
    if kw["ls"] == "None" and not mk:
        kw.update(marker="o", ms=s["marker_size"])   # never draw nothing
    return kw


def note_size(style, delta=0):
    """Size for small annotations (tick labels, trace labels, markers)."""
    return max(4, resolve(style)["tick_size"] + delta)


def label_gutter_points(style) -> float:
    """Width to reserve right of a stack for its end-of-trace labels."""
    return 78.0 * note_size(style) / 8.0


def end_labels(style) -> bool:
    return resolve(style)["labels"] == "End labels"


def y_unit(style, native):
    """The unit to show for intensity: ``native`` (the file's) unless the
    style overrides it. Returns "" for none."""
    u = resolve(style)["y_units"]
    return {"Auto": native, "Counts": "counts", "Counts / s": "counts/s",
            "Arbitrary units (a.u.)": "a.u.", "None": ""}[u]


def with_unit(label, unit):
    return f"{label} ({unit})" if unit else label


def panel_titles(style, title, subtitle):
    """``(title, subtitle)`` after the style's overrides and switches."""
    s = resolve(style)
    t = (s["title_text"] or title) if s["show_title"] else ""
    return t, (subtitle if s["show_subtitle"] else "")


def x_window(style, lo, hi):
    """The energy window ``(lo, hi)`` the style asks for on a panel whose
    data span ``lo``..``hi``, or None to leave the panel alone. An open end
    keeps the data limit. A window that misses the panel altogether (the C 1s
    range on an O 1s panel) is ignored, so one range can be set for a page of
    different core levels."""
    s = resolve(style)
    if s["x_min"] is None and s["x_max"] is None:
        return None
    a = s["x_min"] if s["x_min"] is not None else lo
    b = s["x_max"] if s["x_max"] is not None else hi
    if a < b and b > lo and a < hi:
        return a, b
    return None


def apply_ranges(ax, style, x=True, y=True):
    """Apply the energy / intensity range. Call after the x axis has been
    inverted: the limits keep whichever direction the axis has."""
    s = resolve(style)
    if x:
        a, b = ax.get_xlim()
        win = x_window(s, min(a, b), max(a, b))
        if win:
            ax.set_xlim((win[1], win[0]) if a > b else win)
    if y and (s["y_min"] is not None or s["y_max"] is not None):
        lo, hi = ax.get_ylim()
        lo = s["y_min"] if s["y_min"] is not None else lo
        hi = s["y_max"] if s["y_max"] is not None else hi
        if lo < hi:
            ax.set_ylim(lo, hi)


def finish_axes(ax, style, y_ticks=True):
    """Style details rcParams cannot express: minor tick locators."""
    s = resolve(style)
    if s["minor_ticks"]:
        from matplotlib.ticker import AutoMinorLocator
        ax.xaxis.set_minor_locator(AutoMinorLocator())
        if y_ticks:
            ax.yaxis.set_minor_locator(AutoMinorLocator())

