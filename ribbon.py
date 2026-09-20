"""The tabbed toolbar under the menu bar: Home / Analyse / Report / View, each
a row of icon buttons that call the same ``Workspace`` methods as the menus
(the menu bar stays complete for the keyboard).

The buttons are described by data (``PAGES``): ``(label, icon, target, tip,
needs_data)``; a *target* is a ``Workspace`` method name or ``(name, arg, ...)``,
which keeps the button table testable without a window. Buttons that need
loaded spectra are dimmed while nothing is open. The active tab and whether
the strip is collapsed (tabs only, to give the plot the height back) are kept
in the config.
"""

from __future__ import annotations

import functools
import tkinter as tk
from tkinter import ttk

import themes

TABS = ("Home", "Analyse", "Report", "View")

# ("|", ) is a separator; ("v", label, icon, [items], tip, needs_data) a
# dropdown whose items are (label, target) or None for a separator.
PAGES = {
    "Home": [
        ("Open", "open", "open_files",
         "Open spectra files of any supported format (or a workbook).",
         False),
        ("Folder", "folder", "open_folder",
         "Open a folder of spectra, or an Avantage experiment.", False),
        ("v", "Recent", "recent", "@recent",
         "Files opened before.", False),
        ("|",),
        ("v", "Workbook", "package", [
            ("New workbook", "new_workbook"),
            ("Open workbook…", "open_workbook"), None,
            ("Save workbook as…", ("save_workbook", True)),
        ], "Experiment workbook: keeps the data, notes and figures.", False),
        ("Save", "save", "save_workbook",
         "Save the workbook (Ctrl+S).", True),
        ("|",),
        ("v", "Export", "export", [
            ("Ticked spectra to CSV…", ("export_ticked", "csv")),
            ("Ticked spectra to VAMAS…", ("export_ticked", "vamas")),
            ("Regions and levels…", "open_export"), None,
            ("Metadata to CSV…", "export_meta_csv"),
            ("Metadata to PDF…", "export_meta_pdf"),
        ], "Write spectra or metadata to CSV, VAMAS or PDF.", True),
        ("Image", "image", "save_plot_image",
         "Save the plot as PNG, SVG or PDF.", True),
        ("Close all", "close", "close_all",
         "Close every open file.", True),
    ],
    "Analyse": [
        ("Calibrate", "calibrate", "open_calibrate",
         "Shift binding energies so a reference peak sits at its known "
         "value.", True),
        ("Identify", "identify", "open_identify",
         "Find the elements behind peaks (surveys and core levels).", True),
        ("ISS / REELS", "iss", "open_iss_reels",
         "Ion scattering masses and REELS band gaps.", True),
        ("Sputter", "sputter", "open_sputter",
         "Ion-gun settings of a depth profile: depth and fluence axes.",
         True),
        ("SnapMap", "snapmap", "open_snapmap",
         "View a SnapMap image cube: pick the energy window and regions.",
         True),
        ("|",),
        ("Rename", "rename", "rename_selected",
         "Give the selected sample or region a display name (F2).", True),
        ("Notes", "notes", "notes_selected",
         "Add a note to the selected sample or region.", True),
    ],
    "Report": [
        ("Details", "details", "edit_details",
         "Sample, operator, methods and other details for the report.",
         False),
        ("Figures", "figures", "edit_figures",
         "Save the current look as a figure for the report.", True),
        ("Generator", "report", "report_generator",
         "Choose what goes in the report, and in what order, then make the "
         "PDF or the slides.", True),
        ("|",),
        ("v", "Report PDF", "report", [
            ("Preview…", "preview_report"),
            ("Save PDF…", "save_report"),
        ], "The experiment report as a PDF.", True),
        ("Slides", "slides", "export_powerpoint",
         "Export a PowerPoint deck.", True),
        ("Hand-over", "package", "export_handover",
         "A ZIP with report, spectra, figures and workbook.", True),
        ("Browser", "web", "export_html_browser",
         "One HTML file to explore the data offline.", True),
        ("|",),
        ("v", "PDF", "preview", [
            ("Preview spectra", "preview_spectra"),
            ("Save spectra as PDF…", "save_pdf"), None,
            ("Preview metadata", "preview_metadata"),
            ("Save metadata as PDF…", "export_meta_pdf"),
        ], "Spectra or metadata as PDF.", True),
    ],
    "View": [
        ("@theme",),
        ("Style", "style", "edit_plot_style",
         "Fonts, line widths, ticks, grid, legend and image size.", False),
        ("|",),
        ("@pane", "tree", "Files", "files",
         "Show or hide the file tree."),
        ("@pane", "info", "Details", "details_pane",
         "Show or hide the details column."),
        ("Focus", "focus", "toggle_focus",
         "Hide the file tree and details so the plot fills the window "
         "(F11).", False),
        ("|",),
        ("Expand", "expand", ("_expand", True),
         "Expand every folder in the file tree.", True),
        ("Collapse", "collapse", ("_expand", False),
         "Collapse the file tree.", True),
        ("Untick", "untick", "untick_all",
         "Remove every tick from the plot.", True),
    ],
}


