"""The *Report generator*: choose what the report contains, and in what order,
once for the PDF, the slides and the hand-over package.

Left, the contents: every section with a tick, what it holds ("6 figures",
or why it is empty), figures and files as children that can be ticked one by
one, and Move up / Move down. Right, the cover details and the options. Below,
named presets, the output (PDF, PowerPoint or both) and *Generate*.

Every change is applied to the app straight away (``app.set_report_spec``), so
the choice is remembered and the *Save PDF* / *Export PowerPoint* menu items
use it too. The behaviour is in plain methods (``toggle_section``,
``move_selected``, ``apply_preset`` ...) and the event handlers only call them.
Not modal. Talks to the app through ``report_spec``, ``report_presets``,
``report_inventory()``, ``set_report_spec()``, ``set_report_presets()``,
``details`` / ``logo``, ``edit_details()``, ``preview_report()`` and
``generate_report(kind)``.
"""

from __future__ import annotations

import base64
import os
import tkinter as tk
from tkinter import (colorchooser, filedialog, messagebox, simpledialog,
                     ttk)

import covers
import reportspec
from workbook_ui import _finish

ON, OFF = "☑", "☐"
COLLAPSE_ABOVE = 6            # a section with more children starts collapsed


class ReportGeneratorDialog(tk.Toplevel):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.title("Report generator")
        self.transient(master)
        self.spec = reportspec.sanitise(app.report_spec)
        self.inv = app.report_inventory()
        self.open = {sid: len(self.inv.children.get(sid, ())) <= COLLAPSE_ABOVE
                     for sid in reportspec.SECTION_IDS}
        self.rows = {}                        # tree iid -> (section, child|None)
        self.output = tk.StringVar(value="pdf")
        self.sha = tk.StringVar(value=reportspec.option(self.spec, "sha"))
        self.dividers = tk.StringVar(
            value=reportspec.option(self.spec, "dividers"))
        self.preset = tk.StringVar()
        self._build()
        self.populate()
        self.bind("<Escape>", lambda e: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)
        _finish(self, app, 960, 660)
        self.minsize(820, 560)

    # -- layout ----------------------------------------------------------------
    def _build(self):
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(1, weight=1)

        ttk.Label(body, style="Muted.TLabel", wraplength=840, justify="left",
                  text="Tick what goes in the report and put it in the order "
                       "you want. The same choice is used for the PDF, the "
                       "slides and the hand-over package; it is remembered, "
                       "and saved with the workbook. Click a box to tick it; "
                       "double-click a row marked ▸ to list its figures or "
                       "files and tick them one by one."
                  ).grid(row=0, column=0, columnspan=2, sticky="w",
                         pady=(0, 8))

        left = ttk.LabelFrame(body, text="Contents", padding=8)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(left, columns=("on", "name", "info"),
                                 show="headings", selectmode="browse",
                                 height=12)
        self.tree.heading("on", text="")
        self.tree.heading("name", text="Section")
        self.tree.heading("info", text="Holds")
        self.tree.column("on", width=34, minwidth=34, stretch=False,
                         anchor="center")
        self.tree.column("name", width=215, minwidth=150)
        self.tree.column("info", width=235, minwidth=140)
        self.tree.tag_configure("dim", foreground="#8a8f98")
        self.tree.tag_configure("child", foreground="#5b6470")
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<Button-1>", self._click)
        self.tree.bind("<Double-1>", self._double)
        self.tree.bind("<space>", lambda e: self._toggle_selected())
        bar = ttk.Frame(left)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(bar, text="▲ Move up",
                   command=lambda: self.move_selected(-1)).pack(side="left")
        ttk.Button(bar, text="▼ Move down",
                   command=lambda: self.move_selected(1)).pack(
            side="left", padx=(6, 0))
        ttk.Button(bar, text="Select none",
                   command=lambda: self.select_all(False)).pack(side="right")
        ttk.Button(bar, text="Select all",
                   command=lambda: self.select_all(True)).pack(
            side="right", padx=(0, 6))
        self.summary = ttk.Label(left, style="Muted.TLabel", wraplength=430,
                                 justify="left")
        self.summary.grid(row=2, column=0, columnspan=2, sticky="w",
                          pady=(8, 0))

        right = ttk.Notebook(body)
        right.grid(row=1, column=1, sticky="nsew")
        self._cover_tab(right)
        self._options_tab(right)

        bottom = ttk.Frame(body)
        bottom.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        bottom.columnconfigure(1, weight=1)
        ttk.Label(bottom, text="Preset").grid(row=0, column=0, sticky="w")
        self.preset_box = ttk.Combobox(bottom, textvariable=self.preset,
                                       state="readonly", width=26)
        self.preset_box.grid(row=0, column=1, sticky="w", padx=6)
        self.preset_box.bind("<<ComboboxSelected>>",
                             lambda e: self.apply_preset(self.preset.get()))
        ttk.Button(bottom, text="Save as…",
                   command=self._ask_save_preset).grid(row=0, column=2)
        ttk.Button(bottom, text="Delete",
                   command=self._delete_preset).grid(row=0, column=3,
                                                     padx=(6, 0))
        out = ttk.Frame(bottom)
        out.grid(row=1, column=0, columnspan=4, sticky="w", pady=(10, 0))
        ttk.Label(out, text="Make").pack(side="left")
        for value, text in (("pdf", "PDF report"), ("pptx", "PowerPoint deck"),
                            ("both", "Both")):
            ttk.Radiobutton(out, text=text, value=value,
                            variable=self.output).pack(side="left",
                                                       padx=(12, 0))
        act = ttk.Frame(bottom)
        act.grid(row=2, column=0, columnspan=4, sticky="e", pady=(12, 0))
        ttk.Button(act, text="Close", command=self.close).pack(side="right")
        ttk.Button(act, text="Generate…", command=self.generate).pack(
            side="right", padx=(0, 6))
        ttk.Button(act, text="Preview PDF", command=self.preview).pack(
            side="right", padx=(0, 6))
        self._refresh_presets()

    def _cover_tab(self, nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="Cover")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        ttk.Label(tab, text="Cover picture").grid(row=0, column=0,
                                                  sticky="w")
        holder = ttk.Frame(tab)
        holder.grid(row=1, column=0, sticky="nsew", pady=(4, 6))
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        self.cover_canvas = tk.Canvas(holder, highlightthickness=0,
                                      bg=self.app.palette["bg"], height=230)
        sb = ttk.Scrollbar(holder, orient="vertical",
                           command=self.cover_canvas.yview)
        self.cover_canvas.configure(yscrollcommand=sb.set)
        self.cover_canvas.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self.cover_list = ttk.Frame(self.cover_canvas)
        self.cover_canvas.create_window((0, 0), window=self.cover_list,
                                        anchor="nw")
        self.cover_list.bind("<Configure>", lambda e: self.cover_canvas
                             .configure(scrollregion=self.cover_canvas
                                        .bbox("all")))
        self.cover_canvas.bind("<MouseWheel>", lambda e: self.cover_canvas
                               .yview_scroll(-1 * (e.delta // 120), "units"))
        self.design = tk.StringVar(
            value=reportspec.cover_of(self.spec)["design"])
        self._thumbs = []
        self.build_cover_list()

        row = ttk.Frame(tab)
        row.grid(row=2, column=0, sticky="ew")
        ttk.Button(row, text="Use my own picture…",
                   command=self._browse_picture).pack(side="left")
        acc = ttk.Frame(tab)
        acc.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(acc, text="Colour").pack(side="left")
        for name, hexv in covers.ACCENTS:
            b = tk.Button(acc, bg=hexv, activebackground=hexv, width=2,
                          relief="flat", borderwidth=1,
                          command=lambda h=hexv: self.set_accent(h))
            b.pack(side="left", padx=(5, 0))
        ttk.Button(acc, text="Other…",
                   command=self._pick_accent).pack(side="left", padx=(8, 0))
        self.cover_text = ttk.Label(tab, style="Muted.TLabel", wraplength=340,
                                    justify="left")
        self.cover_text.grid(row=4, column=0, sticky="w", pady=(10, 2))
        ttk.Button(tab, text="Edit details…",
                   command=self._edit_details).grid(row=5, column=0,
                                                    sticky="w")
        self.refresh_cover()

    # -- the cover picture -----------------------------------------------------------
    def build_cover_list(self):
        """(Re)draw the picker: one radio-style entry per design, each with a
        small picture of what it looks like in the current colour."""
        for w in self.cover_list.winfo_children():
            w.destroy()
        self._thumbs = []
        cover = reportspec.cover_of(self.spec)
        entries = [(c.id, c.name, {"design": c.id, "accent": cover["accent"]})
                   for c in covers.list_covers()]
        if cover["design"] == "image":
            name = os.path.basename(cover["image"]) or "picture"
            entries.append(("image", "Your picture: " + name, cover))
        data = self.app.cover_data()
        for design, name, spec in entries:
            png = covers.thumbnail(spec, data)
            kw = {}
            if png:
                img = tk.PhotoImage(data=base64.b64encode(png))
                self._thumbs.append(img)
                kw = {"image": img, "compound": "top"}
            rb = tk.Radiobutton(
                self.cover_list, text=name, value=design, variable=self.design,
                indicatoron=False, anchor="w", padx=6, pady=4,
                bg=self.app.palette["bg"], fg=self.app.palette["fg"],
                selectcolor=self.app.palette["panel"],
                activebackground=self.app.palette["bg"],
                command=lambda d=design: self.set_cover(design=d), **kw)
            rb.pack(fill="x", pady=1)
            rb.bind("<MouseWheel>", lambda e: self.cover_canvas.yview_scroll(
                -1 * (e.delta // 120), "units"))

    def set_cover(self, **changes):
        """Change the cover (``design``, ``image``, ``accent``); applied to
        the app at once."""
        old = reportspec.cover_of(self.spec)
        self._set(reportspec.with_cover(self.spec, **changes))
        new = reportspec.cover_of(self.spec)
        self.design.set(new["design"])
        if new["accent"] != old["accent"] or new["image"] != old["image"]:
            self.build_cover_list()
        self.refresh_cover()

    def set_accent(self, hexv):
        self.set_cover(accent=covers.valid_accent(hexv))

    def choose_picture(self, path):
        """Use the picture at ``path`` as the cover."""
        self.set_cover(design="image", image=path)

    def _browse_picture(self):
        path = filedialog.askopenfilename(
            parent=self, title="Cover picture",
            filetypes=[("Pictures", "*.png *.jpg *.jpeg *.gif"),
                       ("All files", "*.*")])
        if path:
            self.choose_picture(path)

    def _pick_accent(self):
        cur = reportspec.cover_of(self.spec)["accent"] or covers.DEFAULT_ACCENT
        _rgb, hexv = colorchooser.askcolor(color=cur, parent=self,
                                           title="Cover colour")
        if hexv:
            self.set_accent(hexv)

    def _options_tab(self, nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="Options")
        ttk.Label(tab, text="Checksums (SHA-256) in the file list").pack(
            anchor="w")
        for value, text in (("short", "Show the first 16 characters"),
                            ("none", "Leave them out")):
            ttk.Radiobutton(tab, text=text, value=value, variable=self.sha,
                            command=lambda: self.set_option(
                                "sha", self.sha.get())).pack(
                anchor="w", padx=(12, 0), pady=2)
        ttk.Label(tab, text="Divider slides in the PowerPoint").pack(
            anchor="w", pady=(14, 0))
        for value, text in (("auto", "Before a section of 5 slides or more"),
                            ("none", "Never")):
            ttk.Radiobutton(tab, text=text, value=value,
                            variable=self.dividers,
                            command=lambda: self.set_option(
                                "dividers", self.dividers.get())).pack(
                anchor="w", padx=(12, 0), pady=2)

    # -- the tree ----------------------------------------------------------------
    def populate(self):
        """Redraw the rows from ``self.spec`` (keeps the selection)."""
        keep = self.tree.selection()
        keep_key = self.rows.get(keep[0]) if keep else None
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        skip = self.spec["skip"]
        for item in self.spec["sections"]:
            sid = item["id"]
            present = self.inv.present.get(sid, False)
            kids = self.inv.children.get(sid, [])
            mark = ON if (item["on"] and present) else OFF
            arrow = ""
            if len(kids) > 1:
                arrow = "▾ " if self.open.get(sid) else "▸ "
            iid = self.tree.insert(
                "", "end", values=(mark, arrow + reportspec.LABELS[sid],
                                   self.inv.summary(sid) or
                                   reportspec.HINTS[sid]),
                tags=() if present else ("dim",))
            self.rows[iid] = (sid, None)
            if len(kids) > 1 and self.open.get(sid):
                off = set(skip.get(sid, ()))
                for cid, label in kids:
                    ciid = self.tree.insert(
                        "", "end", tags=("child",),
                        values=(ON if (cid not in off and item["on"]
                                       and present) else OFF,
                                "      " + label, ""))
                    self.rows[ciid] = (sid, cid)
        for iid, key in self.rows.items():
            if key == keep_key:
                self.tree.selection_set(iid)
        self.summary.config(text="Report: " + reportspec.describe(
            self.spec, self.inv))

    def _click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        self.tree.selection_set(iid)
        if self.tree.identify_column(event.x) == "#1":
            self._toggle_row(iid)
            return "break"

    def _double(self, event):
        iid = self.tree.identify_row(event.y)
        if iid and self.tree.identify_column(event.x) != "#1":
            sid, cid = self.rows[iid]
            if cid is None and len(self.inv.children.get(sid, ())) > 1:
                self.open[sid] = not self.open.get(sid)
                self.populate()

    def _toggle_selected(self):
        sel = self.tree.selection()
        if sel:
            self._toggle_row(sel[0])
            return "break"

    def _toggle_row(self, iid):
        sid, cid = self.rows[iid]
        if cid is None:
            self.toggle_section(sid)
        else:
            self.toggle_child(sid, cid)

    # -- what the user can do (also called by the tests) ---------------------------
    def _set(self, spec):
        self.spec = reportspec.sanitise(spec)
        self.app.set_report_spec(self.spec)
        self.populate()

    def toggle_section(self, sid):
        if not self.inv.present.get(sid, False):
            return False           # nothing to put in: it stays off
        self._set(reportspec.with_on(self.spec, sid,
                                     not reportspec.is_on(self.spec, sid)))
        return True

    def toggle_child(self, sid, cid):
        on = cid in reportspec.skipped(self.spec, sid)
        self._set(reportspec.with_child(self.spec, sid, cid, on))

    def selected_section(self):
        sel = self.tree.selection()
        if sel and self.rows.get(sel[0], (None, 1))[1] is None:
            return self.rows[sel[0]][0]
        return None

    def move_selected(self, delta):
        sid = self.selected_section()
        if sid:
            self.move(sid, delta)

    def move(self, sid, delta):
        self._set(reportspec.moved(self.spec, sid, delta))
        for iid, key in self.rows.items():
            if key == (sid, None):
                self.tree.selection_set(iid)
                self.tree.see(iid)

    def select_all(self, on):
        spec = reportspec.with_all(self.spec, False)
        if on:
            for sid in reportspec.SECTION_IDS:
                if self.inv.present.get(sid, False):
                    spec = reportspec.with_on(spec, sid, True)
        self._set(spec)

    def set_option(self, key, value):
        self._set(reportspec.with_option(self.spec, key, value))

    # -- presets ----------------------------------------------------------------------
    def _refresh_presets(self):
        names = list(reportspec.all_presets(self.app.report_presets))
        self.preset_box.config(values=names)

    def apply_preset(self, name):
        presets = reportspec.all_presets(self.app.report_presets)
        if name in presets:
            self.sha.set(reportspec.option(presets[name], "sha"))
            self.dividers.set(reportspec.option(presets[name], "dividers"))
            # a preset says what goes in; the look of the cover stays yours
            self._set(reportspec.with_cover_of(presets[name], self.spec))

    def save_preset(self, name):
        """Store the current choice under ``name``; False when the name is
        empty or belongs to a built-in preset."""
        name = (name or "").strip()[:reportspec.MAX_PRESET_NAME]
        if not name or name in reportspec.BUILTIN_PRESETS:
            return False
        presets = dict(self.app.report_presets)
        presets[name] = reportspec.copy_spec(self.spec)
        self.app.set_report_presets(presets)
        self._refresh_presets()
        self.preset.set(name)
        return True

    def delete_preset(self, name):
        presets = dict(self.app.report_presets)
        if name not in presets:
            return False
        del presets[name]
        self.app.set_report_presets(presets)
        self._refresh_presets()
        self.preset.set("")
        return True

    def _ask_save_preset(self):
        name = simpledialog.askstring("Save preset", "Name of this preset:",
                                      parent=self)
        if name is None:
            return
        if not self.save_preset(name):
            messagebox.showinfo(
                "Save preset", "Choose a name that is not empty and not one "
                "of the built-in presets.", parent=self)

    def _delete_preset(self):
        name = self.preset.get()
        if name in reportspec.BUILTIN_PRESETS:
            messagebox.showinfo("Delete preset",
                                "The built-in presets cannot be deleted.",
                                parent=self)
        elif name:
            self.delete_preset(name)

    # -- cover / output ---------------------------------------------------------------
    def refresh_cover(self):
        d = self.app.details
        who = "  ·  ".join(x for x in (d.get("customer"), d.get("reference"),
                                       d.get("date")) if x)
        logo = os.path.basename(self.app.logo) if self.app.logo else "none"
        self.cover_text.config(
            text=f"{d.get('title') or 'Untitled report'}\n"
                 f"{who or 'no customer, reference or date yet'}\n"
                 f"Letterhead: {logo}")

    def _edit_details(self):
        self.app.edit_details()
        self.after(400, self.refresh_cover)

    def preview(self):
        self.app.preview_report()

    def generate(self):
        self.app.generate_report(self.output.get())

    def close(self):
        self.app.report_dlg = None
        self.destroy()
