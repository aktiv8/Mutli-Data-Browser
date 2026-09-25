"""Drawing of spectra: the pure matplotlib functions behind the stack, heat
map and 3-D waterfall panels (no Tk). ``spectradeck`` re-exports them."""

from __future__ import annotations

import math
import os
import re

import plotstyle
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


def add_ke_axis(ax, hv, muted, label=True, size=8):
    """Mirror a binding-energy axis along the top as kinetic energy
    (KE = hν − BE)."""
    def flip(x):
        return hv - x
    sec = ax.secondary_xaxis("top", functions=(flip, flip))
    sec.spines["top"].set_visible(True)
    sec.spines["top"].set_color(muted)
    sec.tick_params(labelsize=size)
    if label:
        sec.set_xlabel("Kinetic Energy (eV)", fontsize=size, color=muted)
    return sec


def draw_stack(ax, regs, offset=0.6, norm="None", cursor=None, colours=None,
               title="", subtitle="", selected=(), multi_file=False,
               first_col=True, bottom_row=True, accent="#0F6B8C",
               muted="#56636E", scale="Binding", ke_top=False,
               top_row=False, markers=(), style=None, fit=None,
               reels=None, auger_colour=None):
    """Draw one panel: a single spectrum plain, several stacked by y offset.

    Stacked panels drop the (meaningless) y ticks for a scale bar and label
    each trace at its right-hand end, in the trace colour, with labels nudged
    apart. ``selected`` holds ``id(region)`` of spectra to draw heavier.
    ``style`` is a plot style (see ``plotstyle``)."""
    st = plotstyle.resolve(style)
    small = plotstyle.note_size(st)
    end_lbl = st["labels"] == "End labels"
    boxed = st["labels"] == "Legend"
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
        lbl = trace_label(r, multi_file, show_name)
        ax.plot(axes_x[i].x, yoff, color=col, zorder=3 if sel else 2,
                label=lbl if boxed else "_nolegend_",
                **plotstyle.line_kwargs(st, n, sel))
        if st["fill_under"]:
            ax.fill_between(axes_x[i].x, i * step + min(v), yoff, color=col,
                            alpha=st["fill_alpha"], lw=0, zorder=1)
        if stacked and end_lbl and i % label_every == 0:
            xs = axes_x[i].x
            j = (min if binding else max)(range(len(xs)), key=xs.__getitem__)
            lo, hi = max(0, j - 2), min(len(yoff), j + 3)
            ends.append((sum(yoff[lo:hi]) / (hi - lo), lbl, col))
    if fit and n == 1:                 # a CasaXPS fit under a single spectrum
        draw_fit(ax, axes_x[0].x, fit, 1.0 / norm_factor(r0, norm, cursor),
                 muted, accent)
    if norm == "At cursor" and cursor is not None:
        cx = (r0.photon_energy - cursor
              if a0.label == "Kinetic Energy" else cursor)
        ax.axvline(cx, color=accent, ls="--", lw=0.9)
    if st["y_scale"] == "Log":
        ax.set_yscale("log")
    ax.margins(x=0.02, y=0.06)
    ax.relim()
    ax.autoscale_view()
    plotstyle.apply_ranges(ax, st, x=False)
    y0, y1 = ax.get_ylim()
    yspan = (y1 - y0) or 1.0
    yaxis_tf = ax.get_yaxis_transform()          # x: axes fraction, y: data
    if stacked:
        ax.set_yticks([])
        ax.spines["left"].set_visible(st["frame"] == "Box")
        # scale bar to the left of the axes replaces the y axis
        bar = nice_step(yspan * 0.22)
        base = y0 + yspan * 0.06
        ax.plot([-0.018, -0.018], [base, base + bar], transform=yaxis_tf,
                color=muted, lw=1.6, solid_capstyle="butt", clip_on=False)
        unit = plotstyle.y_unit(st, r0.count_units)
        unit = "" if norm != "None" or not unit else f" {unit}"
        ax.text(-0.03, base + bar / 2,
                (f"{bar:,.0f}" if bar >= 1 else f"{bar:g}") + unit,
                transform=yaxis_tf, rotation=90, ha="right", va="center",
                fontsize=small, color=muted, clip_on=False)
        pos = dodge([e[0] for e in ends], 0.062 * yspan)
        for (_y, text, col), yy in zip(ends, pos):
            t = ax.text(1.012, yy, text, transform=yaxis_tf, color=col,
                        fontsize=small, va="center", ha="left",
                        clip_on=False)
            t.set_in_layout(False)      # the page reserves the gutter itself
    _titles(ax, title, subtitle, muted, st)
    if bottom_row:
        ax.set_xlabel(st["xlabel"]
                      or f"{a0.label.capitalize()} ({a0.units})")
    if first_col and not stacked:
        ax.set_ylabel(st["ylabel"] or (
            plotstyle.with_unit(r0.count_label,
                                plotstyle.y_unit(st, r0.count_units))
            if norm == "None" else f"{r0.count_label} (normalised)"))
    if reels and n == 1:               # a REELS band-gap construction
        draw_reels(ax, a0, r0.photon_energy, reels,
                   1.0 / norm_factor(r0, norm, cursor), muted, accent,
                   note_size=small)
    if markers:      # peak labels: (energy, text[, kinetic?[, tier]])
        lo, hi = ax.get_xlim()
        xtf = ax.get_xaxis_transform()       # x in data, y as axes fraction
        hv = r0.photon_energy
        tier_colour = {"secondary": accent, "auger": auger_colour or muted}
        for mk in markers:
            be, text = mk[0], mk[1]
            kin = len(mk) > 2 and mk[2]
            tier = mk[3] if len(mk) > 3 else None
            colour = tier_colour.get(tier, muted)
            if kin:                          # ISS peaks: a kinetic energy
                x = (hv - be if hv else None) if binding else be
            else:
                x = be if binding else (hv - be if hv else None)
            if x is None or not lo <= x <= hi:
                continue
            ax.plot([x, x], [0, 1], transform=xtf, color=colour, lw=0.7,
                    ls=":", zorder=1, scalex=False, scaley=False)
            ax.text(x, 0.99, text, transform=xtf, rotation=90, va="top",
                    ha="center", fontsize=plotstyle.note_size(st, -1),
                    color=colour,
                    bbox=dict(fc=ax.get_facecolor(), ec="none", pad=0.6,
                              alpha=0.85))
    if binding:
        ax.invert_xaxis()
    plotstyle.apply_ranges(ax, st, y=False)
    plotstyle.finish_axes(ax, st, y_ticks=not stacked)
    if boxed:
        ax.legend(loc=st["legend_loc"], fontsize=small,
                  frameon=bool(st["legend_frame"]), labelcolor="linecolor")
    if ke_top and binding and top_row and viewdata.photon_energy(regs):
        add_ke_axis(ax, viewdata.photon_energy(regs), muted, size=small)


