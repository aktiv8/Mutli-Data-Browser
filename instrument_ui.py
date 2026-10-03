"""The *Instrument settings (NeXus)* dialog: what a NeXus file asks for and
instrument files rarely state (source type, analyser schemes, detector,
resolution, work function, affiliation), entered once per file
(``nexus_settings.py``). An unset field is left out of the ``.nxs``.

Talks to the app through ``app.instrument_files()`` (what can be edited),
``app.instrument_get(item)``, ``app.instrument_set(item, settings)`` and
``app.palette`` / ``app.themes``. Not modal; every edit is applied when a box
is left, Return is pressed or a choice is made.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import nexus_settings
from workbook_ui import _finish

NOT_SET = "(not set)"


class InstrumentDialog(tk.Toplevel):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.items = app.instrument_files()
        self.title("Instrument settings (NeXus)")
        self.transient(master)
        self.sel = None
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        ttk.Label(body, style="Muted.TLabel", wraplength=600, justify="left",
                  text="NeXus (NXxps) files ask for these and instrument files "
                       "rarely state them. Fill in what your instrument is; "
                       "anything left unset is left out of the .nxs, never "
                       "guessed. What you enter wins over what a file recorded."
                  ).grid(row=0, column=0, columnspan=2, sticky="w",
                         pady=(0, 8))
        self.list = tk.Listbox(body, height=10, width=30,
                               exportselection=False, activestyle="none")
        self.list.grid(row=1, column=0, sticky="ns", padx=(0, 12))
        for it in self.items:
            self.list.insert("end", it["label"])
        self.list.bind("<<ListboxSelect>>", lambda e: self._on_select())

        form = ttk.Frame(body)
        form.grid(row=1, column=1, sticky="nsew")
        self.vars = {}
        for r, (key, label, kind, choices) in enumerate(nexus_settings.FIELDS):
            ttk.Label(form, text=label).grid(row=r, column=0, sticky="w",
                                             pady=3, padx=(0, 10))
            v = tk.StringVar()
            if kind == "choice":
                w = ttk.Combobox(form, textvariable=v, state="readonly",
                                 values=[NOT_SET, *choices], width=28)
                w.bind("<<ComboboxSelected>>", lambda ev: self._commit())
            else:
                w = ttk.Entry(form, textvariable=v,
                              width=14 if kind == "number" else 30)
                w.bind("<Return>", lambda ev: self._commit())
                w.bind("<FocusOut>", lambda ev: self._commit())
            w.grid(row=r, column=1, sticky="w", pady=3)
            self.vars[key] = v
        n = len(nexus_settings.FIELDS)
        bar = ttk.Frame(form)
        bar.grid(row=n, column=0, columnspan=2, sticky="w", pady=(10, 4))
        for text, cmd in (("Use for every file", self._all),
                          ("Clear", self._clear)):
            ttk.Button(bar, text=text, command=cmd).pack(side="left",
                                                         padx=(0, 6))
        self.info = ttk.Label(form, style="Muted.TLabel", wraplength=380,
                              justify="left")
        self.info.grid(row=n + 1, column=0, columnspan=2, sticky="w",
                       pady=(6, 0))
        ttk.Button(body, text="Close", command=self.destroy).grid(
            row=2, column=1, sticky="e", pady=(12, 0))
        self.bind("<Escape>", lambda e: self.destroy())
        _finish(self, app, 760, 470)
        self.list.configure(bg=app.palette["entry"], fg=app.palette["fg"],
                            selectbackground=app.palette["select_bg"],
                            selectforeground=app.palette["select_fg"],
                            highlightthickness=0, relief="flat")
        if self.items:
            self.list.selection_set(0)
            self._on_select()

    # -- reading and writing the form ------------------------------------------
    def _show(self, s):
        for key, var in self.vars.items():
            v = s.get(key)
            if v is None:
                var.set(NOT_SET if nexus_settings._KIND[key] == "choice" else "")
            else:
                var.set(f"{v:g}" if isinstance(v, float) else str(v))
        self._update_info()

    def _form(self):
        raw = {k: ("" if v.get() == NOT_SET else v.get().strip())
               for k, v in self.vars.items()}
        return nexus_settings.sanitise(raw)

    def _update_info(self):
        it = self.items[self.sel] if self.sel is not None else None
        rec = (it or {}).get("recorded") or {}
        if rec:
            text = "The file itself records: " + "; ".join(
                f"{k} = {v}" for k, v in rec.items())
        else:
            text = "The file records none of these."
        self.info.config(text=text)

    def _on_select(self):
        cur = self.list.curselection()
        self.sel = cur[0] if cur else None
        if self.sel is None:
            return
        self._show(nexus_settings.sanitise(
            self.app.instrument_get(self.items[self.sel])))

    def _commit(self):
        if self.sel is None:
            return
        s = self._form()
        it = self.items[self.sel]
        if s != nexus_settings.sanitise(self.app.instrument_get(it)):
            self.app.instrument_set(it, s)
        self._show(s)

    def _all(self):
        if self.sel is None:
            return
        s = self._form()
        for it in self.items:
            self.app.instrument_set(it, s)
        self._show(s)
        messagebox.showinfo("Instrument settings",
                            f"Applied to {len(self.items)} file(s).",
                            parent=self)

    def _clear(self):
        if self.sel is None:
            return
        self.app.instrument_set(self.items[self.sel], {})
        self._show({})
