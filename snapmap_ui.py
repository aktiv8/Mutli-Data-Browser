"""The *SnapMap* viewer: where on the sample a peak comes from.

A SnapMap has a whole spectrum at every pixel (see ``snapmap``). Left: the map,
the counts summed over an energy window; right: the spectrum. Drag across the
spectrum to choose the window (the map redraws), drag a box on the map (or click
one pixel) to see the spectrum of just that area next to the whole map's.
Switch element without losing the box, lay the map over the camera image taken at
the same spot, and save the picture, the map values or the area's spectrum.

The dialog talks to the app through ``app.docs``, ``app.palette``, ``app.cfg``,
``app._photo_image`` and ``app.status``. Not modal.
"""

from __future__ import annotations

import csv
import os
import tkinter as tk
from tkinter import filedialog, ttk

import smoothing
import snapmap
import snapshot
import themes
from workbook_ui import _finish


class SnapMapDialog(tk.Toplevel):
    def __init__(self, master, app, parser, region):
        super().__init__(master)
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.figure import Figure
        self.app, self.parser = app, parser
        self.entries = [r for r in parser.regions
                        if r.extra.get("cube") is not None
                        and r.sample == region.sample] or [region]
        self.region = region
        self.cube = region.extra["cube"]
        self.mask = None                     # boolean (ny, nx), None = whole map
        self.window = snapmap.default_window(self.cube)
        cfg = app.cfg.get("snapmap", {})
        self.scale = tk.StringVar(value=cfg.get("scale", "Viridis")
                                  if cfg.get("scale") in themes.SCALE_NAMES
                                  else "Viridis")
        self.background = tk.BooleanVar(value=bool(cfg.get("background", False)))
        self.overlay = tk.BooleanVar(value=False)
        self.alpha = tk.DoubleVar(value=float(cfg.get("alpha", 0.65)))
        self.smooth_method = tk.StringVar(
            value=cfg.get("smooth_method", "None")
            if cfg.get("smooth_method") in smoothing.METHODS else "None")
        self.smooth_strength = tk.DoubleVar(
            value=float(cfg.get("smooth_strength", 0.5)))
        self.title(f"SnapMap — {region.sample}")

        body = ttk.Frame(self, padding=8)
        body.pack(fill="both", expand=True)
        bar = ttk.Frame(body)
        bar.pack(fill="x")
        ttk.Label(bar, text="Element").pack(side="left")
        self.el_cb = ttk.Combobox(bar, state="readonly", width=14,
                                  values=[self._label(r) for r in self.entries])
        self.el_cb.current(self.entries.index(region)
                           if region in self.entries else 0)
        self.el_cb.pack(side="left", padx=(4, 12))
        self.el_cb.bind("<<ComboboxSelected>>", lambda e: self._element())
        ttk.Label(bar, text="Colours").pack(side="left")
        cb = ttk.Combobox(bar, state="readonly", width=12,
                          textvariable=self.scale, values=themes.SCALE_NAMES)
        cb.pack(side="left", padx=(4, 12))
        cb.bind("<<ComboboxSelected>>", lambda e: self._settings_changed())
        ttk.Checkbutton(bar, text="Remove background", variable=self.background,
                        command=self._settings_changed).pack(side="left")
        self.photo = self._camera_image()
        self.overlay_cb = ttk.Checkbutton(
            bar, text="On camera image", variable=self.overlay,
            command=self._rebuild,
            state="normal" if self.photo is not None else "disabled")
        self.overlay_cb.pack(side="left", padx=(12, 0))
        ttk.Scale(bar, from_=0.15, to=1.0, variable=self.alpha, length=70,
                  command=lambda v: self._settings_changed(quiet=True)).pack(
            side="left", padx=(6, 0))

        bar2 = ttk.Frame(body)
        bar2.pack(fill="x", pady=(4, 0))
        ttk.Label(bar2, text="Smoothing").pack(side="left")
        smooth_cb = ttk.Combobox(bar2, state="readonly", width=19,
                                 textvariable=self.smooth_method,
                                 values=smoothing.METHODS)
        smooth_cb.pack(side="left", padx=(4, 12))
        smooth_cb.bind("<<ComboboxSelected>>", lambda e: self._smoothing_changed())
        ttk.Label(bar2, text="Strength").pack(side="left")
        ttk.Scale(bar2, from_=0.0, to=1.0, variable=self.smooth_strength,
                  length=110, command=self._smoothing_changed).pack(
            side="left", padx=(4, 0))

        self.fig = Figure(figsize=(10.4, 4.9), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=body)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, pady=(6, 4))
        row = ttk.Frame(body)
        row.pack(fill="x")
        self.hint = ttk.Label(row, style="Muted.TLabel", text="", anchor="w")
        self.hint.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Whole map", command=self._whole_map).pack(
            side="right")
        ttk.Button(row, text="Save…", command=self._save_menu).pack(
            side="right", padx=6)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda e: self.destroy())
        _finish(self, app, 1080, 640)
        self._rebuild()

    # -- what is on show -------------------------------------------------------------
    @staticmethod
    def _label(r):
        return r.name

    def _camera_image(self):
        c = self.cube
        if c.stage_x_mm is None:
            return None
        images = [b for p in self.app.docs for b in p.images]
        return snapshot.nearest_image(images, c.stage_x_mm, c.stage_y_mm)

    def _cmap(self):
        return themes.scale_colourmap(self.scale.get(), False, self.app.palette)

    def _image(self):
        lo, hi = self.window
        return self.cube.image(lo, hi, background=self.background.get())

    def _save_cfg(self):
        self.app.cfg["snapmap"] = {
            "scale": self.scale.get(),
            "background": self.background.get(),
            "alpha": round(self.alpha.get(), 2),
            "smooth_method": self.smooth_method.get(),
            "smooth_strength": round(self.smooth_strength.get(), 2),
        }

    def _settings_changed(self, quiet=False):
        self._save_cfg()
        if quiet and self.overlay.get() is False:
            return
        self._update_map()

    def _smoothing_changed(self, *_args):
        self._save_cfg()
        self._update_spectrum()

    def _label_with_smoothing(self, base, extra=None):
        """``base`` (+ ``extra`` in parentheses) with the active smoothing
        method appended, so a smoothed trace is never shown unlabelled."""
        method = self.smooth_method.get()
        if method == "None":
            return base if extra is None else f"{base} ({extra})"
        if extra is None:
            return f"{base} ({method})"
        return f"{base} ({extra}, {method})"

    def _element(self):
        self.region = self.entries[self.el_cb.current()]
        self.cube = self.region.extra["cube"]
        self.window = snapmap.default_window(self.cube)
        self.photo = self._camera_image()
        self.overlay_cb.configure(
            state="normal" if self.photo is not None else "disabled")
        if self.photo is None:
            self.overlay.set(False)
        if self.mask is not None and self.mask.shape != (self.cube.ny,
                                                          self.cube.nx):
            self.mask = None
        self._rebuild()

    # -- drawing ---------------------------------------------------------------------
    def _rebuild(self):
        """Draw everything from scratch (element, overlay or ROI changed)."""
        from matplotlib.widgets import RectangleSelector, SpanSelector
        pal = self.app.palette
        fig = self.fig
        fig.clf()
        fig.set_facecolor(pal["plot_bg"])
        gs = fig.add_gridspec(1, 2, width_ratios=[1.0, 1.15], wspace=0.28,
                              left=0.07, right=0.98, top=0.93, bottom=0.13)
        self.ax_map = fig.add_subplot(gs[0])
        self.ax_spec = fig.add_subplot(gs[1])
        for ax in (self.ax_map, self.ax_spec):
            ax.set_facecolor(pal["plot_bg"])
            ax.tick_params(colors=pal["muted"], labelsize=8)
            for sp in ax.spines.values():
                sp.set_color(pal["muted"])
        cube = self.cube
        # the photo under the map, in the map's own micrometres
        left, right, bottom, top = cube.extent()
        if self.overlay.get() and self.photo is not None:
            img = self.app._photo_image(self.parser, self.photo)
            if img is not None:
                cal = self.photo.calib
                cx, cy = snapshot.stage_to_pixel(cal, cube.stage_x_mm,
                                                 cube.stage_y_mm)
                ux, uy = cal["um_per_px_x"], cal["um_per_px_y"]
                w, h = img.size
                self.ax_map.imshow(img, extent=[-cx * ux, (w - cx) * ux,
                                                (h - cy) * uy, -cy * uy],
                                   zorder=0)
                padx, pady = (right - left) * 0.3, (bottom - top) * 0.3
                self.ax_map.set_xlim(left - padx, right + padx)
                self.ax_map.set_ylim(bottom + pady, top - pady)
        image = self._image()
        vmin, vmax = snapmap.colour_range(image)
        self.im = self.ax_map.imshow(
            image, extent=cube.extent(), origin="upper", cmap=self._cmap(),
            interpolation="nearest", vmin=vmin, vmax=vmax, zorder=1,
            alpha=self.alpha.get() if self.overlay.get() else 1.0)
        if not self.overlay.get():
            self.ax_map.set_xlim(left, right)
            self.ax_map.set_ylim(bottom, top)
        self.ax_map.set_xlabel("X (µm)", color=pal["plot_fg"], fontsize=9)
        self.ax_map.set_ylabel("Y (µm)", color=pal["plot_fg"], fontsize=9)
        self.map_title = self.ax_map.set_title("", fontsize=9,
                                               color=pal["plot_fg"])
        self.cbar = fig.colorbar(self.im, ax=self.ax_map, fraction=0.046,
                                 pad=0.02)
        self.cbar.ax.tick_params(colors=pal["muted"], labelsize=8)
        self._draw_roi_outline()
        self._draw_spectrum()
        self._update_titles()

        self.rect = RectangleSelector(
            self.ax_map, self._on_roi, useblit=False, button=[1],
            minspanx=0, minspany=0, spancoords="data", interactive=True,
            props=dict(edgecolor=pal["accent"], facecolor="none", linewidth=1.6))
        self.span = SpanSelector(
            self.ax_spec, self._on_window, "horizontal", useblit=False,
            interactive=True, props=dict(facecolor=pal["accent"], alpha=0.22))
        self.span.extents = self.window
        self.cid = self.canvas.mpl_connect("motion_notify_event", self._hover)
        self.hint.configure(
            text="Drag across the spectrum to choose the energy window; drag a "
                 "box (or click a pixel) on the map for that area's spectrum.")
        self.canvas.draw_idle()

    def _draw_roi_outline(self):
        """The chosen area's bounding box on the map (the selector's own box
        is gone after a redraw)."""
        if self.mask is None or not self.mask.any():
            return
        import numpy as np
        from matplotlib.patches import Rectangle
        rows, cols = np.flatnonzero(self.mask.any(axis=1)), np.flatnonzero(
            self.mask.any(axis=0))
        c = self.cube
        x0, x1 = c.x_of(cols[0]) - c.dx / 2, c.x_of(cols[-1]) + c.dx / 2
        y0, y1 = c.y_of(rows[0]) - c.dy / 2, c.y_of(rows[-1]) + c.dy / 2
        self.ax_map.add_patch(Rectangle(
            (x0, y0), x1 - x0, y1 - y0, fill=False, lw=1.6, ls="--",
            ec=self.app.palette["accent"], zorder=5))

    def _mean_spectra(self):
        """The whole-map and (if any) ROI spectra, smoothed for display when
        a smoothing method is chosen. Never touches ``cube.data`` itself."""
        cube = self.cube
        n_all = cube.nx * cube.ny
        whole = [v / n_all for v in cube.total()]
        roi = None
        if self.mask is not None and self.mask.any():
            n = int(self.mask.sum())
            roi = [v / n for v in cube.roi_spectrum(self.mask)]
        method = self.smooth_method.get()
        if method != "None":
            strength = self.smooth_strength.get()
            whole = smoothing.smooth(whole, method, strength).tolist()
            if roi is not None:
                roi = smoothing.smooth(roi, method, strength).tolist()
        return whole, roi

    def _draw_spectrum(self):
        pal = self.app.palette
        ax = self.ax_spec
        ax.clear()
        ax.set_facecolor(pal["plot_bg"])
        ax.tick_params(colors=pal["muted"], labelsize=8)
        whole, roi = self._mean_spectra()
        e = self.cube.energy
        ax.plot(e, whole, color=pal["muted"] if roi else pal["accent"], lw=1.4,
                label=self._label_with_smoothing("whole map"))
        if roi:
            ax.plot(e, roi, color=pal["accent"], lw=1.6,
                    label=self._label_with_smoothing(
                        "area", f"{int(self.mask.sum())} px"))
            ax.legend(fontsize=8, frameon=False, labelcolor=pal["plot_fg"])
        r = self.region
        binding = "inding" in (r.energy_label or "")
        ax.set_xlim((max(e), min(e)) if binding else (min(e), max(e)))
        ax.set_xlabel(f"{r.energy_label} ({r.energy_units})", color=pal["plot_fg"],
                      fontsize=9)
        ax.set_ylabel("Counts per pixel", color=pal["plot_fg"], fontsize=9)
        ax.set_title(f"{r.name}", fontsize=9, color=pal["plot_fg"])
        for sp in ax.spines.values():
            sp.set_color(pal["muted"])
        # the window, shown even while nothing is being dragged
        lo, hi = self.window
        self.win_patch = ax.axvspan(lo, hi, color=pal["accent"], alpha=0.14,
                                    lw=0)

    def _update_titles(self):
        lo, hi = self.window
        self.map_title.set_text(
            f"{self.region.name}   {min(lo, hi):.1f}–{max(lo, hi):.1f} "
            f"{self.region.energy_units}")

    def _update_map(self):
        """The window, background or colours changed: redraw just the map."""
        image = self._image()
        vmin, vmax = snapmap.colour_range(image)
        self.im.set_data(image)
        self.im.set_clim(vmin, vmax)
        self.im.set_cmap(self._cmap())
        self.im.set_alpha(self.alpha.get() if self.overlay.get() else 1.0)
        self._update_titles()
        try:
            self.win_patch.remove()
        except (ValueError, AttributeError):
            pass
        lo, hi = self.window
        self.win_patch = self.ax_spec.axvspan(
            lo, hi, color=self.app.palette["accent"], alpha=0.14, lw=0)
        self.canvas.draw_idle()

    def _update_spectrum(self):
        """Smoothing changed: redraw just the spectrum panel (as ``_on_roi``
        already does for a new ROI), leaving the map untouched."""
        self._draw_spectrum()
        self.span.extents = self.window
        self.canvas.draw_idle()

    # -- interaction -------------------------------------------------------------------
    def _on_window(self, lo, hi):
        if abs(hi - lo) < 1e-9:
            return
        self.window = (min(lo, hi), max(lo, hi))
        self._update_map()

    def _on_roi(self, click, release):
        cube = self.cube
        if None in (click.xdata, click.ydata, release.xdata, release.ydata):
            return
        x0, y0, x1, y1 = click.xdata, click.ydata, release.xdata, release.ydata
        if abs(x1 - x0) < abs(cube.dx) / 2 and abs(y1 - y0) < abs(cube.dy) / 2:
            hit = cube.pixel_at(x0, y0)              # a click: one pixel
            if hit is None:
                return
            mask = self._blank_mask()
            mask[hit[1], hit[0]] = True
        else:
            mask = cube.rect_mask(x0, y0, x1, y1)
        if not mask.any():
            return
        self.mask = mask
        self._draw_spectrum()
        self.span.extents = self.window
        self.canvas.draw_idle()

    def _blank_mask(self):
        import numpy as np
        return np.zeros((self.cube.ny, self.cube.nx), dtype=bool)

    def _whole_map(self):
        self.mask = None
        self._rebuild()

    def _hover(self, event):
        cube = self.cube
        if event.inaxes is self.ax_map and event.xdata is not None:
            hit = cube.pixel_at(event.xdata, event.ydata)
            if hit:
                v = self.im.get_array()[hit[1], hit[0]]
                self.hint.configure(
                    text=f"x {event.xdata:.0f} µm   y {event.ydata:.0f} "
                         f"µm    pixel ({hit[0]}, {hit[1]})    value "
                         f"{v:,.1f}")
        elif event.inaxes is self.ax_spec and event.xdata is not None:
            self.hint.configure(text=f"{event.xdata:.2f} "
                                     f"{self.region.energy_units}")

    # -- saving ------------------------------------------------------------------------
    def _save_menu(self):
        m = tk.Menu(self, tearoff=0)
        self.app.themes.register_menu(m)
        m.add_command(label="Picture (PNG)…", command=self._save_png)
        m.add_command(label="Map values (CSV)…", command=self._save_map)
        m.add_command(label="Spectra (CSV)…", command=self._save_spectra)
        w = self.winfo_pointerxy()
        try:
            m.tk_popup(*w)
        finally:
            m.grab_release()

    def _stem(self):
        return f"{self.region.sample} {self.region.name}".replace(" ", "_")

    def _ask(self, ext, kind):
        return filedialog.asksaveasfilename(
            parent=self, defaultextension=ext, initialfile=self._stem() + ext,
            filetypes=[(kind, "*" + ext)])

    def _save_png(self):
        path = self._ask(".png", "PNG image")
        if path:
            self.fig.savefig(path, dpi=200, facecolor=self.fig.get_facecolor())
            self.app.status.config(text=f"Saved {os.path.basename(path)}")

    def _save_map(self):
        path = self._ask(".csv", "CSV")
        if not path:
            return
        with open(path, "w", encoding="utf-8", newline="") as fh:
            lo, hi = self.window
            fh.write(f"# {self.region.sample} {self.region.name}: counts summed "
                     f"over {min(lo, hi):.3f}-{max(lo, hi):.3f} "
                     f"{self.region.energy_units}"
                     f"{', background removed' if self.background.get() else ''}"
                     "\n")
            fh.write(snapmap.to_csv_grid(self.cube, self._image()))
        self.app.status.config(text=f"Saved {os.path.basename(path)}")

    def _csv_smooth_suffix(self):
        """Appended to a CSV column header so a smoothed export never looks
        like raw data."""
        method = self.smooth_method.get()
        return f", {method}" if method != "None" else ""

    def _save_spectra(self):
        path = self._ask(".csv", "CSV")
        if not path:
            return
        whole, roi = self._mean_spectra()
        suffix = self._csv_smooth_suffix()
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            head = [f"{self.region.energy_label} ({self.region.energy_units})",
                    f"Whole map (counts per pixel{suffix})"]
            if roi:
                head.append(
                    f"Area, {int(self.mask.sum())} px (counts per pixel{suffix})")
            w.writerow(head)
            for i, e in enumerate(self.cube.energy):
                w.writerow([f"{e:.4f}", f"{whole[i]:.6g}"]
                           + ([f"{roi[i]:.6g}"] if roi else []))
        self.app.status.config(text=f"Saved {os.path.basename(path)}")