def _titles(ax, title, subtitle, muted, st=None):
    st = plotstyle.resolve(st)
    title, subtitle = plotstyle.panel_titles(st, title, subtitle)
    ax.set_title(title, loc="left")
    if subtitle:
        ax.set_title(subtitle, loc="right", fontsize=plotstyle.note_size(st),
                     fontweight="normal", color=muted)


def draw_heatmap(fig, ax, regs, zi, norm="None", cmap=None, title="",
                 subtitle="", first_col=True, bottom_row=True, top_row=False,
                 muted="#56636E", scale="Binding", ke_top=False, style=None):
    """One panel as a heat map: energy across, ``zi`` (etch time / level,
    acquisition time or trace order, ascending downwards) down, intensity as
    colour. ``regs`` must already be in z order (see viewdata.z_sorted)."""
    import numpy as np
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.ticker import MaxNLocator
    st = plotstyle.resolve(style)
    small = plotstyle.note_size(st)
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
    _titles(ax, title, subtitle, muted, st)
    if bottom_row:
        ax.set_xlabel(st["xlabel"]
                      or f"{a0.label.capitalize()} ({a0.units})")
    plotstyle.apply_ranges(ax, st, y=False)
    plotstyle.finish_axes(ax, st, y_ticks=False)
    cb = fig.colorbar(mesh, ax=ax, pad=0.02, fraction=0.05, aspect=24)
    cb.outline.set_visible(False)
    cb.ax.tick_params(labelsize=plotstyle.note_size(st, -1), length=2)
    cb.set_label("Normalised" if norm != "None" else plotstyle.with_unit(
        r0.count_label, plotstyle.y_unit(st, r0.count_units)), fontsize=small)
    if ke_top and a0.invert and top_row and viewdata.photon_energy(regs):
        add_ke_axis(ax, viewdata.photon_energy(regs), muted, size=small)
    return mesh


