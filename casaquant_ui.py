"""The CasaXPS export panel: read-only tables of the quantification CasaXPS
itself exported into the loaded folder (see ``casaquant.py``) --
Quant_survey.txt, Quant_regions.txt and, for carbon materials,
Quant_Dparam.txt. Embedded as a tab beside Images / Stage map
(``Workspace._build_side_tabs`` / ``_refresh_info``), shown only when a
loaded folder had any of these files. Nothing here is editable: these are
not the app's own numbers, so they are shown exactly as CasaXPS wrote them.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class CasaQuantPanel(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app

        top = ttk.Frame(self)
        top.pack(side="top", fill="x", padx=6, pady=(6, 2))
        ttk.Label(top, text="Sample:").pack(side="left")
        self.sample_var = tk.StringVar()
        self.sample_box = ttk.Combobox(top, textvariable=self.sample_var,
                                       state="readonly", width=30)
        self.sample_box.pack(side="left", padx=(6, 0))
        self.sample_box.bind("<<ComboboxSelected>>",
                             lambda e: self._show_sample())

        self.nb = ttk.Notebook(self)
        self.nb.pack(side="top", fill="both", expand=True, padx=6, pady=6)
        self.survey_tab = self._make_tree_tab("Survey", ("Element", "%Conc"))
        self.regions_tab = self._make_tree_tab(
            "Regions", ("Name", "Position (eV)", "%At Conc"))
        self.dparam_tab = self._make_tree_tab("D parameter",
                                              ("Name", "FWHM (eV)"))

    def _make_tree_tab(self, title, columns):
        frame = ttk.Frame(self.nb)
        self.nb.add(frame, text=title)
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=8)
        for c in columns:
            tree.heading(c, text=c)
            tree.column(c, width=120, anchor="center", stretch=True)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        frame.tree = tree
        return frame

    def refresh(self):
        """Reload from ``self.app.casa_quant``; call whenever it may have
        changed (a folder was opened, a workbook was opened or reset)."""
        q = self.app.casa_quant
        names = sorted(q.samples) if q else []
        self.sample_box["values"] = names
        if not names:
            self.sample_var.set("")
            self._show_sample()
            return
        if self.sample_var.get() not in names:
            self.sample_var.set(names[0])
        self._show_sample()

    def _show_sample(self):
        q = self.app.casa_quant
        sample = q.samples.get(self.sample_var.get()) if q else None
        if sample is None:
            self._fill(self.survey_tab.tree, [])
            self._fill(self.regions_tab.tree, [])
            self._fill(self.dparam_tab.tree, [])
            self.nb.tab(self.dparam_tab, state="hidden")
            return
        self._fill(self.survey_tab.tree,
                  [(r["element"], _pct(r["pct"])) for r in sample.survey])
        self._fill(self.regions_tab.tree,
                  [(r["name"], _num(r["position"]), _pct(r["at_pct"]))
                   for r in sample.regions])
        self._fill(self.dparam_tab.tree,
                  [(r["name"], _num(r["fwhm"])) for r in sample.dparam])
        self.nb.tab(self.dparam_tab,
                   state="normal" if sample.dparam else "hidden")

    @staticmethod
    def _fill(tree, rows):
        tree.delete(*tree.get_children())
        for row in rows:
            tree.insert("", "end", values=row)


def _num(v):
    return "" if v is None else f"{v:g}"


def _pct(v):
    return "" if v is None else f"{v:.2f}"
