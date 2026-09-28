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
import imfp
import rsf as rsf_lib

SOURCE_SURVEY = "survey"
SOURCE_HIGH_RES = "high-res"

# "scofield_tpp2m"/"scofield_ke06" (see imfp.py) are not real libraries in
# rsf.py's table -- they reuse the "scofield" rows verbatim, then multiply
# by a kinetic-energy-dependent factor computed from a formula. This maps
# each to the base library its table lookup actually uses.
_IMFP_LIBRARIES = {"scofield_tpp2m": "scofield", "scofield_ke06": "scofield"}


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
    divided out, None when the file has none), photon_energy (needed by
    ``normalise``'s RSF fallback, which never otherwise sees the ``Region``),
    basis ("data" or "components"),
    source ("survey" or "high-res", from ``r.is_survey`` -- CasaXPS can
    quantify a wide survey region as readily as a fitted high-resolution one,
    but the two should not be treated as equally precise when mixed in one
    total), be_lo / be_hi (region limits, binding energy), avg, rms, chi2_red
    (Poisson-weighted reduced chi-square, None when dwell/scans are unknown),
    approximate, background_known, scale_known, and components (name, group, index, be,
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
            "photon_energy": hv, "basis": basis,
            "source": SOURCE_SURVEY if r.is_survey else SOURCE_HIGH_RES,
            "be_lo": None if hi is None else hv - (hi + rshift),
            "be_hi": None if lo is None else hv - (lo + rshift),
            "avg": getattr(reg, "avg", 1), "rms": cv.residual_rms,
            "chi2_red": cv.chi2_red,
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


def normalise(rows, include=None, transmission=False, rsf_table=None,
             rsf_library="scofield"):
    """Atomic percent of each row: (area / RSF) over the sum of the included
    rows. ``include`` is an optional list of booleans (default: all);
    ``transmission`` divides the transmission function out where the row has
    one. Returns one dict per row: ``corrected``, ``at_pct`` (None when the row
    is left out), ``why`` (the reason, "" when it counts), and ``rsf_source``/
    ``rsf_anode``/``rsf_value`` (all None for the ordinary case below --
    stated only when a substitute RSF is used, never silently identical to a
    real recorded one).

    A row's own recorded RSF (``row["rsf"]``) is used first, exactly as
    always. Only when that is missing/falsy are two further tiers tried, in
    order, before giving up with ``why = "no RSF"``:

    1. **Each component's own RSF** (``rsf_source = "component"``): a
       KherveFitting-derived fit can carry a different, individually
       cross-referenced RSF per component (a doublet's two members are
       physically distinct lines, unlike CasaXPS's convention of one RSF for
       the whole region) -- ``sum(area_i / rsf_i)`` over the components that
       have one, in place of ``area / rsf``. Numerically a no-op for a
       region whose components all share the region's own (falsy) RSF, so
       this changes nothing for a plain CasaXPS file.
    2. **A reference-table lookup** (``rsf_table``, a list from
       ``rsf.load_rsf()``; ``rsf_library`` picks which one, default
       "scofield") -- **off by default** (``rsf_table=None``), the same
       "nothing is guessed" stance this module already takes on a missing
       RSF: only tried when a caller explicitly supplies a table. Looked up
       by the row's own region name and photon energy via ``rsf.rsf_of``;
       when found, ``rsf_source``/``rsf_anode``/``rsf_value`` record exactly
       which library/anode/number was substituted. ``rsf_library``
       ``"scofield_tpp2m"``/``"scofield_ke06"`` look up the base "scofield"
       value the same way, then multiply it by a kinetic-energy-dependent
       factor from ``imfp.py`` (``imfp_nm``/``ke_power_factor``, computed
       from the row's own ``be_lo``/``be_hi``/``photon_energy`` --
       ``res["imfp_nm"]``/``res["ke_power_factor"]`` record which) --
       **never** applied to a real recorded RSF or to the Kratos Axis F1s
       library, both empirical values with their own implicit kinetic-
       energy dependence already baked in (see ``imfp.py``'s own
       docstring). When TPP-2M's own kinetic energy is outside its stated
       validity range, the row honestly falls back to the plain,
       uncorrected Scofield value and ``rsf_source = "scofield"``, never a
       silently-wrong extrapolation."""
    out = []
    for i, row in enumerate(rows):
        res = {"corrected": None, "at_pct": None, "why": "",
               "rsf_source": None, "rsf_anode": None, "rsf_value": None,
               "imfp_nm": None, "ke_power_factor": None}
        area = row.get("area_t") if transmission and \
            row.get("area_t") is not None else row.get("area")
        own_rsf = row.get("rsf")
        if include is not None and not include[i]:
            res["why"] = "not included"
        elif own_rsf and own_rsf > 0:
            if area is None or area <= 0:
                res["why"] = "no area"
            else:
                res["corrected"] = area / own_rsf
        else:
            comp_total = sum(
                c["area"] / c["rsf"] for c in (row.get("components") or [])
                if c.get("rsf") and c["rsf"] > 0 and c.get("area") is not None)
            if comp_total > 0:
                res["corrected"] = comp_total
                res["rsf_source"] = "component"
            elif rsf_table:
                base_library = _IMFP_LIBRARIES.get(rsf_library, rsf_library)
                value = rsf_lib.rsf_of(row.get("region"), rsf_table,
                                       base_library, row.get("photon_energy"))
                if not value:
                    res["why"] = "no RSF"
                elif area is None or area <= 0:
                    res["why"] = "no area"
                else:
                    source = base_library
                    if rsf_library in _IMFP_LIBRARIES:
                        be_lo, be_hi = row.get("be_lo"), row.get("be_hi")
                        hv = row.get("photon_energy")
                        ke = (hv - (be_lo + be_hi) / 2.0
                             if hv is not None and be_lo is not None
                             and be_hi is not None else None)
                        if rsf_library == "scofield_tpp2m":
                            factor, factor_key = imfp.imfp_nm(ke), "imfp_nm"
                        else:
                            factor, factor_key = (imfp.ke_power_factor(ke),
                                                  "ke_power_factor")
                        if factor:
                            value = value * factor
                            source = rsf_library
                            res[factor_key] = factor
                    res["corrected"] = area / value
                    res["rsf_source"] = source
                    res["rsf_anode"] = rsf_lib.anode_for(
                        row.get("photon_energy"))
                    res["rsf_value"] = value
            else:
                res["why"] = "no RSF"
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
              "State at %", "Note", "Source", "RSF Source")


def _g(v):
    return "" if v is None else f"{v:.6g}"


def _rsf_source_text(x):
    """"" for a row's own recorded RSF (the ordinary case); otherwise says
    what substituted it, for the same honesty ``resultspages.py``'s report
    tables give (never silently identical to a real recorded RSF)."""
    src = x.get("rsf_source")
    if not src:
        return ""
    if src == "component":
        return "components' own RSF"
    label = rsf_lib.LIBRARY_SHORT.get(src, src)
    return f"{label}, {x['rsf_anode']} Kα ({_g(x['rsf_value'])})"


def csv_rows(groups, include=None, transmission=False, rsf_table=None,
            rsf_library="scofield"):
    """The quantification table as rows of cells, header first. ``groups`` is
    ``[{"sample", "level", "entries": [{"spectrum", "row"}]}]``: each group (one
    sample at one depth level) is normalised on its own. ``include`` is an
    optional list (per group) of lists of booleans. ``rsf_table``/
    ``rsf_library`` are ``normalise``'s own RSF-fallback args (off by
    default). A region row is followed by one row per chemical state. The
    HTML browser writes the same table."""
    out = [list(CSV_HEADER)]
    for gi, g in enumerate(groups):
        rows = [e["row"] for e in g["entries"]]
        res = normalise(rows, None if include is None else include[gi],
                        transmission, rsf_table, rsf_library)
        lv = "" if g.get("level") is None else str(g["level"])
        for e, x in zip(g["entries"], res):
            row = e["row"]
            area = (row.get("area_t") if transmission
                    and row.get("area_t") is not None else row.get("area"))
            out.append([g["sample"], lv, e["spectrum"], row["region"],
                        row.get("background", ""), _g(row.get("rsf")),
                        _g(area), _g(x["corrected"]), _g(x["at_pct"]), "", "",
                        x["why"], row.get("source", ""), _rsf_source_text(x)])
            if x["at_pct"] is not None:
                for st in states(row, x["at_pct"]):
                    out.append([g["sample"], lv, e["spectrum"], row["region"],
                                "", "", "", "", "", st["name"],
                                _g(st["at_pct"]), "", "", ""])
    return out


def profile(groups, mode="element", include=None, transmission=False,
           rsf_table=None, rsf_library="scofield"):
    """A depth profile from the fit rows of one sample: ``groups`` is one
    ``{"level", "entries": [{"spectrum", "row"}]}`` per depth level (in depth
    order); each level is normalised on its own, as in ``csv_rows``.
    ``rsf_table``/``rsf_library`` are ``normalise``'s own RSF-fallback args
    (off by default).

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
                        transmission, rsf_table, rsf_library)
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
