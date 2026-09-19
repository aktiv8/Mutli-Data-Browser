"""Pure helpers for the alternative plot views (no Tk, no matplotlib): the
energy axis (binding / kinetic), the z axis of waterfall and heat-map views
(etch time / level, acquisition time or plain trace order) and the
resampling of many spectra onto one energy grid.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import NamedTuple

ENERGY_SCALES = ("Binding", "Kinetic")
Z_MODES = ("Auto", "Etch time", "Etch level", "Acquisition time",
           "Trace order")


# -- energy axis ---------------------------------------------------------------
class Axis(NamedTuple):
    x: list             # abscissa values, in the order of the region's counts
    label: str          # e.g. "Binding Energy"
    units: str
    invert: bool        # binding-energy axes are drawn high -> low
    ok: bool            # False: kinetic was asked for but hν is unknown


def is_binding(region) -> bool:
    return (region.energy_label or "").lower().startswith("binding")


def energy_axis(region, scale="Binding") -> Axis:
    """The x values and axis look for one region.

    Binding energies are the native axis for XPS with a known photon energy.
    ``scale="Kinetic"`` converts them (KE = hν − BE); if hν is unknown the
    native axis is kept and ``ok`` is False. A region that is natively
    kinetic (no hν, so it was never converted) is left alone either way."""
    native = Axis(list(region.energy), region.energy_label,
                  region.energy_units, is_binding(region), True)
    if scale != "Kinetic" or not is_binding(region):
        return native
    ke = region.kinetic_energy
    if ke is None:
        return native._replace(ok=False)
    return Axis(list(ke), "Kinetic Energy", region.energy_units, False, True)


def photon_energy(regions):
    """First known photon energy among ``regions`` (None if none has one)."""
    for r in regions:
        if r.photon_energy:
            return r.photon_energy
    return None


def mixed_photon_energy(regions) -> bool:
    hvs = {round(r.photon_energy, 2) for r in regions if r.photon_energy}
    return len(hvs) > 1


# -- z axis ----------------------------------------------------------------------
_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
                 "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d.%m.%Y %H:%M:%S",
                 "%d %b %Y %H:%M:%S", "%d-%b-%Y %H:%M:%S",
                 "%a %b %d %H:%M:%S %Y", "%Y-%m-%d", "%d/%m/%Y")


def parse_date(text):
    """Best-effort datetime from the assorted strings the readers produce
    (None when unparseable)."""
    s = re.sub(r"\s+", " ", (text or "").strip())
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})", s)
    if m:                                    # trailing zone / fractional seconds
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)}",
                                     "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return None


class ZInfo(NamedTuple):
    values: list        # one per region, in the order given
    label: str          # axis label, with units
    mode: str           # which mode was actually used (one of Z_MODES[1:])


def _distinct(values) -> bool:
    return len({round(v, 9) for v in values}) > 1


def _z_candidates(regions, date_of):
    """{mode: (values, label)} for every mode the regions can support."""
    out = {}
    times = [r.etch_time for r in regions]
    if all(t is not None for t in times) and _distinct(times):
        out["Etch time"] = ([float(t) for t in times], "Etch time (s)")
    levels = [r.etch_level for r in regions]
    if all(v is not None for v in levels) and _distinct(levels):
        out["Etch level"] = ([float(v) for v in levels], "Etch level")
    if date_of is not None:
        dts = [parse_date(date_of(r)) for r in regions]
        if all(d is not None for d in dts) and len({*dts}) > 1:
            t0 = min(dts)
            secs = [(d - t0).total_seconds() for d in dts]
            span = max(secs)
            if span >= 7200:
                out["Acquisition time"] = ([s / 3600 for s in secs],
                                           "Time since first (h)")
            elif span >= 120:
                out["Acquisition time"] = ([s / 60 for s in secs],
                                           "Time since first (min)")
            else:
                out["Acquisition time"] = (secs, "Time since first (s)")
    out["Trace order"] = ([float(i + 1) for i in range(len(regions))],
                          "Trace")
    return out


def resolve_z(regions, mode="Auto", date_of=None) -> ZInfo:
    """The z value of each region for the requested mode.

    "Auto" (or a mode this data cannot support) falls back through etch
    time → etch level → acquisition time → trace order, taking the first that
    has at least two distinct values; etch times that are all 0 (not recorded
    in the file) therefore count as absent. ``date_of(region)`` supplies the
    acquisition date string (readers differ in where they keep it)."""
    cands = _z_candidates(regions, date_of)
    order = ("Etch time", "Etch level", "Acquisition time", "Trace order")
    if mode in cands and mode != "Auto":
        pick = mode
    else:
        pick = next(m for m in order if m in cands)
    values, label = cands[pick]
    return ZInfo(values, label, pick)


def z_sorted(regions, mode="Auto", date_of=None):
    """Regions ordered by z for plotting: ``(order, ZInfo)`` where ``order``
    indexes ``regions`` and ``ZInfo.values`` is already in that order.

    Heat maps and waterfalls need strictly increasing z, so if two traces
    share a value (e.g. the same level of two samples) the trace order is
    used instead."""
    info = resolve_z(regions, mode, date_of)
    order = sorted(range(len(regions)), key=lambda i: info.values[i])
    vals = [info.values[i] for i in order]
    if any(b <= a for a, b in zip(vals, vals[1:])):
        info = resolve_z(regions, "Trace order", date_of)
        order = list(range(len(regions)))
        vals = list(info.values)
    return order, ZInfo(vals, info.label, info.mode)


# -- heat map ---------------------------------------------------------------------
def edges(centres):
    """Cell edges around monotonically increasing ``centres`` (len n + 1)."""
    n = len(centres)
    if n == 1:
        return [centres[0] - 0.5, centres[0] + 0.5]
    mids = [(a + b) / 2 for a, b in zip(centres, centres[1:])]
    return [2 * centres[0] - mids[0]] + mids + [2 * centres[-1] - mids[-1]]


def build_matrix(xs_list, ys_list, max_points=1200):
    """Resample spectra onto one ascending energy grid.

    ``xs_list``/``ys_list`` hold one x array and one intensity array per
    trace (either direction). Returns ``(grid, rows)`` with ``rows[i]`` the
    i-th trace interpolated onto ``grid`` (NaN outside its own range), as
    numpy arrays. The grid spans the union of the traces at their median
    step, capped at ``max_points``."""
    import numpy as np
    pairs = []
    for xs, ys in zip(xs_list, ys_list):
        x = np.asarray(xs, dtype=float)
        y = np.asarray(ys, dtype=float)
        o = np.argsort(x)
        pairs.append((x[o], y[o]))
    lo = min(p[0][0] for p in pairs)
    hi = max(p[0][-1] for p in pairs)
    steps = [float(np.median(np.diff(p[0]))) for p in pairs if len(p[0]) > 1]
    step = min(steps) if steps else 1.0
    n = int(round((hi - lo) / step)) + 1 if step > 0 else 2
    n = max(2, min(max_points, n))
    grid = np.linspace(lo, hi, n)
    rows = np.full((len(pairs), n), np.nan)
    for i, (x, y) in enumerate(pairs):
        inside = (grid >= x[0]) & (grid <= x[-1])
        rows[i, inside] = np.interp(grid[inside], x, y)
    return grid, rows
