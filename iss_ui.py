"""The *ISS / REELS* dialog.

**ISS**: click a peak on the plot to list the elements that scatter the ion
there (single binary collision, see ``elements``), add the one you want as a
marker, or mark the elements you expect. Markers sit at kinetic energies, so
they do not move with a binding-energy calibration.

**REELS**: the band gap from the onset of energy losses (see ``reels``). Find
the elastic peak, then click two points on the rising edge of the loss
spectrum: the tangent through them meets the baseline at the gap.

The dialog talks to the app through ``app.spectrum_regions()``,
``app.calibration_label``, ``app.kinetic_from_event``, ``app.data_from_event``,
``app.click_panel_spectra``, ``app.identify_*`` (peak markers),
``app.reels_get/reels_set``, ``app._click_cb`` and ``app.cfg``. Not modal.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import elements
import reels
from workbook_ui import _finish


class IssReelsDialog(tk.Toplevel):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.regions = app.spectrum_regions()
        self.mode = None                  # None / "elastic" / "onset1" / "onset2"
        self.onset = []                   # picked (loss, intensity) points
        self.cands = []
        self.title("ISS / REELS")
        self.transient(master)
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        ttk.Label(body, text="Spectrum").grid(row=0, column=0, sticky="w",
                                              padx=(0, 8))
        self.reg_cb = ttk.Combobox(
            body, state="readonly", width=48,
            values=[app.calibration_label(r) for r in self.regions])
        self.reg_cb.grid(row=0, column=1, sticky="ew")
        self.reg_cb.current(0)
        self.reg_cb.bind("<<ComboboxSelected>>", lambda e: self._region_changed())
        self.hint = ttk.Label(body, style="Muted.TLabel", wraplength=470,
                              justify="left")
        self.hint.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 4))
        self.nb = ttk.Notebook(body)
        self.nb.grid(row=2, column=0, columnspan=2, sticky="nsew")
        body.rowconfigure(2, weight=1)
        self.iss_tab = ttk.Frame(self.nb, padding=8)
        self.reels_tab = ttk.Frame(self.nb, padding=8)
        self.nb.add(self.iss_tab, text="ISS peaks")
        self.nb.add(self.reels_tab, text="REELS band gap")
        self._build_iss()
        self._build_reels()
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self._tab_changed())
        ttk.Button(body, text="Close", command=self.destroy).grid(
            row=3, column=1, sticky="e", pady=(10, 0))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Destroy>", lambda e: self._detach()
                  if e.widget is self else None)
        _finish(self, app, 560, 640)
        for lb in (self.cand_list, self.mark_list):
            lb.configure(bg=app.palette["entry"], fg=app.palette["fg"],
                         selectbackground=app.palette["select_bg"],
                         selectforeground=app.palette["select_fg"],
                         highlightthickness=0, relief="flat")
        app._click_cb = self._on_click
        self._region_changed()

    # -- ISS tab ---------------------------------------------------------------------
    def _build_iss(self):
        t = self.iss_tab
        t.columnconfigure(1, weight=1)
        cfg = self.app.cfg.get("iss", {})
        self.ion = tk.StringVar(value=cfg.get("ion", elements.DEFAULT_ION)
                                if cfg.get("ion") in elements.ION_MASS
                                else elements.DEFAULT_ION)
        self.e0 = tk.StringVar()
        self.theta = tk.StringVar(value=str(cfg.get(
            "theta", elements.DEFAULT_THETA)))
        row = ttk.Frame(t)
        row.grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(row, text="Ion").pack(side="left")
        cb = ttk.Combobox(row, textvariable=self.ion, width=6,
                          state="readonly", values=list(elements.ION_MASS))
        cb.pack(side="left", padx=(4, 12))
        cb.bind("<<ComboboxSelected>>", lambda e: self._save_settings())
        ttk.Label(row, text="Beam energy (eV)").pack(side="left")
        e = ttk.Entry(row, textvariable=self.e0, width=8)
        e.pack(side="left", padx=(4, 12))
        ttk.Label(row, text="Scattering angle (°)").pack(side="left")
        a = ttk.Entry(row, textvariable=self.theta, width=8)
        a.pack(side="left", padx=4)
        for w in (e, a):
            w.bind("<Return>", lambda ev: self._save_settings())
            w.bind("<FocusOut>", lambda ev: self._save_settings())
        ttk.Label(t, text="Candidates").grid(row=1, column=0, sticky="w",
                                             pady=(10, 0))
        self.cand_list = tk.Listbox(t, height=6, exportselection=False,
                                    activestyle="none")
        self.cand_list.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.cand_list.bind("<Double-Button-1>", lambda e: self._add())
        row = ttk.Frame(t)
        row.grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 6))
        ttk.Button(row, text="Add marker", command=self._add).pack(side="left")
        ttk.Label(row, text="   or mark elements").pack(side="left")
        self.symbols = tk.StringVar()
        se = ttk.Entry(row, textvariable=self.symbols, width=16)
        se.pack(side="left", padx=4)
        se.bind("<Return>", lambda ev: self._mark_elements())
        ttk.Button(row, text="Mark", command=self._mark_elements).pack(
            side="left")
        ttk.Label(t, text="Markers on this spectrum").grid(
            row=4, column=0, sticky="w")
        self.mark_list = tk.Listbox(t, height=6, exportselection=False,
                                    activestyle="none")
        self.mark_list.grid(row=5, column=0, columnspan=2, sticky="ew")
        row = ttk.Frame(t)
        row.grid(row=6, column=0, sticky="w", pady=(4, 0))
        ttk.Button(row, text="Remove selected", command=self._remove).pack(
            side="left")
        ttk.Button(row, text="Clear all", command=self._clear).pack(
            side="left", padx=(6, 0))

    # -- REELS tab -------------------------------------------------------------------
    def _build_reels(self):
        t = self.reels_tab
        t.columnconfigure(1, weight=1)
        ttk.Label(t, text="Elastic peak (eV KE)").grid(row=0, column=0,
                                                      sticky="w")
        self.elastic = tk.StringVar()
        ee = ttk.Entry(t, textvariable=self.elastic, width=10)
        ee.grid(row=0, column=1, sticky="w", padx=6)
        ee.bind("<Return>", lambda ev: self._recompute())
        ee.bind("<FocusOut>", lambda ev: self._recompute())
        row = ttk.Frame(t)
        row.grid(row=1, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Button(row, text="Find the maximum", command=self._auto_elastic
                   ).pack(side="left")
        ttk.Button(row, text="Pick on the plot",
                   command=lambda: self._arm("elastic")).pack(
            side="left", padx=6)
        ttk.Separator(t).grid(row=2, column=0, columnspan=2, sticky="ew",
                              pady=6)
        ttk.Button(t, text="Pick the onset: two clicks on the rising edge",
                   command=self._arm_onset).grid(row=3, column=0,
                                                 columnspan=2, sticky="w")
        self.result = ttk.Label(t, wraplength=470, justify="left",
                                font=("", 11, "bold"))
        self.result.grid(row=4, column=0, columnspan=2, sticky="w",
                         pady=(10, 4))
        self.detail = ttk.Label(t, style="Muted.TLabel", wraplength=470,
                                justify="left")
        self.detail.grid(row=5, column=0, columnspan=2, sticky="w")
        ttk.Button(t, text="Clear the band gap",
                   command=self._clear_reels).grid(row=6, column=0,
                                                   sticky="w", pady=(10, 0))

    # -- shared -----------------------------------------------------------------------
    def _detach(self):
        if self.app._click_cb == self._on_click:
            self.app._click_cb = None

    def _region(self):
        return self.regions[self.reg_cb.current()]

    def _tab_changed(self):
        self.mode = None
        self.onset = []
        self._set_hint()

    def _set_hint(self):
        if self.mode == "elastic":
            text = "Click the top of the elastic peak."
        elif self.mode in ("onset1", "onset2"):
            n = 1 if self.mode == "onset1" else 2
            text = (f"Click point {n} of 2 on the rising edge of the loss "
                    f"spectrum (on the plot).")
        elif self.nb.index(self.nb.select()) == 0:
            text = ("Click a peak on the plot to see which elements scatter "
                    "the ion there. Only tick the spectrum you are "
                    "analysing.")
        else:
            text = ("Set the elastic peak, then pick the onset. Tick only "
                    "the spectrum you are analysing.")
        self.hint.config(text=text)

    def _region_changed(self):
        r = self._region()
        hv = r.photon_energy
        if not self.e0.get():
            self.e0.set(f"{hv:g}" if hv and 50 <= hv <= 10000 else "1000")
        self._refresh_markers()
        self._show_reels()
        self._set_hint()

    def _save_settings(self):
        self.app.cfg["iss"] = {"ion": self.ion.get(),
                               "theta": self._theta()}

    def _num(self, var, default):
        try:
            v = float(var.get())
            return v if v > 0 else default
        except ValueError:
            return default

    def _theta(self):
        return self._num(self.theta, elements.DEFAULT_THETA)

    def _e0(self):
        return self._num(self.e0, 1000.0)

    def _on_click(self, _be, event):
        if self.app.click_panel_spectra(event) != 1:
            self.hint.config(text="That panel shows several spectra. Tick "
                                  "only the spectrum you are analysing.")
            return
        ke = self.app.kinetic_from_event(self._region(), event)
        if ke is None:
            self.hint.config(text="The photon energy is not known, so the "
                                  "click cannot be turned into a kinetic "
                                  "energy.")
            return
        if self.nb.index(self.nb.select()) == 0:
            self._on_iss_click(ke)
        else:
            self._on_reels_click(ke, event)

    # -- ISS --------------------------------------------------------------------------
    def _on_iss_click(self, ke):
        self.clicked = ke
        self.cands = elements.candidates(ke, self._e0(), self.ion.get(),
                                         self._theta())
        self.cand_list.delete(0, "end")
        for c in self.cands:
            self.cand_list.insert(
                "end", f"{c['symbol']:<3} {c['name']:<13} "
                       f"{c['energy']:8.1f} eV   ({c['delta']:+.1f})")
        if self.cands:
            self.cand_list.selection_set(0)
        self.hint.config(text=f"Peak at {ke:.1f} eV kinetic energy: "
                              f"{len(self.cands)} element(s) within "
                              f"±{0.005 * self._e0() + 2:.1f} eV.")

    def _add(self):
        sel = self.cand_list.curselection()
        if not sel or not hasattr(self, "clicked"):
            return
        c = self.cands[sel[0]]
        self.app.identify_add(self._region(), self.clicked, c["symbol"],
                              kin=True)
        self._refresh_markers()

    def _mark_elements(self):
        syms = elements.parse_symbols(self.symbols.get())
        if not syms:
            messagebox.showinfo("ISS", "Type element symbols, e.g. "
                                       "'Cu Au Ni'.", parent=self)
            return
        r = self._region()
        lo, hi = min(r.energy), max(r.energy)
        marks = elements.marks_for(syms, self._e0(), self.ion.get(),
                                   self._theta())
        inside = [(s, e) for s, e in marks if lo <= e <= hi] \
            if self._is_ke(r) else marks
        for sym, e in inside:
            self.app.identify_add(r, e, sym, kin=True)
        left = [s for s in syms if s not in [m[0] for m in inside]]
        if left:
            self.hint.config(text="Not marked (outside the spectrum, or the "
                                  "ion cannot scatter from them): "
                                  + ", ".join(left))
        self._refresh_markers()

    @staticmethod
    def _is_ke(r):
        return "kinetic" in (r.energy_label or "").lower()

    def _refresh_markers(self):
        self.mark_list.delete(0, "end")
        for m in self.app.identify_markers(self._region()):
            self.mark_list.insert(
                "end", f"{m['label']:<8} @ {m['be']:.1f} eV"
                       f"{' KE' if m.get('kin') else ' BE'}")

    def _remove(self):
        sel = self.mark_list.curselection()
        if sel:
            m = self.app.identify_markers(self._region())[sel[0]]
            self.app.identify_remove(self._region(), m)
            self._refresh_markers()

    def _clear(self):
        self.app.identify_clear(self._region())
        self._refresh_markers()

    # -- REELS -------------------------------------------------------------------------
    def _elastic(self):
        try:
            return float(self.elastic.get())
        except ValueError:
            return None

    def _ke_counts(self):
        r = self._region()
        d = self.app._display(r)
        if self._is_ke(d):
            return list(d.energy), list(d.counts)
        if d.photon_energy:
            return [d.photon_energy - e for e in d.energy], list(d.counts)
        return None, None

    def _auto_elastic(self):
        ke, counts = self._ke_counts()
        e = reels.elastic_peak(ke, counts) if ke else None
        if e is None:
            messagebox.showinfo("REELS", "The kinetic energies are not "
                                         "known for this spectrum.",
                                parent=self)
            return
        self.elastic.set(f"{e:.2f}")
        self._recompute()

    def _arm(self, mode):
        self.mode = mode
        self.onset = []
        self._set_hint()

    def _arm_onset(self):
        if self._elastic() is None:
            self._auto_elastic()
            if self._elastic() is None:
                return
        self._arm("onset1")

    def _on_reels_click(self, ke, event):
        if self.mode == "elastic":
            self.elastic.set(f"{ke:.2f}")
            self.mode = None
            self._set_hint()
            self._recompute()
            return
        if self.mode not in ("onset1", "onset2"):
            self.hint.config(text="Press 'Pick the onset' first (or 'Pick on "
                                  "the plot' for the elastic peak).")
            return
        y = self.app.data_from_event(self._region(), event)
        el = self._elastic()
        if y is None or el is None:
            return
        self.onset.append((el - ke, y))
        if self.mode == "onset1":
            self.mode = "onset2"
            self._set_hint()
            return
        self.mode = None
        self._recompute()
        self._set_hint()

    def _recompute(self):
        """Store the construction (and its gap, once two points are known)."""
        el = self._elastic()
        if el is None:
            return
        old = self.app.reels_get(self._region()) or {}
        p1 = self.onset[0] if len(self.onset) >= 2 else old.get("p1")
        p2 = self.onset[1] if len(self.onset) >= 2 else old.get("p2")
        if not (p1 and p2):
            return
        ke, counts = self._ke_counts()
        loss = reels.loss_axis(ke, el)
        res = reels.band_gap(loss, counts, tuple(p1), tuple(p2))
        data = {"elastic": el, "p1": list(p1), "p2": list(p2)}
        if res:
            data.update(res)
        self.app.reels_set(self._region(), data)
        self._show_reels()

    def _show_reels(self):
        d = self.app.reels_get(self._region())
        if not d:
            self.result.config(text="No band gap yet")
            self.detail.config(text="")
            return
        self.elastic.set(f"{d['elastic']:.2f}")
        if d.get("gap") is None:
            self.result.config(text="The two points do not give a gap")
            self.detail.config(text="They must lie on a rising edge whose "
                                    "tangent meets the baseline at a "
                                    "positive loss. Pick them again.")
        else:
            self.result.config(text=f"Band gap  Eg = {d['gap']:.2f} eV")
            self.detail.config(
                text=f"Tangent slope {d['slope']:.4g} per eV, baseline "
                     f"{d['base']:.4g}, elastic peak at {d['elastic']:.2f} "
                     f"eV. It is drawn on the plot and stored with the "
                     f"workbook.")

    def _clear_reels(self):
        self.app.reels_set(self._region(), None)
        self.onset = []
        self._show_reels()