def draw_waterfall3d(ax, regs, zi, norm="None", colours=None, title="",
                     subtitle="", pal=None, scale="Binding", style=None):
    """One panel as a 3-D waterfall: energy (x), trace z (y), intensity
    (vertical). ``ax`` must be a 3-D axes; ``regs`` in z order."""
    from matplotlib.collections import PolyCollection
    from matplotlib.colors import to_rgba
    pal = pal or themes.PALETTES[themes.DEFAULT]
    st = plotstyle.resolve(style)
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
                **plotstyle.line_kwargs(st, n))
    xs = [x for a in axes_x for x in a.x]
    ax.set_xlim(min(xs), max(xs))
    win = plotstyle.x_window(st, min(xs), max(xs))
    if win:
        ax.set_xlim(*win)
    zlo, zhi = min(zi.values), max(zi.values)
    pad = 0.5 if zhi == zlo else 0.0
    ax.set_ylim(zlo - pad, zhi + pad)
    ax.set_zlim(floor, max(max(v) for v in ys if v))
    if a0.invert:
        ax.invert_xaxis()
    _titles(ax, title, subtitle, pal["muted"], st)
    ax.set_xlabel(st["xlabel"] or f"{a0.label.capitalize()} ({a0.units})",
                  labelpad=2)
    ax.set_ylabel(zi.label, labelpad=2)
    ax.text2D(0.0, 0.9, "Normalised" if norm != "None"
              else plotstyle.with_unit(
                  r0.count_label, plotstyle.y_unit(st, r0.count_units)),
              transform=ax.transAxes, fontsize=plotstyle.note_size(st),
              color=pal["muted"])
    ax.tick_params(labelsize=plotstyle.note_size(st, -1), pad=0)
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


def draw_holder_markers(ax, points, hot=(), filled=False, cold="#19E0FF",
                        hot_colour="#FF4D4D", halo="#0B1116", size=9):
    """Analysis-position markers with the sample name beside each.

    ``points`` is ``{sample: (x, y)}`` in data coordinates. Markers and labels
    carry a halo (a stroke in ``halo``) so they stay readable over a photo
    of any brightness. Samples in ``hot`` (the ones selected or ticked) are
    larger, bold and in ``hot_colour``. Returns ``{sample: artists}``."""
    import matplotlib.patheffects as pe
    out = {}
    for name, (x, y) in points.items():
        is_hot = name in hot
        col = hot_colour if is_hot else cold
        s = 170 if is_hot else 95
        lw = 2.2 if is_hot else 1.6
        ring = ax.scatter([x], [y], s=s, facecolors="none", edgecolors=halo,
                          linewidths=lw + 2.6, zorder=3)
        dot = ax.scatter([x], [y], s=s, zorder=4, linewidths=lw,
                         facecolors=col if filled else "none",
                         edgecolors=col)
        text = ax.annotate(
            name or "(unnamed)", (x, y), textcoords="offset points",
            xytext=(9, -9), fontsize=size + (1 if is_hot else 0),
            color=col, fontweight="bold" if is_hot else "normal", zorder=5,
            path_effects=[pe.withStroke(linewidth=3.2, foreground=halo)])
        out[name] = (ring, dot, text)
    return out


