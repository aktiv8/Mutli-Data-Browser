"""In-app PDF preview (PyMuPDF renders pages into a Tk canvas).

``PdfPreview`` is a self-contained frame: give it a PDF path with
:meth:`show`. What you see is exactly the file that *Save as…* copies, so a
preview never differs from the saved result. When PyMuPDF is not installed,
``HAVE_PDF`` is False and the caller should fall back to
:func:`open_external`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:                                    # new name first, then the legacy one
    import pymupdf as _mu
except Exception:                       # pragma: no cover - optional dependency
    try:
        import fitz as _mu
    except Exception:
        _mu = None

HAVE_PDF = _mu is not None
ZOOMS = ["Fit width", "Fit page", "50%", "75%", "100%", "150%", "200%"]


def open_external(path: str):
    """Open a file with the system's default application."""
    if sys.platform.startswith("win"):
        os.startfile(path)                          # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class PdfPreview(ttk.Frame):
    """Page viewer with navigation, zoom, save and open-in-viewer."""

    def __init__(self, master, on_close=None):
        super().__init__(master)
        self.on_close = on_close
        self.doc = None
        self.path = None
        self.save_name = "output.pdf"
        self.page = 0
        self._photo = None
        self._job = None

        bar = ttk.Frame(self)
        bar.pack(side="top", fill="x", padx=10, pady=(8, 2))
        self.title_lbl = ttk.Label(bar, text="PDF preview",
                                   style="Section.TLabel")
        self.title_lbl.pack(side="left", padx=(0, 12))
        self.prev_btn = ttk.Button(bar, text="◀", width=3, command=self.prev,
                                   style="Tool.TButton")
        self.prev_btn.pack(side="left")
        self.page_lbl = ttk.Label(bar, text="", width=11, anchor="center")
        self.page_lbl.pack(side="left")
        self.next_btn = ttk.Button(bar, text="▶", width=3, command=self.next,
                                   style="Tool.TButton")
        self.next_btn.pack(side="left")
        ttk.Button(bar, text="Close", style="Tool.TButton",
                   command=self._close).pack(side="right")
        ttk.Button(bar, text="Open in viewer", style="Tool.TButton",
                   command=self.open_viewer).pack(side="right")
        ttk.Button(bar, text="Save as…", style="Tool.TButton",
                   command=self.save_as).pack(side="right")

        # second row: zoom, then the caller's options (panels per page, …)
        row = ttk.Frame(self)
        row.pack(side="top", fill="x", padx=10, pady=(0, 6))
        ttk.Label(row, text="Zoom").pack(side="left")
        self.zoom_var = tk.StringVar(value="Fit page")
        zb = ttk.Combobox(row, textvariable=self.zoom_var, width=9,
                          state="readonly", values=ZOOMS)
        zb.pack(side="left", padx=(6, 16))
        zb.bind("<<ComboboxSelected>>", lambda e: self._schedule())
        self.options = ttk.Frame(row)
        self.options.pack(side="left", fill="x")

        body = ttk.Frame(self)
        body.pack(side="top", fill="both", expand=True)
        self.canvas = tk.Canvas(body, highlightthickness=0)
        vs = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        hs = ttk.Scrollbar(body, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        vs.pack(side="right", fill="y")
        hs.pack(side="bottom", fill="x")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._schedule())
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", lambda e: self._wheel(e, 120))
        self.canvas.bind("<Button-5>", lambda e: self._wheel(e, -120))
        self.canvas.bind("<Enter>", lambda e: self.canvas.focus_set())
        self.canvas.bind("<Prior>", lambda e: self.prev())
        self.canvas.bind("<Next>", lambda e: self.next())
        self.canvas.bind("<Home>", lambda e: self.goto(0))
        self.canvas.bind("<End>", lambda e: self.goto(10 ** 9))

    # -- public --------------------------------------------------------------
    @property
    def n_pages(self) -> int:
        return len(self.doc) if self.doc is not None else 0

    def clear_options(self):
        for w in self.options.winfo_children():
            w.destroy()

    def show(self, path: str, title: str = "PDF preview",
             save_name: str = "output.pdf", keep_page: bool = False):
        """Load (or reload) a PDF file into the viewer."""
        if not HAVE_PDF:
            raise RuntimeError("PyMuPDF is not installed")
        keep = self.page if keep_page else 0
        if self.doc is not None:
            self.doc.close()
        self.doc = _mu.open(path)
        self.path = path
        self.save_name = save_name
        self.title_lbl.config(text=title)
        self.page = max(0, min(keep, self.n_pages - 1))
        self._render()

    def close_document(self):
        if self.doc is not None:
            self.doc.close()
            self.doc = None
        self._photo = None
        self.canvas.delete("all")

    # -- navigation ------------------------------------------------------------
    def goto(self, n):
        n = max(0, min(n, self.n_pages - 1))
        if n != self.page:
            self.page = n
            self._render()

    def prev(self):
        self.goto(self.page - 1)

    def next(self):
        self.goto(self.page + 1)

    def _wheel(self, event, delta=None):
        d = delta if delta is not None else event.delta
        self.canvas.yview_scroll(-1 if d > 0 else 1, "units")
        return "break"

    # -- rendering ---------------------------------------------------------------
    def _schedule(self):
        if self._job is not None:
            self.after_cancel(self._job)
        self._job = self.after(60, self._render)

    def refresh(self):
        """Re-render immediately (e.g. right after the frame is shown)."""
        if self._job is not None:
            self.after_cancel(self._job)
        self._render()

    def _zoom_factor(self, page):
        w = max(200, self.canvas.winfo_width() - 24)
        h = max(200, self.canvas.winfo_height() - 24)
        rect = page.rect
        mode = self.zoom_var.get()
        if mode == "Fit width":
            return w / rect.width
        if mode == "Fit page":
            return min(w / rect.width, h / rect.height)
        try:
            return int(mode.rstrip("%")) / 100.0 * 96.0 / 72.0
        except ValueError:
            return 1.0

    def _render(self):
        self._job = None
        if self.doc is None or self.n_pages == 0:
            self.page_lbl.config(text="")
            return
        page = self.doc[self.page]
        z = self._zoom_factor(page)
        pix = page.get_pixmap(matrix=_mu.Matrix(z, z), alpha=False)
        self._photo = tk.PhotoImage(data=pix.tobytes("ppm"))
        self.canvas.delete("all")
        pad = 12
        x = max(pad, (self.canvas.winfo_width() - pix.width) // 2)
        self.canvas.create_rectangle(x + 3, pad + 3, x + pix.width + 3,
                                     pad + pix.height + 3, fill="#8a8a8a",
                                     outline="")
        self.canvas.create_image(x, pad, anchor="nw", image=self._photo)
        self.canvas.configure(scrollregion=(0, 0, x + pix.width + pad,
                                            pad + pix.height + pad))
        self.canvas.yview_moveto(0)
        self.page_lbl.config(text=f"Page {self.page + 1} / {self.n_pages}")
        self.prev_btn.config(state="normal" if self.page > 0 else "disabled")
        self.next_btn.config(
            state="normal" if self.page < self.n_pages - 1 else "disabled")

    # -- actions ---------------------------------------------------------------
    def save_as(self):
        if not self.path:
            return
        dest = filedialog.asksaveasfilename(
            defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
            initialfile=self.save_name)
        if not dest:
            return
        try:
            shutil.copyfile(self.path, dest)
        except OSError as exc:
            messagebox.showerror("Save failed", str(exc))
            return
        messagebox.showinfo("Saved", f"PDF saved to\n{dest}")

    def open_viewer(self):
        if self.path:
            try:
                open_external(self.path)
            except Exception as exc:
                messagebox.showerror("Could not open", str(exc))

    def _close(self):
        if self.on_close:
            self.on_close()
