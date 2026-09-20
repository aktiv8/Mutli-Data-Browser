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


def state_of(comp, region):
    """``(key, name)`` of the chemical state a component belongs to: components
    sharing an INDEX >= 0 are one state, named by the group's tag (unless that
    is only CasaXPS's label for the region, then by the first component); the
    others stand alone. The same rule ``plots.draw_fit`` uses for its legend."""
    idx = comp.get("index", -1)
    if idx is not None and idx >= 0:
        grp = (comp.get("group") or "").strip()
        named = grp and grp.lower() != (region or "").strip().lower()
        return f"i{idx}", (grp if named else comp["name"])
    return f"n{comp['name']}", comp["name"]


def fit_rows(r, curves=False):
    """One row per distinct fit region of ``r`` (a Region with ``fit``), or [].

    Keys: region, background, rsf, area, area_t (with the transmission function
    divided out, None when the file has none), basis ("data" or "components"),
    be_lo / be_hi (region limits, binding energy), avg, rms, approximate,
    background_known, scale_known, and components (name, group, index, be,
    fwhm, area, shape, rsf, plus ``gk`` / ``state``: its chemical state's key
    and name). With ``curves=True`` a row also has ``curves``: ``i0`` (index of
    the first point of the region in the spectrum) and the background, envelope
    and component curves from there on, in the spectrum's own counts."""
    fit = getattr(r, "fit", None)
    if (fit is None or fit.is_empty() or not r.photon_energy or not r.energy
            or not r.counts):
        return []
    try:
        import numpy as np
    except ImportError:
        return []
    hv = float(r.photon_energy)
    dwell, scans = r.dwell_and_scans()
    cvs = casafit.curves(fit, r.energy, r.counts, hv, dwell, scans)
    if not cvs:
        return []
    k = (dwell * scans) if dwell else 1.0
    ke = hv - np.asarray(r.energy, dtype=float)
    counts = np.asarray(r.counts, dtype=float)
    tf = r.transmission()
    tf = None if tf is None else np.asarray(tf, dtype=float)
    cshift = fit.shift_of_comps()
    rshift = fit.shift_of_regions()
    rows = []
    for cv in cvs:
        reg = cv.fit_region
        comps = []
        for c, _v in cv.components:
            comp = {"name": c.name, "group": c.group, "index": c.index,
                    "be": hv - (c.pos_ke + cshift), "fwhm": c.fwhm,
                    "area": c.area, "shape": c.shape, "rsf": c.rsf}
            comp["gk"], comp["state"] = state_of(comp, cv.region)
            comps.append(comp)
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
        if area is None and cv.background is None:
            continue                            # nothing to draw or count
        lo = getattr(reg, "start_ke", None)
        hi = getattr(reg, "end_ke", None)
        row = {
            "region": cv.region, "background": cv.background_type,
            "rsf": getattr(reg, "rsf", None), "area": area, "area_t": area_t,
            "basis": basis,
            "be_lo": None if hi is None else hv - (hi + rshift),
            "be_hi": None if lo is None else hv - (lo + rshift),
            "avg": getattr(reg, "avg", 1), "rms": cv.residual_rms,
            "approximate": bool(cv.approximate),
            "background_known": bool(cv.background_known),
            "scale_known": bool(cv.scale_known),
            "components": comps}
        if curves:
            row["curves"] = _curves_of(cv)
        rows.append(row)
    return rows


