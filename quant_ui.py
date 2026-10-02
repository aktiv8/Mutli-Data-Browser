"""The desktop "Quantification" tab: live at%/RSF numbers from this
codebase's own recomputation of a CasaXPS fit (``quant.py`` /
``resultspages.py``), for whatever is currently ticked in the tree -- the
same computation and dedup rules (a region "counted once", a preferred-line
exclusion, the RSF fallback tiers) the PDF/deck/HTML browser already show,
just not routed through a report. Embedded as a tab beside Images / Stage
map / CasaXPS quant (``Workspace._build_side_tabs`` / ``_refresh_info``),
shown only when at least one ticked region has a fit.

Unlike the CasaXPS-quant tab (``casaquant_ui.py``: CasaXPS's own *exported*
numbers, unconditionally shown when a folder had them), this tab has its own
RSF-library choice, independent of the Report generator's spec, so a
substitute can be explored live without touching report settings -- so it
calls ``resultspages.collect`` directly rather than through the memoized
``Workspace._results()``. A sample with no fit of its own (``sample.
casaxps`` only, i.e. ``levels`` empty) already has its home in the
CasaXPS-quant tab and is left out here rather than shown twice.

What the user can change here -- which regions count (the tick in the first
column), dividing the transmission function out, which depth level to show
(or the depth profile, in one of three modes) and writing the table as a CSV
-- lives in ``quantview.ViewState``; the numbers are recomputed from the
report's rows, never edited, and the report itself is not touched. The
ticks are keyed by what a region is (``quantview.entry_key``), so they
survive the tree being re-ticked and are saved, with the transmission choice
and the RSF library, in the workbook state.
"""

from __future__ import annotations

import csv
import tkinter as tk
from tkinter import filedialog, ttk

import quantview
import reportspec
import resultspages
import rsf as rsf_lib

RSF_OFF = "off"
RSF_LABELS = {RSF_OFF: "Off (no substitute)", **rsf_lib.LIBRARIES}
RSF_CHOICES = tuple(RSF_LABELS)

PROFILE_LABEL = "Depth profile"
TICK_ON, TICK_OFF = "☑", "☐"          # ballot box with / without check