_LABEL_SPOTS = ((9, -9, "left", "top"), (9, 9, "left", "bottom"),
                (-9, -9, "right", "top"), (-9, 9, "right", "bottom"),
                (0, -14, "center", "top"), (0, 14, "center", "bottom"),
                (16, 0, "left", "center"), (-16, 0, "right", "center"))


def place_marker_labels(ax, artists, hot=(), radius=9):
    """Give each marker label the first spot round its marker where it covers
    neither another label nor another marker (selected samples choose first).
    Call once the axes limits and layout are final; ``artists`` is what
    ``draw_holder_markers`` returned."""
    from matplotlib.transforms import Bbox
    fig = ax.figure
    try:
        renderer = fig.canvas.get_renderer()
    except AttributeError:                  # a canvas that only saves files
        try:
            renderer = fig._get_renderer()
        except Exception:
            return
    dots = {}
    for name, (_ring, dot, _text) in artists.items():
        x, y = ax.transData.transform(dot.get_offsets()[0])
        dots[name] = Bbox.from_bounds(x - radius, y - radius, 2 * radius,
                                      2 * radius)
    placed = []
    for name in sorted(artists, key=lambda n: n not in hot):
        text = artists[name][2]
        others = [b for n, b in dots.items() if n != name] + placed
        chosen = None
        for dx, dy, ha, va in _LABEL_SPOTS:
            text.xyann = (dx, dy)
            text.set_ha(ha)
            text.set_va(va)
            bb = text.get_window_extent(renderer)
            if not any(bb.overlaps(o) for o in others):
                chosen = bb
                break
        if chosen is None:                       # crowded: the first spot
            dx, dy, ha, va = _LABEL_SPOTS[0]
            text.xyann = (dx, dy)
            text.set_ha(ha)
            text.set_va(va)
            chosen = text.get_window_extent(renderer)
        placed.append(chosen)


def draw_fit(ax, x, fit, scale, muted, accent):
    """Overlay a reconstructed CasaXPS fit on a single-spectrum panel.

    ``fit`` is ``{"curves": [casafit.Curves], "show": {"envelope", "components",
    "background"}, "colours": [...], "state_colour": {name: colour}}``; ``x``
    are the panel's x values (one per data point) and ``scale`` multiplies
    every curve (normalisation).

    Components are named the same way CasaXPS shows them (a group's own tag,
    unless that is just the region's label, in which case the first
    component names it); two components with the same name -- whether
    they share an INDEX, come from different regions on this panel, or
    (via ``state_colour``, a dict the caller keeps across panels) appear on
    another panel of the same page or report -- get one legend entry and one
    colour. Without ``state_colour`` the mapping is local to this call only.
    The residual RMS of each curve with one to show (see
    ``casafit.Curves.residual_rms``) is noted in the top-right corner, since a
    number for how well the fit reproduces the data is otherwise only in the
    report's quantification table, not visible while looking at the plot."""
    import math
    show = fit.get("show", {})
    cols = fit.get("colours") or ["#888888"]
    state_colour = fit.get("state_colour")
    if state_colour is None:
        state_colour = {}
    names = {}
    for cv in fit["curves"]:
        base = ([(b * scale) if b == b else b for b in cv.background]
                if cv.background is not None else None)
        if show.get("background") and base is not None:
            ax.plot(x, base, color=muted, lw=1.0, ls="--", zorder=2.2)
        if show.get("components"):
            for comp, vals in cv.components:
                # a group's own name, unless CasaXPS just tagged it with
                # the region's label: then the first component names it
                grp = comp.group.strip()
                named = (comp.index >= 0 and grp and grp.lower()
                         != (cv.region or "").strip().lower())
                name = (grp if named else comp.name).strip()
                if name not in state_colour:
                    n = len(state_colour)
                    state_colour[name] = cols[n % len(cols)]
                if name not in names:
                    names[name] = (state_colour[name], name)
                col = names[name][0]
                y = [v * scale for v in vals]
                lo = base if base is not None else [0.0] * len(y)
                top = [(b + v) if (v == v and b == b) else float("nan")
                       for b, v in zip(lo, y)]
                ok = [t == t for t in top]
                ax.fill_between(x, lo, top, where=ok, color=col, alpha=0.35,
                                lw=0, zorder=1.6)
                ax.plot(x, top, color=col, lw=0.9, zorder=2.3)
        if show.get("envelope") and cv.envelope is not None:
            ax.plot(x, [v * scale for v in cv.envelope],
                    color=ax.xaxis.label.get_color(), lw=1.3, zorder=2.6)
    if names and show.get("components"):
        from matplotlib.patches import Patch
        handles = [Patch(facecolor=c, alpha=0.5, label=n[:22])
                   for c, n in names.values()]
        many = len(handles) > 6           # a long list would cover the data:
        fs = max(6, int(ax.xaxis.label.get_fontsize()) - 2)   # put it below
        if many:
            ax.legend(handles=handles, frameon=False, handlelength=1.0,
                      loc="upper center", bbox_to_anchor=(0.5, -0.2),
                      ncol=3, fontsize=fs - 1, columnspacing=1.2)
        else:
            ax.legend(handles=handles, loc="upper left", fontsize=fs,
                      frameon=False, handlelength=1.0)
    rms_bits = [(f"{cv.region}: " if len(fit["curves"]) > 1 else "")
               + f"{100 * cv.residual_rms:.1f}%"
               for cv in fit["curves"] if cv.residual_rms is not None]
    if rms_bits:
        fs = max(6, int(ax.xaxis.label.get_fontsize()) - 2)
        ax.text(0.98, 0.98, "RMS " + ", ".join(rms_bits),
                transform=ax.transAxes, ha="right", va="top",
                fontsize=fs, color=muted)


