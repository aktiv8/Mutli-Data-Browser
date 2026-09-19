"""Colour themes for the whole UI: ttk widgets, classic Tk widgets, tick-box
icons and matplotlib figures.

"Light" keeps the platform-native look (it is the original colour scheme);
every other theme uses ttk's fully recolourable ``clam`` engine. PDFs always
render with :data:`PRINT` (white paper) whatever theme is active.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

NATIVE = "Light"

# Every palette must define every key (checked by tests/test_themes.py).
KEYS = ("bg", "panel", "fg", "muted", "accent", "entry", "select_bg",
        "select_fg", "border", "hint", "plot_bg", "plot_fg", "plot_grid",
        "cycle", "box_edge", "box_fill", "box_mark")

_TAB10 = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
          "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]

PALETTES = {
    "Light": {
        "bg": "#f0f0f0", "panel": "#e6e6e6", "fg": "#1a1a1a", "muted": "#666666",
        "accent": "#2a6fdb", "entry": "#ffffff", "select_bg": "#cde0f7",
        "select_fg": "#000000", "border": "#b5b5b5", "hint": "#aa0000",
        "plot_bg": "#ffffff", "plot_fg": "#222222", "plot_grid": "#cccccc",
        "cycle": _TAB10, "box_edge": "#4a4a4a", "box_fill": "#ffffff",
        "box_mark": "#2a6fdb"},
    "Dark": {
        "bg": "#1e1f22", "panel": "#2b2d30", "fg": "#dcdcdc", "muted": "#9a9a9a",
        "accent": "#4c9aff", "entry": "#2b2d30", "select_bg": "#2f65ca",
        "select_fg": "#ffffff", "border": "#43454a", "hint": "#ff8a80",
        "plot_bg": "#1e1f22", "plot_fg": "#dcdcdc", "plot_grid": "#3a3c40",
        "cycle": ["#4fc3f7", "#ffb74d", "#81c784", "#e57373", "#ba68c8",
                  "#a1887f", "#f06292", "#b0bec5", "#dce775", "#4dd0e1"],
        "box_edge": "#9a9a9a", "box_fill": "#2b2d30", "box_mark": "#4c9aff"},
    "Midnight": {
        "bg": "#0f172a", "panel": "#1e293b", "fg": "#e2e8f0", "muted": "#94a3b8",
        "accent": "#38bdf8", "entry": "#16213a", "select_bg": "#1d4ed8",
        "select_fg": "#ffffff", "border": "#334155", "hint": "#fca5a5",
        "plot_bg": "#0f172a", "plot_fg": "#e2e8f0", "plot_grid": "#26344d",
        "cycle": ["#38bdf8", "#fbbf24", "#34d399", "#f87171", "#a78bfa",
                  "#fb923c", "#f472b6", "#94a3b8", "#a3e635", "#22d3ee"],
        "box_edge": "#94a3b8", "box_fill": "#16213a", "box_mark": "#38bdf8"},
    "Solarized Light": {
        "bg": "#fdf6e3", "panel": "#eee8d5", "fg": "#586e75", "muted": "#93a1a1",
        "accent": "#268bd2", "entry": "#fffdf5", "select_bg": "#d5e6ee",
        "select_fg": "#073642", "border": "#d3cbb6", "hint": "#dc322f",
        "plot_bg": "#fdf6e3", "plot_fg": "#586e75", "plot_grid": "#e3dcc6",
        "cycle": ["#268bd2", "#dc322f", "#859900", "#b58900", "#6c71c4",
                  "#2aa198", "#d33682", "#cb4b16"],
        "box_edge": "#657b83", "box_fill": "#fffdf5", "box_mark": "#268bd2"},
    "High contrast": {
        "bg": "#000000", "panel": "#101010", "fg": "#ffffff", "muted": "#cccccc",
        "accent": "#ffff00", "entry": "#000000", "select_bg": "#ffff00",
        "select_fg": "#000000", "border": "#ffffff", "hint": "#ff6060",
        "plot_bg": "#000000", "plot_fg": "#ffffff", "plot_grid": "#555555",
        "cycle": ["#ffff00", "#00ffff", "#ff00ff", "#00ff00", "#ff8000",
                  "#ffffff", "#ff5555", "#55aaff"],
        "box_edge": "#ffffff", "box_fill": "#000000", "box_mark": "#ffff00"},
}
THEME_NAMES = list(PALETTES)

# white "paper" style used for every PDF
PRINT = dict(PALETTES["Light"], plot_bg="#ffffff", plot_fg="#000000",
             plot_grid="#cccccc")


def mpl_rc(pal) -> dict:
    """matplotlib rcParams for a palette (use with ``matplotlib.rc_context``)."""
    rc = {
        "figure.facecolor": pal["plot_bg"], "savefig.facecolor": pal["plot_bg"],
        "axes.facecolor": pal["plot_bg"], "axes.edgecolor": pal["plot_fg"],
        "axes.labelcolor": pal["plot_fg"], "axes.titlecolor": pal["plot_fg"],
        "text.color": pal["plot_fg"], "xtick.color": pal["plot_fg"],
        "ytick.color": pal["plot_fg"], "grid.color": pal["plot_grid"],
        "legend.facecolor": pal["plot_bg"], "legend.edgecolor": pal["plot_grid"],
    }
    try:
        from cycler import cycler
        rc["axes.prop_cycle"] = cycler(color=list(pal["cycle"]))
    except Exception:
        pass
    return rc


def make_box_images(pal):
    """Tiny tick-box icons for the tree: ([unticked, partial, ticked], blank)."""
    def build(state):
        img = tk.PhotoImage(width=16, height=16)
        img.put(pal["box_fill"], to=(2, 2, 14, 14))
        for box in ((2, 2, 14, 3), (2, 13, 14, 14), (2, 2, 3, 14),
                    (13, 2, 14, 14)):
            img.put(pal["box_edge"], to=box)
        if state == 2:
            img.put(pal["box_mark"], to=(5, 5, 11, 11))
        elif state == 1:
            img.put(pal["box_mark"], to=(5, 7, 11, 9))
        return img
    return [build(0), build(1), build(2)], tk.PhotoImage(width=16, height=16)


class ThemeManager:
    """Applies a named palette to a Tk application."""

    def __init__(self, root):
        self.root = root
        self.style = ttk.Style(root)
        self.native = self.style.theme_use()
        self.name = NATIVE
        self.palette = dict(PALETTES[NATIVE])
        self._menus = []
        self._defaults = self._probe_defaults()

    def register_menu(self, menu):
        self._menus.append(menu)

    # -- ttk -------------------------------------------------------------
    def apply(self, name):
        """Switch theme; returns the palette (with the widget bg resolved)."""
        pal = dict(PALETTES.get(name, PALETTES[NATIVE]))
        self.name = name if name in PALETTES else NATIVE
        st = self.style
        if self.name == NATIVE:
            st.theme_use(self.native)
            pal["bg"] = st.lookup("TFrame", "background") or pal["bg"]
            pal["fg"] = st.lookup("TLabel", "foreground") or pal["fg"]
        else:
            st.theme_use("clam")
            self._style_clam(pal)
        st.configure("Hint.TLabel", foreground=pal["hint"])
        st.configure("Muted.TLabel", foreground=pal["muted"])
        self.palette = pal
        self.root.configure(bg=(self._defaults["frame"][0]
                                if self.name == NATIVE else pal["bg"]))
        self.recolor_tk(self.root)
        return pal

    def _style_clam(self, p):
        st = self.style
        bg, panel, fg, muted, entry, border = (
            p["bg"], p["panel"], p["fg"], p["muted"], p["entry"], p["border"])
        st.configure(".", background=bg, foreground=fg, fieldbackground=entry,
                     bordercolor=border, lightcolor=panel, darkcolor=panel,
                     troughcolor=panel, focuscolor=p["accent"],
                     selectbackground=p["select_bg"],
                     selectforeground=p["select_fg"], insertcolor=fg)
        st.map(".", foreground=[("disabled", muted)],
               background=[("disabled", bg)])
        st.configure("TButton", background=panel, foreground=fg, padding=(6, 2))
        st.map("TButton", background=[("active", p["select_bg"]),
                                      ("pressed", p["select_bg"])],
               foreground=[("active", p["select_fg"]),
                           ("disabled", muted)])
        st.configure("TMenubutton", background=panel, foreground=fg,
                     arrowcolor=fg)
        st.map("TMenubutton", background=[("active", p["select_bg"])],
               foreground=[("active", p["select_fg"])])
        st.configure("TEntry", fieldbackground=entry, foreground=fg,
                     insertcolor=fg)
        st.configure("TCombobox", fieldbackground=entry, background=panel,
                     foreground=fg, arrowcolor=fg, selectbackground=entry,
                     selectforeground=fg)
        st.map("TCombobox", fieldbackground=[("readonly", entry)],
               foreground=[("readonly", fg)],
               selectbackground=[("readonly", entry)],
               selectforeground=[("readonly", fg)])
        st.configure("TSpinbox", fieldbackground=entry, foreground=fg,
                     arrowcolor=fg)
        for w in ("TCheckbutton", "TRadiobutton"):
            st.configure(w, background=bg, foreground=fg,
                         indicatorbackground=entry, indicatorforeground=fg)
            st.map(w, background=[("active", bg)],
                   indicatorbackground=[("selected", p["accent"]),
                                        ("active", entry)],
                   foreground=[("disabled", muted)])
        st.configure("TLabelframe", background=bg, bordercolor=border)
        st.configure("TLabelframe.Label", background=bg, foreground=fg)
        st.configure("TNotebook", background=bg, bordercolor=border)
        st.configure("TNotebook.Tab", background=panel, foreground=fg,
                     padding=(8, 2))
        st.map("TNotebook.Tab", background=[("selected", bg)],
               foreground=[("selected", p["accent"])])
        st.configure("Treeview", background=entry, fieldbackground=entry,
                     foreground=fg, bordercolor=border)
        st.map("Treeview", background=[("selected", p["select_bg"])],
               foreground=[("selected", p["select_fg"])])
        st.configure("Treeview.Heading", background=panel, foreground=fg,
                     bordercolor=border, relief="flat")
        st.map("Treeview.Heading", background=[("active", p["select_bg"])])
        for o in ("Vertical", "Horizontal"):
            st.configure(f"{o}.TScrollbar", background=panel, troughcolor=bg,
                         bordercolor=border, arrowcolor=fg)
            st.map(f"{o}.TScrollbar", background=[("active", p["select_bg"])])
        st.configure("TScale", background=bg, troughcolor=panel,
                     bordercolor=border)
        st.configure("Sash", background=border, bordercolor=border)
        st.configure("TPanedwindow", background=border)
        st.configure("TSeparator", background=border)

    # -- classic Tk widgets ------------------------------------------------
    def _probe_defaults(self):
        """Platform-native colours of classic Tk widgets (to restore Light)."""
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
                                activeforeground=p["select_fg"])
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
                highlightbackground=bg, selectcolor=p["panel"])
            try:
                toolbar._set_image_for_button(b)      # recolours the icon
            except Exception:
                pass
        if hasattr(toolbar, "_message_label"):
            cfg(toolbar._message_label, bg=bg, fg=fg)
        for w in toolbar.winfo_children():
            if w.winfo_class() == "Frame":            # separators
                cfg(w, bg=p["border"])