class QuantPanel(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.samples = []
        self.sample = None
        self.view = quantview.ViewState()
        self._row_entry = {}            # tree row id -> entry index (ticks)
        self._level_of_row = None       # level index the rows belong to
        self._choices = []              # [(label, level index or None)]

        top = ttk.Frame(self)
        top.pack(side="top", fill="x", padx=6, pady=(6, 2))
        ttk.Label(top, text="Sample:").pack(side="left")
        self.sample_var = tk.StringVar()
        self.sample_box = ttk.Combobox(top, textvariable=self.sample_var,
                                       state="readonly", width=26)
        self.sample_box.pack(side="left", padx=(6, 12))
        self.sample_box.bind("<<ComboboxSelected>>",
                             lambda e: self._show_sample())

        ttk.Label(top, text="RSF:").pack(side="left")
        self.rsf_var = tk.StringVar(value=RSF_LABELS[RSF_OFF])
        self.rsf_box = ttk.Combobox(
            top, textvariable=self.rsf_var, state="readonly", width=32,
            values=[RSF_LABELS[k] for k in RSF_CHOICES])
        self.rsf_box.pack(side="left")
        self.rsf_box.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        mid = ttk.Frame(self)
        mid.pack(side="top", fill="x", padx=6, pady=(0, 2))
        ttk.Label(mid, text="Show:").pack(side="left")
        self.view_var = tk.StringVar()
        self.view_box = ttk.Combobox(mid, textvariable=self.view_var,
                                     state="readonly", width=26)
        self.view_box.pack(side="left", padx=(6, 12))
        self.view_box.bind("<<ComboboxSelected>>",
                           lambda e: self._view_chosen())
        self.mode_var = tk.StringVar(value=dict(
            quantview.PROFILE_MODES)[self.view.profile_mode])
        self.mode_box = ttk.Combobox(
            mid, textvariable=self.mode_var, state="disabled", width=28,
            values=[label for _k, label in quantview.PROFILE_MODES])
        self.mode_box.pack(side="left")
        self.mode_box.bind("<<ComboboxSelected>>",
                           lambda e: self._mode_chosen())

        bar = ttk.Frame(self)
        bar.pack(side="top", fill="x", padx=6, pady=(0, 2))
        self.trans_var = tk.BooleanVar(value=False)
        self.trans_check = ttk.Checkbutton(
            bar, text="Divide out the transmission function",
            variable=self.trans_var, command=self._transmission_toggled,
            state="disabled")
        self.trans_check.pack(side="left")
        self.export_btn = ttk.Button(bar, text="Export CSV…",
                                     command=self.export_csv)
        self.export_btn.pack(side="right")
        self.reset_btn = ttk.Button(bar, text="Reset ticks",
                                    command=self.reset_ticks)
        self.reset_btn.pack(side="right", padx=(0, 6))

        tree_frame = ttk.Frame(self)
        tree_frame.pack(side="top", fill="both", expand=True, padx=6, pady=6)
        self.tree = ttk.Treeview(tree_frame, show="tree headings", height=10)
        vsb = ttk.Scrollbar(tree_frame, orient="vertical",
                            command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.column("#0", width=34, minwidth=34, stretch=False,
                         anchor="center")
        self.tree.heading("#0", text="Use")
        self.tree.tag_configure("state", foreground="#5b6470")
        self.tree.tag_configure("off", foreground="#8a9099")
        self.tree.tag_configure("changed", font=("TkDefaultFont", 9, "bold"))
        self.tree.bind("<Button-1>", self._on_click)

        self.notes = tk.Text(self, height=3, wrap="word", relief="flat",
                             state="disabled")
        self.notes.pack(side="top", fill="x", padx=6, pady=(0, 6))

    # -- choices -----------------------------------------------------------
    def rsf_choice(self):
        """The chosen RSF library key ("off" or one of ``rsf.LIBRARIES``)."""
        label = self.rsf_var.get()
        return next((k for k in RSF_CHOICES if RSF_LABELS[k] == label),
                    RSF_OFF)

    def set_transmission(self, on):
        """Set (and show) the transmission choice; a no-op for the numbers
        when no row has a transmission-corrected area."""
        self.view.transmission = bool(on)
        self.trans_var.set(bool(on))
        self._show_sample()

    def _transmission_toggled(self):
        self.view.transmission = bool(self.trans_var.get())
        self._show_sample()

    def _view_chosen(self):
        if self.sample is None:
            return
        label = self.view_var.get()
        li = next((i for t, i in self._choices if t == label), 0)
        self.view.level[self.sample.key] = li
        self._show_sample()

    def _mode_chosen(self):
        label = self.mode_var.get()
        self.view.profile_mode = next(
            (k for k, t in quantview.PROFILE_MODES if t == label), "element")
        self._show_sample()

    def reset_ticks(self):
        """Back to the report's own choice of what counts."""
        self.view.reset(self.sample.key if self.sample else None)
        self._show_sample()

    def reset_all_ticks(self):
        """Back to the automatic choice for every sample (the Report
        generator's reset)."""
        self.view.reset()
        self._show_sample()

    # -- data --------------------------------------------------------------
    def refresh(self):
        """Reload from the app's ticked regions and this panel's own RSF
        choice; call whenever the ticks, files or annotations may have
        changed (``Workspace._refresh_info``)."""
        app = self.app
        rsf_key = self.rsf_choice()
        rsf_table = app.rsf_entries() if rsf_key != RSF_OFF else None
        results = resultspages.collect(
            app.docs, app._display, lambda p: reportspec.doc_key(p),
            app.casa_quant, ticked=lambda r: id(r) in app.checked,
            rsf_table=rsf_table, rsf_library=rsf_key,
            prefer_csv=bool(app.csv_curves_var.get()))
        # a sample with no fit of its own (CasaXPS's own export only) is
        # already shown in the "CasaXPS quant" tab -- not duplicated here
        self.samples = [s for s in results.samples if s.levels]
        self.sample_box["values"] = [s.label for s in self.samples]
        has_t = quantview.transmission_available(self.samples)
        self.trans_check.configure(state="normal" if has_t else "disabled")
        if not has_t and self.view.transmission:
            self.view.transmission = False
            self.trans_var.set(False)
        if not self.samples:
            self.sample_var.set("")
            self.sample = None
            self._show_sample()
            return
        key = self.sample.key if self.sample else None
        match = next((s for s in self.samples if s.key == key), None) \
            or self.samples[0]
        self.sample = match
        self.sample_var.set(match.label)
        self._show_sample()

    def _show_sample(self):
        label = self.sample_var.get()
        self.sample = next((s for s in self.samples if s.label == label),
                           None)
        self._row_entry = {}
        self._level_of_row = None
        if self.sample is None:
            self._choices = []
            self.view_box["values"] = []
            self.view_var.set("")
            self.view_box.configure(state="disabled")
            self.mode_box.configure(state="disabled")
            self.tree.configure(show="headings")
            self._set_columns(())
            self._fill([])
            self._set_notes([])
            return
        s = self.sample
        shown = self.view.shown(s)
        self._choices = ([(PROFILE_LABEL, None)] if s.is_profile else []) + [
            (quantview.level_label(lv, i), i) for i, lv in enumerate(s.levels)]
        self.view_box["values"] = [t for t, _i in self._choices]
        self.view_box.configure(
            state="readonly" if len(self._choices) > 1 else "disabled")
        self.view_var.set(next(t for t, i in self._choices if i == shown))
        self.mode_box.configure(state="readonly" if shown is None
                                else "disabled")
        self.mode_var.set(dict(quantview.PROFILE_MODES)[
            self.view.profile_mode])
        if shown is None:
            header, rows = quantview.profile_cells(s, self.view)
            self.tree.configure(show="headings")        # no tick column
            self._set_columns(header)
            self._fill([(None, r) for r in rows])
        else:
            self._level_of_row = shown
            eff = quantview.effective(s, shown, self.view)
            changed = quantview.changed(s, shown, self.view)
            self.tree.configure(show="tree headings")
            self._set_columns(resultspages.COMPOSITION_HEADER)
            self._fill(resultspages.composition_cells(eff),
                       ticks=(eff.include, changed))
        self._set_notes(s.notes)

    # -- ticks ---------------------------------------------------------------
    def _on_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "tree":
            return
        if self.tree.identify_column(event.x) != "#0":
            return
        iid = self.tree.identify_row(event.y)
        if iid in self._row_entry:
            self.toggle_row(iid)
            return "break"

    def toggle_row(self, iid):
        """Flip the tick of a region row (a state row has none)."""
        ei = self._row_entry.get(iid)
        if ei is None or self.sample is None or self._level_of_row is None:
            return
        lv = self.sample.levels[self._level_of_row]
        self.view.toggle(quantview.entry_key(
            self.sample, self._level_of_row, ei), lv.include[ei])
        self._show_sample()

    # -- output --------------------------------------------------------------
    def export_csv(self, path=None):
        """Write the table of every sample here (the ticks and the
        transmission choice applied) as a CSV; asks for the file unless
        ``path`` is given. Returns the path written, or None."""
        if not self.samples:
            return None
        if path is None:
            path = filedialog.asksaveasfilename(
                parent=self, defaultextension=".csv",
                initialfile="quantification.csv",
                filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if not path:
            return None
        rows = quantview.csv_table(self.samples, self.view)
        # UTF-8 with a BOM so Excel reads the Greek/degree signs
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            csv.writer(fh).writerows(rows)
        status = getattr(self.app, "status", None)
        if status is not None:
            status.config(text=f"Saved {path}")
        return path

    # -- table ---------------------------------------------------------------
    def _set_columns(self, header):
        cols = list(range(len(header)))
        self.tree["columns"] = cols
        for i, text in enumerate(header):
            self.tree.heading(i, text=text)
            self.tree.column(i, anchor="w" if i == 0 else "center",
                             width=140 if i == 0 else 100, stretch=True)

    def _fill(self, rows, ticks=None):
        self.tree.delete(*self.tree.get_children())
        self._row_entry = {}
        ei = -1
        for kind, cells in rows:
            tags, text = (("state",) if kind == "state" else ()), ""
            if ticks is not None and kind == "region":
                ei += 1
                inc, changed = ticks
                text = TICK_ON if inc[ei] else TICK_OFF
                if not inc[ei]:
                    tags += ("off",)
                if changed[ei]:
                    tags += ("changed",)
            iid = self.tree.insert("", "end", text=text, values=cells,
                                   tags=tags)
            if ticks is not None and kind == "region":
                self._row_entry[iid] = ei

    def _set_notes(self, notes):
        self.notes.configure(state="normal")
        self.notes.delete("1.0", "end")
        self.notes.insert("end", "\n".join(notes))
        self.notes.configure(state="disabled")