def draw_reels(ax, a0, hv, reels, scale, muted, accent, note_size=8):
    """Overlay a REELS band-gap construction on a single-spectrum panel: the
    elastic peak, the baseline, the tangent through the two picked points and
    the resulting gap. ``reels`` holds ``elastic`` (kinetic energy), ``p1`` /
    ``p2`` (loss, intensity), ``gap``, ``base``, ``slope``; ``a0`` is the
    panel's energy axis (``viewdata.energy_axis``); ``scale`` multiplies
    intensities (normalisation)."""
    import reels as rl

    def X(loss):                        # loss -> the panel's x value
        ke = reels["elastic"] - loss
        if a0.label == "Kinetic Energy":
            return ke
        return hv - ke if hv else None
    xe = X(0.0)
    if xe is not None:
        ax.axvline(xe, color=muted, lw=0.8, ls=":", zorder=1)
        ax.text(xe, 0.02, " elastic", transform=ax.get_xaxis_transform(),
                color=muted, fontsize=note_size, rotation=90, va="bottom",
                ha="right")
    for key in ("p1", "p2"):
        x, y = X(reels[key][0]), reels[key][1] * scale
        if x is not None:
            ax.plot([x], [y], "o", color=accent, ms=5, zorder=4)
    if "gap" not in reels or reels["gap"] is None:
        return
    (xa, ya), (xb, yb) = rl.tangent_points(reels, reels["p1"], reels["p2"])
    pts = [(X(xa), ya * scale), (X(xb), yb * scale)]
    if None in (pts[0][0], pts[1][0]):
        return
    ax.plot([pts[0][0], pts[1][0]], [pts[0][1], pts[1][1]], color=accent,
            lw=1.3, zorder=3.5)
    x0 = X(0.0)
    if x0 is not None:
        ax.plot([x0, pts[0][0]], [reels["base"] * scale] * 2, color=accent,
                lw=0.9, ls="--", zorder=3.4)
    ax.plot([pts[0][0]], [reels["base"] * scale], "s", color=accent, ms=4,
            zorder=4)
    ax.annotate(f"Eg = {reels['gap']:.2f} eV",
                (pts[0][0], reels["base"] * scale), xytext=(8, 14),
                textcoords="offset points", color=accent,
                fontsize=note_size + 1, fontweight="bold",
                arrowprops={"arrowstyle": "-", "color": accent, "lw": 0.7})
