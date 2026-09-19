"""Drawing of spectra: the pure matplotlib functions behind the stack, heat
map and 3-D waterfall panels (no Tk). ``escape_explorer`` re-exports them."""

from __future__ import annotations

import math
import os
import re

import themes
import viewdata


def interp_intensity(region, energy):
    """Linear interpolation of a region's intensity at a given energy.
    Works for ascending or descending energy axes; clamps at the ends."""
    xs, ys = region.energy, region.counts
    if not xs or not ys:
        return None
    pts = sorted(zip(xs, ys))
    xs2 = [p[0] for p in pts]
    ys2 = [p[1] for p in pts]
    if energy <= xs2[0]:
        return ys2[0]
    if energy >= xs2[-1]:
        return ys2[-1]
    import bisect
    i = bisect.bisect_left(xs2, energy)
    x0, x1 = xs2[i - 1], xs2[i]
    y0, y1 = ys2[i - 1], ys2[i]
    f = (energy - x0) / (x1 - x0) if x1 != x0 else 0.0
    return y0 + f * (y1 - y0)


def trace_label(r, multi_file=False, show_name=True):
    """Short end-of-trace label. Depth profiles: the level (and etch time);
    otherwise the sample, plus the region name only where a panel mixes
    regions. Unnamed samples fall back to the file stem (several files) or the
    region name. Colour already tells files apart, so no file prefix."""
    if r.etch_level is not None:
        base = (f"L{r.etch_level} ({r.etch_time:g} s)"
                if r.etch_time is not None else f"L{r.etch_level}")
    else:
        parts = [r.sample] if r.sample else []
        if show_name and parts:
            parts.append(r.name)
        if not parts:
            parts = [os.path.splitext(r.source)[0]
                     if (multi_file and r.source) else r.name]
        base = " ".join(parts)
    return base if len(base) <= 24 else base[:22] + "…"


def nice_step(x):
    """Round a positive number down to 1, 2 or 5 x 10^n."""
    if not x or x <= 0 or not math.isfinite(x):
        return 1.0
    e = math.floor(math.log10(x))
    m = x / 10 ** e
    for k in (5, 2, 1):
        if m >= k:
            return k * 10 ** e
    return 10 ** e


