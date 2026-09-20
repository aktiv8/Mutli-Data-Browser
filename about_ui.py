"""The About box: a small version of the supplied picture, the name and
version, a link to the project page, the libraries in use and the font credit,
with a button that copies the version report for bug reports."""

from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import ttk

import appinfo

PICTURE_SIDE = 220          # px: the longest side of the picture shown


def small_picture(master, max_side=PICTURE_SIDE):
    """The About picture as a Tk image (``appinfo.image_path("about")``, else
    the splash picture) shrunk to ``max_side``, or None when there is no
    picture or it cannot be read."""
    path = appinfo.image_path("about")
    if not path:
        return None
    try:
        from PIL import Image, ImageTk
        im = Image.open(path).convert("RGBA")
        im.thumbnail((max_side, max_side), Image.LANCZOS)
        return ImageTk.PhotoImage(im, master=master)
    except Exception:
        pass
    try:
        img = tk.PhotoImage(file=path, master=master)
        k = max(1, -(-max(img.width(), img.height()) // max_side))
        return img.subsample(k) if k > 1 else img
    except Exception:
        return None


def open_link(url=None):
    """Open the project page in the browser. True when it was handed over."""
    try:
        return bool(webbrowser.open(url or appinfo.GITHUB_URL))
    except Exception:
        return False


class AboutDialog(tk.Toplevel):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        pal = app.palette
        self.title(f"About {appinfo.NAME}")
        self.transient(master)
        self.resizable(False, False)
        self.configure(bg=pal["bg"])
        body = ttk.Frame(self, padding=(24, 20, 24, 16))
        body.pack(fill="both", expand=True)

        self.picture = small_picture(self)
        if self.picture is not None:
            ttk.Label(body, image=self.picture).pack(pady=(0, 12))
        ttk.Label(body, text=appinfo.NAME, style="Section.TLabel",
                  font=(app.font_family, 15, "bold")).pack()
        ttk.Label(body, text=f"Version {appinfo.VERSION}",
                  style="Muted.TLabel").pack(pady=(2, 8))
        ttk.Label(body, text=appinfo.DESCRIPTION, wraplength=340,
                  justify="center").pack()

        self.link = tk.Label(body, text=appinfo.GITHUB_URL, cursor="hand2",
                             fg=pal["accent"], bg=pal["bg"], takefocus=1,
                             font=(app.font_family, 10, "underline"))
        self.link.pack(pady=(12, 12))
        self.link.bind("<Button-1>", lambda e: open_link())
        self.link.bind("<Return>", lambda e: open_link())
        self.link.bind("<space>", lambda e: open_link())

        libs = "   ".join(f"{name} {ver}" if ver else f"{name} –"
                         for name, ver in appinfo.library_versions())
        ttk.Label(body, text=libs, style="Muted.TLabel", wraplength=340,
                  justify="center").pack()
        ttk.Label(body, text=appinfo.FONT_CREDIT, style="Muted.TLabel",
                  wraplength=340, justify="center").pack(pady=(6, 0))

        row = ttk.Frame(body)
        row.pack(pady=(16, 0))
        self.copy_btn = ttk.Button(row, text="Copy version info",
                                   command=self.copy_info)
        self.copy_btn.pack(side="left", padx=(0, 8))
        ttk.Button(row, text="Close", command=self.destroy).pack(side="left")
        self.bind("<Escape>", lambda e: self.destroy())

        app.themes.recolor_tk(self)
        self.link.configure(fg=pal["accent"], bg=pal["bg"])
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = master.winfo_rootx() + max(0, (master.winfo_width() - w) // 2)
        y = master.winfo_rooty() + max(0, (master.winfo_height() - h) // 3)
        self.geometry(f"+{x}+{y}")
        self.copy_btn.focus_set()

    def copy_info(self):
        self.clipboard_clear()
        self.clipboard_append(appinfo.version_report())
        self.copy_btn.configure(text="Copied")
