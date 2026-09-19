"""The *Sputter settings* dialog: the ion gun settings of each depth profile,
prefilled from the file where it states them. They give the depth and
fluence axes (``sputter.py``).

Talks to the app through ``app.sputter_samples()`` (what can be edited),
``app.sputter_get(item)``, ``app.sputter_set(item, settings)``,
``app.sputter_prefill(item)`` and ``app.palette`` / ``app.themes``. Not
modal; every edit is applied when the box is left or Return is pressed.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import sputter
from workbook_ui import _finish


class SputterDialog(tk.Toplevel):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.items = app.sputter_samples()
        self.title("Sputter settings")
        self.transient(master)
        self.sel = None
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        ttk.Label(body, style="Muted.TLabel", wraplength=560, justify="left",
                  text="Ion gun settings of each depth profile. With them a "
                       "waterfall or heat map can use Depth or Fluence as its "
                       "z axis (fluence = current × time ÷ (charge × e × "
                       "area)). Nothing is guessed: fill in what your "
                       "instrument used."
                  ).grid(row=0, column=0, columnspan=2, sticky="w",
                         pady=(0, 8))
        self.list = tk.Listbox(body, height=10, width=34,
                               exportselection=False, activestyle="none")
        self.list.grid(row=1, column=0, sticky="ns", padx=(0, 12))
        for it in self.items:
            self.list.insert("end", it["label"])
        self.list.bind("<<ListboxSelect>>", lambda e: self._on_select())

        form = ttk.Frame(body)
        form.grid(row=1, column=1, sticky="nsew")
        self.vars = {}
        rows = (("ion", "Ion", None), ("charge", "Charge state", None),
                ("energy_ev", "Energy", "eV"),
                ("current", "Current", "current_unit"),
                ("raster_x", "Raster width", "mm"),
                ("raster_y", "Raster height", "mm"),
                ("etch_rate", "Etch rate", "rate_unit"))
        for r, (key, label, unit) in enumerate(rows):
            ttk.Label(form, text=label).grid(row=r, column=0, sticky="w",
                                             pady=3, padx=(0, 10))
            v = tk.StringVar()
            e = ttk.Entry(form, textvariable=v, width=14)
            e.grid(row=r, column=1, sticky="w", pady=3)
            e.bind("<Return>", lambda ev: self._commit())
            e.bind("<FocusOut>", lambda ev: self._commit())
            self.vars[key] = v
            if unit in ("current_unit", "rate_unit"):
                uv = tk.StringVar()
                vals = list(sputter.CURRENT_UNITS if unit == "current_unit"
                            else sputter.RATE_UNITS)
                cb = ttk.Combobox(form, textvariable=uv, values=vals,
                                  width=8, state="readonly")
                cb.grid(row=r, column=2, padx=(6, 0))
                cb.bind("<<ComboboxSelected>>", lambda ev: self._commit())
                self.vars[unit] = uv
            elif unit:
                ttk.Label(form, text=unit, style="Muted.TLabel").grid(
                    row=r, column=2, sticky="w", padx=(6, 0))
        bar = ttk.Frame(form)
        bar.grid(row=len(rows), column=0, columnspan=3, sticky="w",
                 pady=(10, 4))
        for text, cmd in (("Prefill from file", self._prefill),
                          ("Apply to every sample of this file", self._all),
                          ("Clear", self._clear)):
            ttk.Button(bar, text=text, command=cmd).pack(side="left",
                                                         padx=(0, 6))
        self.info = ttk.Label(form, style="Muted.TLabel", wraplength=340,
                              justify="left")
        self.info.grid(row=len(rows) + 1, column=0, columnspan=3,
                       sticky="w", pady=(6, 0))
        ttk.Button(body, text="Close", command=self.destroy).grid(
            row=2, column=1, sticky="e", pady=(12, 0))
        self.bind("<Escape>", lambda e: self.destroy())
        _finish(self, app, 700, 470)
        self.list.configure(bg=app.palette["entry"], fg=app.palette["fg"],
                            selectbackground=app.palette["select_bg"],
                            selectforeground=app.palette["select_fg"],
                            highlightthickness=0, relief="flat")
        if self.items:
            self.list.selection_set(0)
            self._on_select()

    # -- reading and writing the form ------------------------------------------
    def _show(self, s):
        for k, var in self.vars.items():
            v = s.get(k)
            var.set("" if v is None else
                    (f"{v:g}" if isinstance(v, float) else str(v)))
        self._update_info(s)

    def _form(self):
        raw = {k: v.get().strip() for k, v in self.vars.items()}
        for k in sputter.NUMBER_KEYS + ("charge",):
            if raw[k] == "":
                raw[k] = None
        return sputter.sanitise(raw)

    def _update_info(self, s):
        it = self.items[self.sel] if self.sel is not None else None
        lines = []
        if it and it.get("t_max"):
            t = it["t_max"]
            fl, dp = sputter.fluence(s, t), sputter.depth_nm(s, t)
            bits = [f"After {t:g} s:"]
            bits.append(f"fluence {fl:.3g} ions/cm²" if fl else
                        "fluence needs the current and the raster size")
            bits.append(f"depth {dp:.3g} nm" if dp else
                        "depth needs the etch rate")
            lines.append("  ·  ".join(bits))
        elif it:
            lines.append("These spectra have no etch times, so no depth or "
                         "fluence can be worked out.")
        self.info.config(text="\n".join(lines))

    def _on_select(self):
        cur = self.list.curselection()
        self.sel = cur[0] if cur else None
        if self.sel is None:
            return
        it = self.items[self.sel]
        self._show(sputter.sanitise(self.app.sputter_get(it)))

    def _commit(self):
        if self.sel is None:
            return
        s = self._form()
        it = self.items[self.sel]
        if s != sputter.sanitise(self.app.sputter_get(it)):
            self.app.sputter_set(it, s)
        self._show(s)

    def _prefill(self):
        if self.sel is None:
            return
        it = self.items[self.sel]
        pre = self.app.sputter_prefill(it)
        if not pre:
            messagebox.showinfo("Sputter settings",
                                "This file does not state any ion gun "
                                "settings; enter them by hand.", parent=self)
            return
        cur = sputter.sanitise(self.app.sputter_get(it))
        merged = {k: cur[k] if cur[k] not in (None, "") else pre.get(k)
                  for k in cur}
        merged["current_unit"] = pre.get("current_unit", cur["current_unit"]) \
            if cur["current"] is None else cur["current_unit"]
        s = sputter.sanitise(merged)
        self.app.sputter_set(it, s)
        self._show(s)

    def _all(self):
        if self.sel is None:
            return
        s = self._form()
        it = self.items[self.sel]
        n = 0
        for other in self.items:
            if other["file"] == it["file"]:
                self.app.sputter_set(other, s)
                n += 1
        self._show(s)
        messagebox.showinfo("Sputter settings",
                            f"Applied to {n} sample(s) of this file.",
                            parent=self)

    def _clear(self):
        if self.sel is None:
            return
        self.app.sputter_set(self.items[self.sel], sputter.sanitise({}))
        self._show(sputter.sanitise({}))