def _curves_of(cv):
    """The curves of one ``casafit.Curves`` from the first point of the region
    to the last, NaN gaps as None: ``{i0, bg, env, comps}``."""
    import numpy as np
    cols = [cv.background, cv.envelope] + [v for _c, v in cv.components]
    have = [np.asarray(c, dtype=float) for c in cols if c is not None]
    if not have:
        return None
    ok = ~np.isnan(have[0])
    idx = np.nonzero(ok)[0]
    if not len(idx):
        return None
    i0, i1 = int(idx[0]), int(idx[-1]) + 1

    def cut(c):
        if c is None:
            return None
        return [None if v != v else v for v in c[i0:i1]]
    return {"i0": i0, "bg": cut(cv.background), "env": cut(cv.envelope),
            "comps": [cut(v) for _c, v in cv.components]}


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
    (>= 0) are one state (see ``state_of``); the rest stand alone."""
    groups = {}
    for c in row.get("components") or []:
        a = max(0.0, c.get("area") or 0.0)
        key, name = state_of(c, row.get("region"))
        groups.setdefault(key, {"name": name, "area": 0.0})["area"] += a
    tot = sum(g["area"] for g in groups.values())
    if tot <= 0:
        return []
    return [{"name": g["name"], "frac": g["area"] / tot,
             "at_pct": None if at_pct is None else at_pct * g["area"] / tot}
            for g in groups.values()]


CSV_HEADER = ("Sample", "Level", "Spectrum", "Region", "Background", "RSF",
              "Area (counts/s.eV)", "Area / RSF", "at %", "State",
              "State at %", "Note")


def _g(v):
    return "" if v is None else f"{v:.6g}"


def csv_rows(groups, include=None, transmission=False):
    """The quantification table as rows of cells, header first. ``groups`` is
    ``[{"sample", "level", "entries": [{"spectrum", "row"}]}]``: each group (one
    sample at one depth level) is normalised on its own. ``include`` is an
    optional list (per group) of lists of booleans. A region row is followed by
    one row per chemical state. The HTML browser writes the same table."""
    out = [list(CSV_HEADER)]
    for gi, g in enumerate(groups):
        rows = [e["row"] for e in g["entries"]]
        res = normalise(rows, None if include is None else include[gi],
                        transmission)
        lv = "" if g.get("level") is None else str(g["level"])
        for e, x in zip(g["entries"], res):
            row = e["row"]
            area = (row.get("area_t") if transmission
                    and row.get("area_t") is not None else row.get("area"))
            out.append([g["sample"], lv, e["spectrum"], row["region"],
                        row.get("background", ""), _g(row.get("rsf")),
                        _g(area), _g(x["corrected"]), _g(x["at_pct"]), "", "",
                        x["why"]])
            if x["at_pct"] is not None:
                for st in states(row, x["at_pct"]):
                    out.append([g["sample"], lv, e["spectrum"], row["region"],
                                "", "", "", "", "", st["name"],
                                _g(st["at_pct"]), ""])
    return out


def profile(groups, mode="element", include=None, transmission=False):
    """A depth profile from the fit rows of one sample: ``groups`` is one
    ``{"level", "entries": [{"spectrum", "row"}]}`` per depth level (in depth
    order); each level is normalised on its own, as in ``csv_rows``.

    ``mode``: "element" (atomic % of each region), "state" (atomic % of each
    chemical state) or "share" (a state's percent of its own region). Returns
    ``{"levels": [...], "series": [{"name", "values"}]}`` with one value per
    level (None where the region is missing, left out or has no RSF). A region
    that appears twice at one level counts once (the first)."""
    levels = [g.get("level") for g in groups]
    series, order = {}, []
    for gi, g in enumerate(groups):
        rows = [e["row"] for e in g["entries"]]
        res = normalise(rows, None if include is None else include[gi],
                        transmission)
        seen = set()
        for e, x in zip(g["entries"], res):
            if x["at_pct"] is None:
                continue
            region = e["row"]["region"]
            if mode == "element":
                items = [(region, x["at_pct"])]
            else:
                items = [(f"{region}: {st['name']}",
                          st["at_pct"] if mode == "state"
                          else 100.0 * st["frac"])
                         for st in states(e["row"], x["at_pct"])]
            for name, v in items:
                if name in seen:
                    continue
                seen.add(name)
                if name not in series:
                    series[name] = [None] * len(groups)
                    order.append(name)
                series[name][gi] = v
    return {"levels": levels,
            "series": [{"name": n, "values": series[n]} for n in order]}
