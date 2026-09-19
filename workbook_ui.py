"""Dialogs for experiment workbooks and the AVG/VGD import prompt.

Kept out of ``escape_explorer.py``; each dialog talks to the app only through
a few attributes / methods (see the docstrings).
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import plotstyle
import workbook as wbk


def _finish(dialog, app, width, height):
    """Theme a dialog like the main window and centre it over it."""
    dialog.configure(bg=app.palette["bg"])
    app.themes.recolor_tk(dialog)
    dialog.update_idletasks()
    root = app.root
    x = root.winfo_rootx() + max(0, (root.winfo_width() - width) // 2)
    y = root.winfo_rooty() + max(0, (root.winfo_height() - height) // 3)
    dialog.geometry(f"{width}x{height}+{x}+{y}")


class DetailsDialog(tk.Toplevel):
    """Title, customer, reference, operator, date, the free-text summary and
    the letterhead logo of a workbook. ``on_ok(details, logo_path)`` is called
    with the edited values."""

    FIELDS = (("title", "Title"), ("customer", "Customer"),
              ("reference", "Reference / job no."), ("operator", "Operator"),
              ("date", "Date"))

    def __init__(self, master, app, details, logo, on_ok):
        super().__init__(master)
        self.app, self.on_ok, self.logo = app, on_ok, logo or ""
        self.title("Workbook details and notes")
        self.transient(master)
        self.grab_set()
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        self.vars = {}
        for row, (key, label) in enumerate(self.FIELDS):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w",
                                             pady=3, padx=(0, 10))
            self.vars[key] = tk.StringVar(value=details.get(key, ""))
            ttk.Entry(body, textvariable=self.vars[key]).grid(
                row=row, column=1, columnspan=2, sticky="ew", pady=3)
        r = len(self.FIELDS)
        ttk.Label(body, text="Summary / notes").grid(
            row=r, column=0, sticky="nw", pady=(8, 3), padx=(0, 10))
        holder = ttk.Frame(body)
        holder.grid(row=r, column=1, columnspan=2, sticky="nsew", pady=(8, 3))
        body.rowconfigure(r, weight=1)
        self.summary = tk.Text(holder, wrap="word", height=12, width=60,
                               undo=True, relief="flat", borderwidth=1,
                               font="TkDefaultFont")
        sb = ttk.Scrollbar(holder, command=self.summary.yview)
        self.summary.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.summary.pack(side="left", fill="both", expand=True)
        self.summary.insert("1.0", details.get("summary", ""))
        ttk.Label(body, style="Muted.TLabel", wraplength=460, justify="left",
                  text="Blank lines start a new paragraph in the report. The "
                       "text is saved in the workbook."
                  ).grid(row=r + 1, column=1, columnspan=2, sticky="w")

        ttk.Label(body, text="Letterhead logo").grid(
            row=r + 2, column=0, sticky="w", pady=(10, 3), padx=(0, 10))
        self.logo_lbl = ttk.Label(body, style="Muted.TLabel")
        self.logo_lbl.grid(row=r + 2, column=1, sticky="w", pady=(10, 3))
        lb = ttk.Frame(body)
        lb.grid(row=r + 2, column=2, sticky="e", pady=(10, 3))
        ttk.Button(lb, text="Choose…", command=self._choose_logo).pack(
            side="left")
        ttk.Button(lb, text="Remove", command=self._clear_logo).pack(
            side="left", padx=(4, 0))
        self._show_logo()

        bar = ttk.Frame(body)
        bar.grid(row=r + 3, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(
            side="right")
        ttk.Button(bar, text="OK",
                   command=self._ok).pack(side="right", padx=(0, 6))
        self.bind("<Escape>", lambda e: self.destroy())
        _finish(self, app, 620, 560)
        self.summary.configure(bg=app.palette["entry"], fg=app.palette["fg"],
                               insertbackground=app.palette["fg"])

    def _show_logo(self):
        self.logo_lbl.config(text=os.path.basename(self.logo)
                             if self.logo else "none")

    def _choose_logo(self):
        p = filedialog.askopenfilename(
            parent=self, title="Choose a logo",
            filetypes=[("Images", "*.png *.jpg *.jpeg"), ("All files", "*.*")])
        if p:
            self.logo = p
            self._show_logo()

    def _clear_logo(self):
        self.logo = ""
        self._show_logo()

    def _ok(self):
        details = {k: v.get().strip() for k, v in self.vars.items()}
        details["summary"] = self.summary.get("1.0", "end").rstrip()
        self.on_ok(details, self.logo)
        self.destroy()


class FiguresDialog(tk.Toplevel):
    """Manage the workbook's named figures (saved looks with captions).

    Uses ``app.figures`` (list of ``{id, name, caption, state}``),
    ``app.capture_state()``, ``app.apply_state(state)`` and ``app.wb_touch()``.
    Not modal, so the plot stays visible while you adjust it."""

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.title("Figures")
        self.transient(master)
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        ttk.Label(body, style="Muted.TLabel", wraplength=440, justify="left",
                  text="A figure remembers what is ticked and how it looks "
                       "(view, colours, axes, grouping…). Figures become the "
                       "figure pages of the experiment report."
                  ).grid(row=0, column=0, columnspan=2, sticky="w",
                         pady=(0, 8))
        self.list = tk.Listbox(body, height=8, exportselection=False,
                               activestyle="none")
        self.list.grid(row=1, column=0, sticky="nsew")
        body.rowconfigure(1, weight=1)
        self.list.bind("<<ListboxSelect>>", lambda e: self._on_select())
        self.list.bind("<Double-Button-1>", lambda e: self._recall())
        side = ttk.Frame(body)
        side.grid(row=1, column=1, sticky="n", padx=(8, 0))
        for text, cmd in (("Add current view…", self._add),
                          ("Recall", self._recall),
                          ("Update from current view", self._update),
                          ("Rename…", self._rename),
                          ("Move up", lambda: self._move(-1)),
                          ("Move down", lambda: self._move(1)),
                          ("Delete", self._delete)):
            ttk.Button(side, text=text, command=cmd).pack(fill="x", pady=2)
        ttk.Label(body, text="Caption").grid(row=2, column=0, sticky="w",
                                             pady=(10, 2))
        self.caption = tk.Text(body, wrap="word", height=6, undo=True,
                               relief="flat", borderwidth=1,
                               font="TkDefaultFont")
        self.caption.grid(row=3, column=0, columnspan=2, sticky="ew")
        ttk.Button(body, text="Close", command=self._close).grid(
            row=4, column=1, sticky="e", pady=(10, 0))
        self.sel = None
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Escape>", lambda e: self._close())
        _finish(self, app, 620, 520)
        self.caption.configure(bg=app.palette["entry"], fg=app.palette["fg"],
                               insertbackground=app.palette["fg"])
        self.list.configure(bg=app.palette["entry"], fg=app.palette["fg"],
                            selectbackground=app.palette["select_bg"],
                            selectforeground=app.palette["select_fg"],
                            highlightthickness=0, relief="flat")
        self._fill()

    # -- list ------------------------------------------------------------
    def _fill(self, select=None):
        self.list.delete(0, "end")
        for i, f in enumerate(self.app.figures, 1):
            self.list.insert("end", f"{i}.  {f['name']}")
        self.sel = None
        if select is not None and self.app.figures:
            select = max(0, min(select, len(self.app.figures) - 1))
            self.list.selection_set(select)
            self.sel = select
        self._show_caption()

    def _flush(self):
        """Store the caption text being edited into its figure."""
        if self.sel is not None and self.sel < len(self.app.figures):
            text = self.caption.get("1.0", "end").rstrip()
            fig = self.app.figures[self.sel]
            if fig.get("caption", "") != text:
                fig["caption"] = text
                self.app.wb_touch()

    def _show_caption(self):
        self.caption.delete("1.0", "end")
        if self.sel is not None:
            self.caption.insert("1.0",
                                self.app.figures[self.sel].get("caption", ""))

    def _on_select(self):
        self._flush()
        cur = self.list.curselection()
        self.sel = cur[0] if cur else None
        self._show_caption()

    def _current(self):
        self._flush()
        cur = self.list.curselection()
        if not cur:
            messagebox.showinfo("Figures", "Select a figure first.",
                                parent=self)
            return None
        return cur[0]

    # -- actions -----------------------------------------------------------
    def _add(self):
        self._flush()
        n = len(self.app.figures) + 1
        name = simpledialog.askstring("Add figure", "Name of the figure:",
                                      initialvalue=f"Figure {n}", parent=self)
        if not name or not name.strip():
            return
        ids = [f["id"] for f in self.app.figures]
        self.app.figures.append({"id": wbk.new_id(ids, "g"),
                                 "name": name.strip(), "caption": "",
                                 "state": self.app.capture_state()})
        self.app.wb_touch()
        self._fill(select=len(self.app.figures) - 1)
        self.caption.focus_set()

    def _recall(self):
        i = self._current()
        if i is None:
            return
        missing = self.app.apply_state(self.app.figures[i]["state"])
        if missing:
            messagebox.showwarning(
                "Figure recalled",
                f"{missing} spectrum(s) of this figure are no longer in the "
                f"loaded files and were skipped.", parent=self)

    def _update(self):
        i = self._current()
        if i is None:
            return
        name = self.app.figures[i]["name"]
        if messagebox.askyesno("Update figure",
                               f"Replace the saved look of '{name}' with the "
                               f"current view?", parent=self):
            self.app.figures[i]["state"] = self.app.capture_state()
            self.app.wb_touch()

    def _rename(self):
        i = self._current()
        if i is None:
            return
        name = simpledialog.askstring(
            "Rename figure", "Name:", initialvalue=self.app.figures[i]["name"],
            parent=self)
        if name and name.strip():
            self.app.figures[i]["name"] = name.strip()
            self.app.wb_touch()
            self._fill(select=i)

    def _move(self, d):
        i = self._current()
        if i is None or not 0 <= i + d < len(self.app.figures):
            return
        figs = self.app.figures
        figs[i], figs[i + d] = figs[i + d], figs[i]
        self.app.wb_touch()
        self._fill(select=i + d)

    def _delete(self):
        i = self._current()
        if i is None:
            return
        if messagebox.askyesno("Delete figure",
                               f"Delete '{self.app.figures[i]['name']}'?",
                               parent=self):
            del self.app.figures[i]
            self.app.wb_touch()
            self._fill(select=i)

    def _close(self):
        self._flush()
        self.destroy()


class DuplicateFormatDialog(tk.Toplevel):
    """Ask what to import when files exist as both ``.avg`` and ``.vgd``.

    After ``wait_window``, ``result`` is ``None`` (cancelled) or
    ``(choice, remember)`` where ``choice`` is ``"avg"``, ``"vgd"``,
    ``"both"`` or a ``{avg_path: choice}`` dict."""

    MAX_LISTED = 200

    def __init__(self, master, app, pairs, default="avg"):
        super().__init__(master)
        self.app, self.pairs, self.result = app, pairs, None
        self.title("Same data in two formats")
        self.transient(master)
        self.grab_set()
        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        n = len(pairs)
        ttk.Label(
            body, wraplength=440, justify="left",
            text=(f"{n} dataset{'s are' if n != 1 else ' is'} in this "
                  f"selection as both .avg and .vgd. The data are the same in "
                  f"both, so importing both would list everything twice.\n\n"
                  f"Which would you like to import?")).pack(anchor="w")
        self.mode = tk.StringVar(value=default if default in
                                 ("avg", "vgd", "both") else "avg")
        for value, text in (("avg", "Use the .avg files (recommended)"),
                            ("vgd", "Use the .vgd files"),
                            ("both", "Import both"),
                            ("each", "Choose for each dataset")):
            ttk.Radiobutton(body, text=text, value=value, variable=self.mode,
                            command=self._sync).pack(anchor="w", pady=2,
                                                     padx=(10, 0))
        self.list_frame = ttk.Frame(body)
        self.list_frame.pack(fill="x", padx=(28, 0), pady=(4, 0))
        self.each = {}
        for avg, _vgd in pairs[:self.MAX_LISTED]:
            row = ttk.Frame(self.list_frame)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=os.path.splitext(os.path.basename(avg))[0],
                      width=34).pack(side="left")
            var = tk.StringVar(value="avg")
            cb = ttk.Combobox(row, textvariable=var, width=6,
                              state="disabled", values=["avg", "vgd", "both"])
            cb.pack(side="left")
            self.each[avg] = (var, cb)
        if n > self.MAX_LISTED:
            ttk.Label(self.list_frame, style="Muted.TLabel",
                      text=f"… and {n - self.MAX_LISTED} more (use .avg)"
                      ).pack(anchor="w")
        self.remember = tk.BooleanVar(value=False)
        ttk.Checkbutton(body, text="Remember my choice and don't ask again",
                        variable=self.remember).pack(anchor="w", pady=(12, 0))
        bar = ttk.Frame(body)
        bar.pack(fill="x", pady=(12, 0))
        ttk.Button(bar, text="Cancel import", command=self.destroy).pack(
            side="right")
        ttk.Button(bar, text="Import",
                   command=self._ok).pack(side="right", padx=(0, 6))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._ok())
        self._sync()
        _finish(self, app, 520, min(620, 330 + 26 * min(n, 12)))

    def _sync(self):
        state = "readonly" if self.mode.get() == "each" else "disabled"
        for _var, cb in self.each.values():
            cb.configure(state=state)

    def _ok(self):
        mode = self.mode.get()
        if mode == "each":
            choice = {avg: var.get() for avg, (var, _cb) in self.each.items()}
            for avg, _vgd in self.pairs[self.MAX_LISTED:]:
                choice[avg] = "avg"
            remember = False          # a per-file choice is not a preference
        else:
            choice, remember = mode, self.remember.get()
        self.result = (choice, remember)
        self.destroy()


class SectionsDialog(tk.Toplevel):
    """A small checklist of sections to include; ``on_ok(chosen_keys)`` is
    called with the ticked keys (in order) when the user confirms."""

    def __init__(self, master, app, title, options, on_ok):
        super().__init__(master)
        self.on_ok = on_ok
        self.title(title)
        self.transient(master)
        self.grab_set()
        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Include:").pack(anchor="w")
        self.vars = []
        for key, label in options:
            var = tk.BooleanVar(value=True)
            ttk.Checkbutton(body, text=label, variable=var).pack(
                anchor="w", padx=(12, 0), pady=2)
            self.vars.append((key, var))
        bar = ttk.Frame(body)
        bar.pack(fill="x", pady=(14, 0))
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(
            side="right")
        ttk.Button(bar, text="Export…", command=self._ok).pack(
            side="right", padx=(0, 6))
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._ok())
        _finish(self, app, 360, 60 + 32 * len(options) + 70)

    def _ok(self):
        chosen = tuple(k for k, v in self.vars if v.get())
        if not chosen:
            messagebox.showinfo("Export", "Choose at least one section.",
                                parent=self)
            return
        self.destroy()
        self.on_ok(chosen)


class NotesDialog(tk.Toplevel):
    """Free-text notes for a sample or region; ``on_ok(text)`` gets the text."""

    def __init__(self, master, app, title, text, on_ok):
        super().__init__(master)
        self.on_ok = on_ok
        self.title(title)
        self.transient(master)
        self.grab_set()
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        self.text = tk.Text(body, wrap="word", height=10, width=56, undo=True,
                            relief="flat", borderwidth=1,
                            font="TkDefaultFont")
        self.text.pack(fill="both", expand=True)
        self.text.insert("1.0", text)
        bar = ttk.Frame(body)
        bar.pack(fill="x", pady=(10, 0))
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(
            side="right")
        ttk.Button(bar, text="OK", command=self._ok).pack(
            side="right", padx=(0, 6))
        self.bind("<Escape>", lambda e: self.destroy())
        _finish(self, app, 520, 340)
        self.text.configure(bg=app.palette["entry"], fg=app.palette["fg"],
                            insertbackground=app.palette["fg"])
        self.text.focus_set()

    def _ok(self):
        text = self.text.get("1.0", "end").rstrip()
        self.destroy()
        self.on_ok(text)


class CalibrateDialog(tk.Toplevel):
    """Binding-energy calibration: find (or click) a reference peak, enter its
    reference energy, and apply the shift to a region, a sample or the file.

    Uses ``app.calibration_label(region)``, ``app.apply_calibration(...)``,
    ``app.clear_calibration(...)`` and ``app._pick_cb``. Not modal, so the
    plot can be clicked while it is open."""

    def __init__(self, master, app, regions):
        import calibration
        super().__init__(master)
        self.app, self.cal = app, calibration
        self.regions = regions
        self.title("Calibrate binding energy")
        self.transient(master)
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        r = 0
        ttk.Label(body, text="Reference spectrum").grid(
            row=r, column=0, sticky="w", pady=3)
        self.reg_var = tk.StringVar()
        names = [app.calibration_label(x) for x in regions]
        self.reg_cb = ttk.Combobox(body, textvariable=self.reg_var,
                                   values=names, state="readonly", width=44)
        self.reg_cb.grid(row=r, column=1, columnspan=2, sticky="ew", pady=3)
        self.reg_cb.current(0)
        r += 1
        ttk.Label(body, text="Reference peak").grid(row=r, column=0,
                                                    sticky="w", pady=3)
        self.preset_var = tk.StringVar(value=calibration.PRESETS[0][0])
        pc = ttk.Combobox(body, textvariable=self.preset_var, state="readonly",
                          values=[p[0] for p in calibration.PRESETS],
                          width=44)
        pc.grid(row=r, column=1, columnspan=2, sticky="ew", pady=3)
        pc.bind("<<ComboboxSelected>>", lambda e: self._preset())
        r += 1
        self.vars = {}
        for key, label, init in (("ref", "Reference BE (eV)", "284.80"),
                                 ("centre", "Search around (eV)", "285.00"),
                                 ("half", "± window (eV)", "2.0"),
                                 ("meas", "Measured BE (eV)", "")):
            ttk.Label(body, text=label).grid(row=r, column=0, sticky="w",
                                             pady=3)
            self.vars[key] = tk.StringVar(value=init)
            e = ttk.Entry(body, textvariable=self.vars[key], width=12)
            e.grid(row=r, column=1, sticky="w", pady=3)
            self.vars[key].trace_add("write", lambda *a: self._update())
            r += 1
        btns = ttk.Frame(body)
        btns.grid(row=r - 1, column=2, sticky="e")
        ttk.Button(btns, text="Find peak", command=self._find).pack(
            side="left")
        ttk.Button(btns, text="Click on plot", command=self._pick).pack(
            side="left", padx=(4, 0))
        self.result = ttk.Label(body, style="Muted.TLabel", wraplength=440,
                                justify="left")
        self.result.grid(row=r, column=0, columnspan=3, sticky="w",
                         pady=(6, 2))
        r += 1
        self.scope = tk.StringVar(value="sample")
        box = ttk.LabelFrame(body, text="Apply the shift to")
        box.grid(row=r, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        for value, text in (("region", "this region of this sample"),
                            ("sample", "every region of this sample"),
                            ("file", "every sample in this file")):
            ttk.Radiobutton(box, text=text, value=value,
                            variable=self.scope).pack(anchor="w", padx=8,
                                                      pady=1)
        r += 1
        bar = ttk.Frame(body)
        bar.grid(row=r, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(bar, text="Close", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="Remove shift", command=self._remove).pack(
            side="right", padx=(0, 6))
        ttk.Button(bar, text="Apply", command=self._apply).pack(
            side="right", padx=(0, 6))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Destroy>", lambda e: self._cancel_pick()
                  if e.widget is self else None)
        _finish(self, app, 560, 460)
        self._update()

    # -- helpers -----------------------------------------------------------------
    def _region(self):
        return self.regions[self.reg_cb.current()]

    def _num(self, key):
        try:
            return float(self.vars[key].get())
        except ValueError:
            return None

    def _preset(self):
        for label, centre, ref in self.cal.PRESETS:
            if label == self.preset_var.get() and ref is not None:
                self.vars["ref"].set(f"{ref:.2f}")
                self.vars["centre"].set(f"{centre:.2f}")
                self.vars["half"].set("2.0")

    def _find(self):
        centre, half = self._num("centre"), self._num("half")
        if centre is None or half is None:
            self.result.config(text="Enter the search centre and window.")
            return
        r = self._region()
        hit = self.cal.find_peak(r.energy, r.counts, centre - half,
                                 centre + half)
        if hit is None:
            self.result.config(text="No data in that window.")
            return
        self.vars["meas"].set(f"{hit[0]:.3f}")

    def _pick(self):
        self.app._pick_cb = self._picked
        self.result.config(text="Click the peak on the plot…")
        try:
            self.app.canvas.get_tk_widget().config(cursor="crosshair")
        except tk.TclError:
            pass

    def _picked(self, be):
        if self.winfo_exists():
            self.vars["meas"].set(f"{be:.3f}")

    def _cancel_pick(self):
        self.app._pick_cb = None

    def _shift(self):
        ref, meas = self._num("ref"), self._num("meas")
        if ref is None or meas is None:
            return None
        return self.cal.shift_for(meas, ref)

    def _update(self):
        shift = self._shift()
        if shift is None:
            self.result.config(text="Find or click the reference peak, or "
                                    "type its measured energy.")
        else:
            self.result.config(
                text=f"Shift = {shift:+.3f} eV  (measured "
                     f"{self._num('meas'):.3f} → "
                     f"{self._num('ref'):.3f} eV)")

    def _apply(self):
        shift = self._shift()
        if shift is None:
            messagebox.showinfo("Calibrate", "Enter the reference and "
                                             "measured energies first.",
                                parent=self)
            return
        ref_text = self.preset_var.get().split(" - ")[0]
        if ref_text == "Custom":
            ref_text = "the reference peak"
        self.app.apply_calibration(
            self._region(), self.scope.get(), shift,
            {"measured": self._num("meas"), "reference": self._num("ref"),
             "ref_text": ref_text})

    def _remove(self):
        self.app.clear_calibration(self._region(), self.scope.get())


class ProgressDialog(tk.Toplevel):
    """A modal 'Loading n of N' box with a Cancel button. Call ``step(text)``
    between units of work (it keeps the UI alive) and check ``cancelled``."""

    def __init__(self, master, app, title, total):
        super().__init__(master)
        self.total, self.done, self.cancelled = max(1, total), 0, False
        self.title(title)
        self.transient(master)
        self.grab_set()
        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        self.label = ttk.Label(body, text="", width=54)
        self.label.pack(anchor="w")
        self.bar = ttk.Progressbar(body, maximum=self.total, length=380)
        self.bar.pack(fill="x", pady=(8, 10))
        ttk.Button(body, text="Cancel", command=self._cancel).pack(
            side="right")
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        _finish(self, app, 460, 130)

    def _cancel(self):
        self.cancelled = True
        self.label.config(text="Cancelling after the current file…")

    def step(self, text):
        self.label.config(text=text)
        self.bar["value"] = self.done
        self.done += 1
        self.update()

    def close(self):
        try:
            self.grab_release()
            self.destroy()
        except tk.TclError:
            pass


class ImageOptionsDialog(tk.Toplevel):
    """Options for 'Save plot image': style, size and resolution.
    ``on_ok(style, width_in, height_in, dpi)`` is called on OK."""

    def __init__(self, master, app, on_ok):
        super().__init__(master)
        self.on_ok = on_ok
        self.title("Save plot image")
        self.transient(master)
        self.grab_set()
        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Style").grid(row=0, column=0, sticky="w",
                                           pady=3)
        self.style = tk.StringVar(value="Paper (white)")
        ttk.Combobox(body, textvariable=self.style, state="readonly", width=18,
                     values=["Paper (white)", "Current theme"]).grid(
            row=0, column=1, sticky="w", pady=3)
        self.vars = {}
        w0, h0, dpi0 = plotstyle.export_size(app.plot_style)
        for r, (key, label, init) in enumerate((
                ("w", "Width (inches)", f"{w0:g}"),
                ("h", "Height (inches)", f"{h0:g}"),
                ("dpi", "Resolution (dpi)", str(dpi0))), start=1):
            ttk.Label(body, text=label).grid(row=r, column=0, sticky="w",
                                             pady=3, padx=(0, 12))
            self.vars[key] = tk.StringVar(value=init)
            ttk.Entry(body, textvariable=self.vars[key], width=8).grid(
                row=r, column=1, sticky="w", pady=3)
        ttk.Label(body, style="Muted.TLabel", wraplength=300,
                  text="Saves the panels currently shown (PNG, SVG or PDF, "
                       "chosen next). Fonts, lines and ticks follow the plot "
                       "style; its image size is the starting point here.").grid(row=4, column=0, columnspan=2,
                                             sticky="w", pady=(6, 0))
        bar = ttk.Frame(body)
        bar.grid(row=5, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="Next…", command=self._ok).pack(
            side="right", padx=(0, 6))
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._ok())
        _finish(self, app, 380, 260)

    def _ok(self):
        try:
            w, h = float(self.vars["w"].get()), float(self.vars["h"].get())
            dpi = int(float(self.vars["dpi"].get()))
        except ValueError:
            messagebox.showinfo("Save plot image", "Enter numbers for the "
                                                   "size and resolution.",
                                parent=self)
            return
        if not (1 <= w <= 40 and 1 <= h <= 40 and 50 <= dpi <= 1200):
            messagebox.showinfo("Save plot image",
                                "Size 1-40 inches, resolution 50-1200 dpi.",
                                parent=self)
            return
        style = self.style.get()
        self.destroy()
        self.on_ok(style, w, h, dpi)


class IdentifyDialog(tk.Toplevel):
    """Label the peaks of a survey with element lines. Click a peak on the
    plot to list the candidate lines near it, add the one you want as a
    marker, or let 'Auto-label' do every peak. Markers are kept with the
    workbook. Uses ``app.identify_*`` methods and ``app._click_cb``; not
    modal, so the plot stays usable."""

    def __init__(self, master, app, regions):
        import xpslines
        super().__init__(master)
        self.app, self.xl = app, xpslines
        self.lines = app.element_lines()
        self.regions = regions
        self.clicked = None                    # measured BE of the last click
        self.cands = []
        self.title("Identify peaks")
        self.transient(master)
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        top = ttk.Frame(body)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="Spectrum").grid(row=0, column=0, sticky="w",
                                             padx=(0, 8))
        self.reg_cb = ttk.Combobox(
            top, state="readonly", width=44,
            values=[app.calibration_label(r) for r in regions])
        self.reg_cb.grid(row=0, column=1, sticky="ew")
        self.reg_cb.current(0)
        self.reg_cb.bind("<<ComboboxSelected>>",
                         lambda e: self._refresh_markers())
        ttk.Label(top, text="Window ± (eV)").grid(
            row=1, column=0, sticky="w", pady=(6, 0))
        self.window = tk.StringVar(value="2.0")
        ttk.Entry(top, textvariable=self.window, width=7).grid(
            row=1, column=1, sticky="w", pady=(6, 0))
        self.hint = ttk.Label(body, style="Muted.TLabel", wraplength=470,
                              justify="left",
                              text="Click a peak on the plot to see the "
                                   "candidate lines. Line positions are "
                                   "approximate (chemical shifts of a few eV "
                                   "are normal).")
        self.hint.grid(row=1, column=0, sticky="w", pady=(8, 4))
        ttk.Label(body, text="Candidates").grid(row=2, column=0, sticky="w")
        self.cand_list = tk.Listbox(body, height=6, exportselection=False,
                                    activestyle="none")
        self.cand_list.grid(row=3, column=0, sticky="ew")
        self.cand_list.bind("<Double-Button-1>", lambda e: self._add())
        row = ttk.Frame(body)
        row.grid(row=4, column=0, sticky="w", pady=(4, 8))
        ttk.Button(row, text="Add marker", command=self._add).pack(
            side="left")
        ttk.Button(row, text="Auto-label all peaks",
                   command=self._auto).pack(side="left", padx=(6, 0))
        ttk.Label(body, text="Markers on this spectrum").grid(
            row=5, column=0, sticky="w")
        self.mark_list = tk.Listbox(body, height=6, exportselection=False,
                                    activestyle="none")
        self.mark_list.grid(row=6, column=0, sticky="ew")
        row2 = ttk.Frame(body)
        row2.grid(row=7, column=0, sticky="w", pady=(4, 0))
        ttk.Button(row2, text="Remove selected",
                   command=self._remove).pack(side="left")
        ttk.Button(row2, text="Clear all", command=self._clear).pack(
            side="left", padx=(6, 0))
        ttk.Button(body, text="Close", command=self.destroy).grid(
            row=8, column=0, sticky="e", pady=(10, 0))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Destroy>", lambda e: self._detach()
                  if e.widget is self else None)
        _finish(self, app, 520, 640)
        for lb in (self.cand_list, self.mark_list):
            lb.configure(bg=app.palette["entry"], fg=app.palette["fg"],
                         selectbackground=app.palette["select_bg"],
                         selectforeground=app.palette["select_fg"],
                         highlightthickness=0, relief="flat")
        app._click_cb = self._on_click
        self._refresh_markers()

    def _detach(self):
        if self.app._click_cb == self._on_click:
            self.app._click_cb = None

    def _region(self):
        return self.regions[self.reg_cb.current()]

    def _win(self):
        try:
            return max(0.1, float(self.window.get()))
        except ValueError:
            return 2.0

    def _on_click(self, be, event=None):
        self.clicked = be
        hv = self._region().photon_energy
        self.cands = self.xl.candidates(be, self._win(), self.lines, hv)
        self.cand_list.delete(0, "end")
        for d, e in self.cands:
            self.cand_list.insert(
                "end", f"{self.xl.label_of(e):<12} "
                       f"{self.xl.line_be(e, hv):8.1f} eV   ({d:+.1f})")
        if self.cands:
            self.cand_list.selection_set(0)
        self.hint.config(text=f"Peak at {be:.2f} eV measured: "
                              f"{len(self.cands)} candidate line(s) within "
                              f"±{self._win():g} eV.")

    def _add(self):
        sel = self.cand_list.curselection()
        if self.clicked is None or not sel:
            return
        d, e = self.cands[sel[0]]
        self.app.identify_add(self._region(), self.clicked,
                              self.xl.label_of(e))
        self._refresh_markers()

    def _auto(self):
        n = self.app.identify_auto(self._region())
        self.hint.config(text=f"{n} peak(s) labelled.")
        self._refresh_markers()

    def _refresh_markers(self):
        self.mark_list.delete(0, "end")
        for m in self.app.identify_markers(self._region()):
            self.mark_list.insert("end", f"{m['label']:<12} @ {m['be']:.2f} eV")

    def _remove(self):
        sel = self.mark_list.curselection()
        if not sel:
            return
        m = self.app.identify_markers(self._region())[sel[0]]
        self.app.identify_remove(self._region(), m)
        self._refresh_markers()

    def _clear(self):
        self.app.identify_clear(self._region())
        self._refresh_markers()
