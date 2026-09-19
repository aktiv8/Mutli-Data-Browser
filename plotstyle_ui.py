"""The *Plot style* dialog. Its controls are generated from
``plotstyle.FIELDS``, so adding a field there adds the control here.

The dialog talks to the app through ``app.plot_style`` (the current style),
``app.plot_presets`` (the user's presets), ``app.set_plot_style(style)``,
``app.set_plot_presets(presets)``, ``app.tooltip(widget, text)``,
``app.palette`` and ``app.themes``. It is not modal: every change is applied
to the plot straight away, so the effect can be watched.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import plotstyle
from workbook_ui import _finish


class PlotStyleDialog(tk.Toplevel):
    MODIFIED = "(modified)"

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.title("Plot style")
        self.transient(master)
        self.vars = {}
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text="Preset").grid(row=0, column=0, sticky="w",
                                            padx=(0, 8))
        self.preset = tk.StringVar()
        self.preset_cb = ttk.Combobox(body, textvariable=self.preset,
                                      state="readonly", width=26)
        self.preset_cb.grid(row=0, column=1, sticky="ew")
        self.preset_cb.bind("<<ComboboxSelected>>",
                            lambda e: self._on_preset())
        bar = ttk.Frame(body)
        bar.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 8))
        for text, cmd in (("Save as preset…", self._save_preset),
                          ("Delete preset", self._delete_preset),
                          ("Reset", self._reset)):
            ttk.Button(bar, text=text, command=cmd).pack(side="left",
                                                         padx=(0, 6))

        self.nb = ttk.Notebook(body)
        self.nb.grid(row=2, column=0, columnspan=2, sticky="nsew")
        body.rowconfigure(2, weight=1)
        for group in plotstyle.GROUPS:
            tab = ttk.Frame(self.nb, padding=(10, 8))
            tab.columnconfigure(1, weight=1)
            self.nb.add(tab, text=group)
            row = 0
            for f in (x for x in plotstyle.FIELDS if x.group == group):
                self._add_field(tab, row, f)
                row += 1
        ttk.Label(body, style="Muted.TLabel", wraplength=420, justify="left",
                  text="Changes apply to the plot at once, and to PDFs, "
                       "slides and saved images. The style is saved with "
                       "the workbook and with each figure."
                  ).grid(row=3, column=0, columnspan=2, sticky="w",
                         pady=(8, 0))
        ttk.Button(body, text="Close", command=self.destroy).grid(
            row=4, column=1, sticky="e", pady=(10, 0))
        self.bind("<Escape>", lambda e: self.destroy())
        _finish(self, app, 500, 520)
        self._sync()

    # -- controls, one per field ------------------------------------------
    def _add_field(self, parent, row, f):
        label = ttk.Label(parent, text=f.label)
        label.grid(row=row, column=0, sticky="w", padx=(0, 12), pady=3)
        if f.kind == "bool":
            var = tk.BooleanVar()
            w = ttk.Checkbutton(
                parent, variable=var,
                command=lambda: self._commit(f.key, var.get()))
        elif f.kind == "choice":
            var = tk.StringVar()
            w = ttk.Combobox(parent, textvariable=var, state="readonly",
                             width=22, values=list(f.choices))
            w.bind("<<ComboboxSelected>>",
                   lambda e: self._commit(f.key, var.get()))
        elif f.kind in ("float", "int"):
            var = tk.StringVar()
            w = ttk.Spinbox(parent, textvariable=var, width=9,
                            from_=f.lo, to=f.hi, increment=f.step,
                            command=lambda: self._commit_text(f))
        else:                                    # text, optfloat
            var = tk.StringVar()
            w = ttk.Entry(parent, textvariable=var,
                          width=28 if f.kind == "text" else 9)
        if f.kind in ("float", "int", "text", "optfloat"):
            w.bind("<Return>", lambda e: self._commit_text(f))
            w.bind("<FocusOut>", lambda e: self._commit_text(f))
        w.grid(row=row, column=1, sticky="w", pady=3)
        if f.unit:
            ttk.Label(parent, text=f.unit, style="Muted.TLabel").grid(
                row=row, column=2, sticky="w", padx=(6, 0))
        if f.tip:
            for widget in (label, w):
                self.app.tooltip(widget, f.tip)
        self.vars[f.key] = var

    # -- reading and writing ------------------------------------------------
    def _shown(self, f, value):
        if f.kind == "bool":
            return bool(value)
        if value is None:
            return ""
        if f.kind == "float":
            return f"{value:g}"
        return str(value)

    def _sync(self):
        """Show the app's current style in every control."""
        style = self.app.plot_style
        for f in plotstyle.FIELDS:
            self.vars[f.key].set(self._shown(f, style[f.key]))
        names = plotstyle.preset_names(self.app.plot_presets)
        self.preset_cb.configure(values=names)
        self.preset.set(plotstyle.matching_preset(
            style, self.app.plot_presets) or self.MODIFIED)

    def _pending(self):
        """Text typed into an entry but not yet committed (Return / leaving
        the box), so that changing another control does not throw it away.
        Text that does not parse is ignored (the sync restores the old
        value)."""
        out = {}
        for f in plotstyle.FIELDS:
            if f.kind in ("float", "int", "text", "optfloat"):
                try:
                    value = plotstyle.parse_field(f, self.vars[f.key].get())
                except (ValueError, TypeError):
                    continue
                if value != self.app.plot_style[f.key]:
                    out[f.key] = value
        return out

    def _commit(self, key, value):
        new = {**self.app.plot_style, **self._pending(), key: value}
        self.app.set_plot_style(new)
        self._sync()

    def _commit_text(self, f):
        try:
            plotstyle.parse_field(f, self.vars[f.key].get())
        except (ValueError, TypeError):
            self.bell()
            self._sync()
            return
        pending = self._pending()
        if pending:
            self.app.set_plot_style({**self.app.plot_style, **pending})
        self._sync()

    # -- presets ------------------------------------------------------------------
    def _on_preset(self):
        style = plotstyle.preset_style(self.preset.get(),
                                       self.app.plot_presets)
        if style is not None:
            self.app.set_plot_style(style)
        self._sync()

    def _reset(self):
        self.app.set_plot_style(plotstyle.DEFAULTS)
        self._sync()

    def _save_preset(self):
        name = simpledialog.askstring("Save preset", "Name of the preset:",
                                      parent=self)
        name = (name or "").strip()
        if not name:
            return
        if name in plotstyle.BUILTIN_PRESETS:
            messagebox.showinfo("Save preset",
                                f"'{name}' is a built-in preset. Choose "
                                f"another name.", parent=self)
            return
        if name in self.app.plot_presets and not messagebox.askyesno(
                "Save preset", f"Replace the preset '{name}'?", parent=self):
            return
        self.app.set_plot_presets(
            {**self.app.plot_presets,
             name: plotstyle.changed(self.app.plot_style)})
        self._sync()

    def _delete_preset(self):
        name = self.preset.get()
        if name not in self.app.plot_presets:
            messagebox.showinfo("Delete preset",
                                "Select one of your own presets to delete "
                                "it (built-in presets stay).", parent=self)
            return
        if messagebox.askyesno("Delete preset", f"Delete '{name}'?",
                               parent=self):
            rest = dict(self.app.plot_presets)
            del rest[name]
            self.app.set_plot_presets(rest)
            self._sync()
