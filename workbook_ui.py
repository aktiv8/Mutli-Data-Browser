"""Dialogs for experiment workbooks and the AVG/VGD import prompt.

Kept out of ``escape_explorer.py``; each dialog talks to the app only through
a few attributes / methods (see the docstrings).
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

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