def targets():
    """Every ``Workspace`` method name the buttons call (for the tests)."""
    names = set()

    def add(t):
        if isinstance(t, tuple):
            t = t[0]
        if isinstance(t, str) and not t.startswith("@"):
            names.add(t)
    for items in PAGES.values():
        for it in items:
            if it[0] == "|" or it[0] == "@theme":
                continue
            if it[0] == "@pane":
                continue
            if it[0] == "v":
                if isinstance(it[3], list):
                    for sub in it[3]:
                        if sub is not None:
                            add(sub[1])
                continue
            add(it[2])
    names.add("toggle_focus")
    names.add("_toggle_pane")
    names.add("set_theme")
    names.add("show_about")
    return sorted(names)


class Ribbon(ttk.Frame):
    def __init__(self, parent, app, icon_cache=None):
        super().__init__(parent, style="Ribbon.TFrame")
        self.app = app
        self.icons = icon_cache
        self.items = []                 # (widget, icon name, needs data)
        self.collapsed = bool(app.cfg.get("ribbon_collapsed", False))
        tab = app.cfg.get("ribbon_tab", "Home")
        self.tab_var = tk.StringVar(value=tab if tab in TABS else "Home")

        strip = ttk.Frame(self)
        strip.pack(side="top", fill="x")
        self.tab_buttons = {}
        for name in TABS:
            rb = ttk.Radiobutton(strip, text=name, value=name,
                                 variable=self.tab_var, style="Tab.Toolbutton",
                                 command=self._on_tab)
            rb.pack(side="left")
            rb.bind("<Double-Button-1>", lambda e: self._set_collapsed(True))
            self.tab_buttons[name] = rb
        self.fold = ttk.Button(strip, style="Tool.TButton",
                               command=self._toggle_collapsed)
        self.fold.pack(side="right", padx=(0, 6))
        self.about = ttk.Button(strip, style="Tool.TButton",
                                text="" if icon_cache else "About",
                                command=app.show_about)
        self.about.pack(side="right")
        self._track(self.about, "about", False)
        app.tooltip(self.about, "About this program.")

        self.body = ttk.Frame(self, style="Ribbon.TFrame")
        self.pages = {}
        for name in TABS:
            page = ttk.Frame(self.body, style="Ribbon.TFrame")
            self.pages[name] = page
            self._fill(page, PAGES[name])
        self.sep = ttk.Separator(self)
        self.sep.pack(side="bottom", fill="x")
        self._show()
        self.refresh_icons()
        self.refresh_state()

    # -- building ---------------------------------------------------------
    def _resolve(self, target):
        app = self.app
        if isinstance(target, tuple):
            return functools.partial(getattr(app, target[0]), *target[1:])
        return getattr(app, target)

    def _track(self, widget, icon, needs_data):
        self.items.append((widget, icon, needs_data))

    def _button(self, page, label, icon, target, tip, needs_data):
        b = ttk.Button(page, text=label, style="Ribbon.TButton",
                       compound="top", command=self._resolve(target))
        b.pack(side="left", padx=1, pady=3)
        self._track(b, icon, needs_data)
        self.app.tooltip(b, tip)
        return b

    def _dropdown(self, page, label, icon, items, tip, needs_data):
        app = self.app
        b = ttk.Button(page, text=f"{label} ▾", style="Ribbon.TButton",
                       compound="top")
        if items == "@recent":
            menu = app.recent_menu
        else:
            menu = tk.Menu(b, tearoff=0)
            for it in items:
                if it is None:
                    menu.add_separator()
                else:
                    menu.add_command(label=it[0],
                                     command=self._resolve(it[1]))
            app.themes.register_menu(menu)

        def drop():
            try:
                menu.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())
            finally:
                menu.grab_release()
        b.configure(command=drop)
        b.pack(side="left", padx=1, pady=3)
        self._track(b, icon, needs_data)
        app.tooltip(b, tip)

    def _fill(self, page, spec):
        app = self.app
        for it in spec:
            kind = it[0]
            if kind == "|":
                ttk.Separator(page, orient="vertical").pack(
                    side="left", fill="y", padx=6, pady=6)
            elif kind == "v":
                _v, label, icon, items, tip, needs = it
                self._dropdown(page, label, icon, items, tip, needs)
            elif kind == "@theme":
                box = ttk.Frame(page, style="Ribbon.TFrame")
                box.pack(side="left", padx=(8, 6), pady=6)
                ttk.Label(box, text="Theme", style="Muted.TLabel").pack(
                    anchor="w")
                cb = ttk.Combobox(box, width=15, state="readonly",
                                  values=themes.THEME_NAMES,
                                  textvariable=app.theme_var)
                cb.pack()
                cb.bind("<<ComboboxSelected>>",
                        lambda e: app.set_theme(app.theme_var.get()))
                app.tooltip(cb, "Colour theme of the window and the plots.")
            elif kind == "@pane":
                _p, key, label, icon, tip = it
                cb = ttk.Checkbutton(
                    page, text=label, style="Ribbon.Toolbutton",
                    compound="top", variable=app.show_vars[key],
                    command=lambda k=key: app._toggle_pane(k))
                cb.pack(side="left", padx=1, pady=3)
                self._track(cb, icon, False)
                app.tooltip(cb, tip)
            else:
                label, icon, target, tip, needs = it
                self._button(page, label, icon, target, tip, needs)

    # -- tabs ----------------------------------------------------------------
    def _show(self):
        for page in self.pages.values():
            page.pack_forget()
        self.body.pack_forget()
        if not self.collapsed:
            self.pages[self.tab_var.get()].pack(side="left", fill="x",
                                                padx=6)
            self.body.pack(side="top", fill="x", before=self.sep)
        self._fold_icon()

    def _on_tab(self):
        if self.collapsed:
            self.collapsed = False
        self._show()

    def _set_collapsed(self, value):
        self.collapsed = bool(value)
        self._show()

    def _toggle_collapsed(self):
        self._set_collapsed(not self.collapsed)

    def _fold_icon(self):
        if self.icons is None:
            self.fold.configure(text="▸" if self.collapsed else "▾")
            return
        name = "expand" if self.collapsed else "collapse"
        self.fold.configure(image=self.icons.get(name))
        self.app.tooltip(self.fold, "Show the buttons" if self.collapsed
                         else "Hide the buttons (double-click a tab)")

    def save_state(self, cfg):
        cfg["ribbon_tab"] = self.tab_var.get()
        cfg["ribbon_collapsed"] = bool(self.collapsed)

    # -- icons and enabled state --------------------------------------------
    def set_icons(self, cache):
        self.icons = cache
        self.refresh_icons()

    def refresh_icons(self):
        """(Re)apply the icons for the current palette and enabled state."""
        if self.icons is None:
            return
        for widget, name, _needs in self.items:
            off = widget.instate(["disabled"])
            widget.configure(image=self.icons.get(name, disabled=off))
        self._fold_icon()

    def refresh_state(self):
        """Dim the buttons that need spectra while none are loaded."""
        has = bool(self.app.docs)
        for widget, _name, needs in self.items:
            if needs:
                widget.state(["!disabled"] if has else ["disabled"])
        self.refresh_icons()
