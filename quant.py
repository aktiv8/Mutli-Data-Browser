"""Quantification from CasaXPS fits (Tk-free; numpy only to evaluate).

What is recorded is what is used: the areas and RSFs are CasaXPS's own numbers
(read from the VAMAS ``CASA region`` / ``CASA comp`` lines by ``casafit``), the
background comes from ``casafit.curves``. Nothing is guessed: a region with no
RSF or no area is left out and says why.

Areas are in counts/s x eV: intensity is divided by dwell x scans, the same
scale ``casafit`` uses for the stored component areas (checked: the integral of
each reconstructed component equals its stored area).

``fit_rows(region)`` gives one row (a JSON-ready dict) per distinct fit region
of a *display* region (binding-energy shift applied, so positions are in the
frame that is drawn); ``normalise`` turns rows into atomic percent and
``states`` splits an element by chemical state (components sharing an INDEX are
one state; the others stand alone).

Region area = integral of (data - background) over the region, in raw kinetic
energy, as CasaXPS reports it. Where the background type is not reproduced the
sum of the component areas is used instead and the row says so (``basis``).
"""

import casafit


def _trapz(y, x):
    """Trapezoid rule; x ascending."""
    if len(x) < 2:
        return 0.0
    return float(((x[1:] - x[:-1]) * (y[1:] + y[:-1]) / 2.0).sum())


def fit_rows(r):
    """One row per distinct fit region of ``r`` (a Region with ``fit``), or [].

    Keys: region, background, rsf, area, area_t (with the transmission function
    divided out, None when the file has none), basis ("data" or "components"),
    be_lo / be_hi (region limits, binding energy), avg, rms, approximate,
    background_known, scale_known, and components (name, group, index, be,
    fwhm, area, shape, rsf)."""
    fit = getattr(r, "fit", None)
    if (fit is None or fit.is_empty() or not r.photon_energy or not r.energy
            or not r.counts):
        return []
    try:
        import numpy as np
    except ImportError:
        return []
    hv = float(r.photon_energy)
    scans = r.extra.get("n_scans", 1) or 1
    cvs = casafit.curves(fit, r.energy, r.counts, hv, r.dwell, scans)
    if not cvs:
        return []
    k = (r.dwell * scans) if r.dwell else 1.0
    ke = hv - np.asarray(r.energy, dtype=float)
    counts = np.asarray(r.counts, dtype=float)
    tf = r.transmission()
    tf = None if tf is None else np.asarray(tf, dtype=float)
    cshift = fit.shift_of_comps()
    rshift = fit.shift_of_regions()
    rows = []
    for cv in cvs:
        reg = cv.fit_region
        comps = [{"name": c.name, "group": c.group, "index": c.index,
                  "be": hv - (c.pos_ke + cshift), "fwhm": c.fwhm,
                  "area": c.area, "shape": c.shape, "rsf": c.rsf}
                 for c, _v in cv.components]
        area = area_t = None
        basis = "components"
        if cv.background is not None:
            bg = np.asarray(cv.background, dtype=float)
            ok = ~np.isnan(bg)
            if ok.sum() >= 3:
                order = np.argsort(ke[ok])
                x = ke[ok][order]
                d = (counts[ok][order] - bg[ok][order]) / k
                area, basis = _trapz(d, x), "data"
                if tf is not None and np.all(tf[ok] > 0):
                    area_t = _trapz(d / tf[ok][order], x)
        if area is None and comps:
            area = float(sum(c["area"] for c in comps))
        if area is None:
            continue
        lo = getattr(reg, "start_ke", None)
        hi = getattr(reg, "end_ke", None)
        rows.append({
            "region": cv.region, "background": cv.background_type,
            "rsf": getattr(reg, "rsf", None), "area": area, "area_t": area_t,
            "basis": basis,
            "be_lo": None if hi is None else hv - (hi + rshift),
            "be_hi": None if lo is None else hv - (lo + rshift),
            "avg": getattr(reg, "avg", 1), "rms": cv.residual_rms,
            "approximate": bool(cv.approximate),
            "background_known": bool(cv.background_known),
            "scale_known": bool(cv.scale_known),
            "components": comps})
    return rows


def normalise(rows, include=None, transmission=False):
    """Atomic percent of each row: (area / RSF) over the sum of the included
    rows. ``include`` is an optional list of booleans (default: all);
    ``transmission`` divides the transmission function out where the row has
    one. Returns one dict per row: ``corrected``, ``at_pct`` (None when the row
    is left out) and ``why`` (the reason, "" when it counts)."""
    out = []
    for i, row in enumerate(rows):
        res = {"corrected": None, "at_pct": None, "why": ""}
        area = row.get("area_t") if transmission and \
            row.get("area_t") is not None else row.get("area")
        rsf = row.get("rsf")
        if include is not None and not include[i]:
            res["why"] = "not included"
        elif not rsf or rsf <= 0:
            res["why"] = "no RSF"
        elif area is None or area <= 0:
            res["why"] = "no area"
        else:
            res["corrected"] = area / rsf
        out.append(res)
    total = sum(x["corrected"] for x in out if x["corrected"] is not None)
    for x in out:
        if x["corrected"] is not None and total > 0:
            x["at_pct"] = 100.0 * x["corrected"] / total
    return out


def states(row, at_pct=None):
    """Chemical states of one row: ``[{name, frac, at_pct}]``, each state's
    share of the row's positive component area. Components with the same INDEX
    (>= 0) are one state, named by the group's tag or its first component; the
    rest stand alone."""
    groups = {}
    for c in row.get("components") or []:
        a = max(0.0, c.get("area") or 0.0)
        idx = c.get("index", -1)
        key = ("i", idx) if idx is not None and idx >= 0 else ("c", c["name"])
        g = groups.setdefault(key, {"name": c.get("group") or c["name"]
                                    if key[0] == "i" else c["name"],
                                    "area": 0.0})
        g["area"] += a
    tot = sum(g["area"] for g in groups.values())
    if tot <= 0:
        return []
    return [{"name": g["name"], "frac": g["area"] / tot,
             "at_pct": None if at_pct is None else at_pct * g["area"] / tot}
            for g in groups.values()]
