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
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import reportspec
import resultspages
import rsf as rsf_lib

RSF_OFF = "off"
RSF_LABELS = {RSF_OFF: "Off (no substitute)", **rsf_lib.LIBRARIES}
RSF_CHOICES = tuple(RSF_LABELS)


class QuantPanel(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.samples = []
        self.sample = None

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

        tree_frame = ttk.Frame(self)
        tree_frame.pack(side="top", fill="both", expand=True, padx=6, pady=6)
        self.tree = ttk.Treeview(tree_frame, show="headings", height=10)
        vsb = ttk.Scrollbar(tree_frame, orient="vertical",
                            command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.tag_configure("state", foreground="#5b6470")

        self.notes = tk.Text(self, height=3, wrap="word", relief="flat",
                             state="disabled")
        self.notes.pack(side="top", fill="x", padx=6, pady=(0, 6))

    def rsf_choice(self):
        """The chosen RSF library key ("off" or one of ``rsf.LIBRARIES``)."""
        label = self.rsf_var.get()
        return next((k for k in RSF_CHOICES if RSF_LABELS[k] == label),
                    RSF_OFF)

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
        if self.sample is None:
            self._set_columns(())
            self._fill([])
            self._set_notes([])
            return
        if self.sample.is_profile:
            header, rows = resultspages.profile_cells(self.sample)
            self._set_columns(header)
            self._fill([(None, r) for r in rows])
        else:
            self._set_columns(resultspages.COMPOSITION_HEADER)
            self._fill(resultspages.composition_cells(self.sample.levels[0]))
        self._set_notes(self.sample.notes)

    def _set_columns(self, header):
        cols = list(range(len(header)))
        self.tree["columns"] = cols
        for i, text in enumerate(header):
            self.tree.heading(i, text=text)
            self.tree.column(i, anchor="w" if i == 0 else "center",
                             width=140 if i == 0 else 100, stretch=True)

    def _fill(self, rows):
        self.tree.delete(*self.tree.get_children())
        for kind, cells in rows:
            self.tree.insert("", "end", values=cells,
                             tags=("state",) if kind == "state" else ())

    def _set_notes(self, notes):
        self.notes.configure(state="normal")
        self.notes.delete("1.0", "end")
        self.notes.insert("end", "\n".join(notes))
        self.notes.configure(state="disabled")