def dodge(values, gap):
    """Nudge label positions upward so neighbours are at least ``gap`` apart
    (order preserved). Returns the new positions."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = list(values)
    for a, b in zip(order, order[1:]):
        if out[b] - out[a] < gap:
            out[b] = out[a] + gap
    return out


def normalise_name(name):
    """Case/whitespace-insensitive key for a region (element) name."""
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


def norm_factor(r, mode, cursor=None):
    """Divisor that normalises spectrum r for the chosen mode."""
    ys = r.counts
    if mode == "Max = 1":
        m = max(ys)
        return m if m else 1.0
    if mode == "Area = 1":
        s = sum(abs(y) for y in ys)
        return s / len(ys) if s else 1.0
    if mode == "At cursor" and cursor is not None:
        v = interp_intensity(r, cursor)
        return v if v and v > 0 else 1.0
    return 1.0


def add_ke_axis(ax, hv, muted, label=True):
    """Mirror a binding-energy axis along the top as kinetic energy
    (KE = hν − BE)."""
    def flip(x):
        return hv - x
    sec = ax.secondary_xaxis("top", functions=(flip, flip))
    sec.spines["top"].set_visible(True)
    sec.spines["top"].set_color(muted)
    sec.tick_params(labelsize=8)
    if label:
        sec.set_xlabel("Kinetic Energy (eV)", fontsize=8, color=muted)
    return sec


def draw_stack(ax, regs, offset=0.6, norm="None", cursor=None, colours=None,
               title="", subtitle="", selected=(), multi_file=False,
               first_col=True, bottom_row=True, accent="#0F6B8C",
               muted="#56636E", scale="Binding", ke_top=False,
               top_row=False, markers=()):
    """Draw one panel: a single spectrum plain, several stacked by y offset.

    Stacked panels drop the (meaningless) y ticks for a scale bar and label
    each trace at its right-hand end, in the trace colour, with labels nudged
    apart. ``selected`` holds ``id(region)`` of spectra to draw heavier."""
    normed = [[y / norm_factor(r, norm, cursor) for y in r.counts]
              for r in regs]
    n = len(regs)
    stacked = n > 1
    spans = [(max(v) - min(v)) for v in normed if v]
    step = offset * (max(spans) if spans else 1.0) if stacked else 0.0
    r0 = regs[0]
    axes_x = [viewdata.energy_axis(r, scale) for r in regs]
    a0 = axes_x[0]
    binding = a0.invert
    show_name = len({normalise_name(r.name) for r in regs}) > 1
    label_every = max(1, math.ceil(n / 12))
    ends = []
    for i, (r, v) in enumerate(zip(regs, normed)):
        yoff = [y + i * step for y in v]
        col = colours[i] if colours else None
        sel = id(r) in selected
        ax.plot(axes_x[i].x, yoff, color=col,
                lw=1.9 if sel else (0.8 if n > 12 else 1.1),
                zorder=3 if sel else 2)
        if stacked and i % label_every == 0:
            xs = axes_x[i].x
            j = (min if binding else max)(range(len(xs)), key=xs.__getitem__)
            lo, hi = max(0, j - 2), min(len(yoff), j + 3)
            ends.append((sum(yoff[lo:hi]) / (hi - lo),
                         trace_label(r, multi_file, show_name), col))
    if norm == "At cursor" and cursor is not None:
        cx = (r0.photon_energy - cursor
              if a0.label == "Kinetic Energy" else cursor)
        ax.axvline(cx, color=accent, ls="--", lw=0.9)
    ax.margins(x=0.02, y=0.06)
    ax.relim()
    ax.autoscale_view()
    y0, y1 = ax.get_ylim()
    yspan = (y1 - y0) or 1.0
    yaxis_tf = ax.get_yaxis_transform()          # x: axes fraction, y: data
    if stacked:
        ax.set_yticks([])
        ax.spines["left"].set_visible(False)
        # scale bar to the left of the axes replaces the y axis
        bar = nice_step(yspan * 0.22)
        base = y0 + yspan * 0.06
        ax.plot([-0.018, -0.018], [base, base + bar], transform=yaxis_tf,
                color=muted, lw=1.6, solid_capstyle="butt", clip_on=False)
        unit = "" if norm != "None" else f" {r0.count_units}"
        ax.text(-0.03, base + bar / 2,
                (f"{bar:,.0f}" if bar >= 1 else f"{bar:g}") + unit,
                transform=yaxis_tf, rotation=90, ha="right", va="center",
                fontsize=8, color=muted, clip_on=False)
        pos = dodge([e[0] for e in ends], 0.062 * yspan)
        for (_y, text, col), yy in zip(ends, pos):
            t = ax.text(1.012, yy, text, transform=yaxis_tf, color=col,
                        fontsize=8, va="center", ha="left", clip_on=False)
            t.set_in_layout(False)      # the page reserves the gutter itself
    ax.set_title(title, loc="left")
    if subtitle:
        ax.set_title(subtitle, loc="right", fontsize=8, fontweight="normal",
                     color=muted)
    if bottom_row:
        ax.set_xlabel(f"{a0.label.capitalize()} ({a0.units})")
    if first_col and not stacked:
        ax.set_ylabel(f"{r0.count_label} ({r0.count_units})" if norm == "None"
                      else f"{r0.count_label} (normalised)")
    if markers:                        # element labels: (binding energy, text)
        lo, hi = ax.get_xlim()
        xtf = ax.get_xaxis_transform()       # x in data, y as axes fraction
        hv = r0.photon_energy
        for be, text in markers:
            x = be if binding else (hv - be if hv else None)
            if x is None or not lo <= x <= hi:
                continue
            ax.plot([x, x], [0, 1], transform=xtf, color=muted, lw=0.7,
                    ls=":", zorder=1, scalex=False, scaley=False)
            ax.text(x, 0.99, text, transform=xtf, rotation=90, va="top",
                    ha="center", fontsize=7, color=muted,
                    bbox=dict(fc=ax.get_facecolor(), ec="none", pad=0.6,
                              alpha=0.85))
    if binding:
        ax.invert_xaxis()
    if ke_top and binding and top_row and viewdata.photon_energy(regs):
        add_ke_axis(ax, viewdata.photon_energy(regs), muted)


def _titles(ax, title, subtitle, muted):
    ax.set_title(title, loc="left")
    if subtitle:
        ax.set_title(subtitle, loc="right", fontsize=8, fontweight="normal",
                     color=muted)


def draw_heatmap(fig, ax, regs, zi, norm="None", cmap=None, title="",
                 subtitle="", first_col=True, bottom_row=True, top_row=False,
                 muted="#56636E", scale="Binding", ke_top=False):
    """One panel as a heat map: energy across, ``zi`` (etch time / level,
    acquisition time or trace order, ascending downwards) down, intensity as
    colour. ``regs`` must already be in z order (see viewdata.z_sorted)."""
    import numpy as np
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.ticker import MaxNLocator
    axes_x = [viewdata.energy_axis(r, scale) for r in regs]
    a0, r0 = axes_x[0], regs[0]
    ys = [[y / norm_factor(r, norm) for y in r.counts] for r in regs]
    grid, rows = viewdata.build_matrix([a.x for a in axes_x], ys)
    if cmap is None:
        cmap = LinearSegmentedColormap.from_list("heat", ["#FFFFFF", "#000000"])
    cmap = cmap.with_extremes(bad=(0, 0, 0, 0))   # outside a trace's range
    mesh = ax.pcolormesh(viewdata.edges(list(grid)),
                         viewdata.edges(list(zi.values)),
                         np.ma.masked_invalid(rows), cmap=cmap,
                         shading="flat", rasterized=True)
    ax.set_xlim(grid[0], grid[-1])
    ax.set_ylim(max(viewdata.edges(list(zi.values))),
                min(viewdata.edges(list(zi.values))))     # first trace on top
    if a0.invert:
        ax.invert_xaxis()
    if len(regs) == 1:
        ax.set_yticks([zi.values[0]])
    elif zi.mode in ("Trace order", "Etch level"):
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_ylabel(zi.label)
    _titles(ax, title, subtitle, muted)
    if bottom_row:
        ax.set_xlabel(f"{a0.label.capitalize()} ({a0.units})")
    cb = fig.colorbar(mesh, ax=ax, pad=0.02, fraction=0.05, aspect=24)
    cb.outline.set_visible(False)
    cb.ax.tick_params(labelsize=7, length=2)
    cb.set_label("Normalised" if norm != "None"
                 else f"{r0.count_label} ({r0.count_units})", fontsize=8)
    if ke_top and a0.invert and top_row and viewdata.photon_energy(regs):
        add_ke_axis(ax, viewdata.photon_energy(regs), muted)
    return mesh


def draw_waterfall3d(ax, regs, zi, norm="None", colours=None, title="",
                     subtitle="", pal=None, scale="Binding"):
    """One panel as a 3-D waterfall: energy (x), trace z (y), intensity
    (vertical). ``ax`` must be a 3-D axes; ``regs`` in z order."""
    from matplotlib.collections import PolyCollection
    from matplotlib.colors import to_rgba
    pal = pal or themes.PALETTES[themes.DEFAULT]
    axes_x = [viewdata.energy_axis(r, scale) for r in regs]
    a0, r0 = axes_x[0], regs[0]
    ys = [[y / norm_factor(r, norm) for y in r.counts] for r in regs]
    floor = min(min(v) for v in ys if v)
    n = len(regs)
    for i, (a, v, z) in enumerate(zip(axes_x, ys, zi.values)):
        col = colours[i] if colours else None
        verts = [(a.x[0], floor)] + list(zip(a.x, v)) + [(a.x[-1], floor)]
        ax.add_collection3d(
            PolyCollection([verts], facecolors=[to_rgba(col or "#888", 0.10)],
                           edgecolors="none"), zs=z, zdir="y")
        ax.plot(a.x, [z] * len(a.x), v, color=col,
                lw=0.8 if n > 12 else 1.1)
    xs = [x for a in axes_x for x in a.x]
    ax.set_xlim(min(xs), max(xs))
    zlo, zhi = min(zi.values), max(zi.values)
    pad = 0.5 if zhi == zlo else 0.0
    ax.set_ylim(zlo - pad, zhi + pad)
    ax.set_zlim(floor, max(max(v) for v in ys if v))
    if a0.invert:
        ax.invert_xaxis()
    _titles(ax, title, subtitle, pal["muted"])
    ax.set_xlabel(f"{a0.label.capitalize()} ({a0.units})", labelpad=2)
    ax.set_ylabel(zi.label, labelpad=2)
    ax.text2D(0.0, 0.9, "Normalised" if norm != "None"
              else f"{r0.count_label} ({r0.count_units})",
              transform=ax.transAxes, fontsize=8, color=pal["muted"])
    ax.tick_params(labelsize=7, pad=0)
    ax.view_init(elev=24, azim=-58)
    try:                                   # fill the panel (matplotlib >= 3.3)
        ax.set_box_aspect((1.5, 1.0, 0.75), zoom=1.1)
    except Exception:
        pass
    for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        try:
            axis.set_pane_color(to_rgba(pal["plot_bg"], 0.0))
            axis.label.set_color(pal["plot_fg"])
            axis._axinfo["grid"]["color"] = to_rgba(pal["plot_grid"])
            axis._axinfo["axisline"]["color"] = to_rgba(pal["muted"])
        except Exception:
            pass
    ax.tick_params(colors=pal["muted"])
