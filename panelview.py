"""Per-panel view settings (Tk-free).

The page has one *default* look (the view row: view, normalise, offset, z axis,
reverse, fit layers). A panel may override any of those keys, so one page can
show a depth profile as a waterfall, a survey as a stack and a CasaXPS fit as a
single fitted spectrum. Overrides are keyed by the panel's group label and are
stored beside the look (``Workspace.panel_views``, ``state["panel_views"]``).
Page-level settings (grouping, energy scale, style, colours) are not here.
"""
import viewdata

VIEWS = ("Stack", "Waterfall 3D", "Heatmap", "Fit")
SERIES = ("Waterfall 3D", "Heatmap")           # read in z order
NORMS = ("None", "Max = 1", "Area = 1", "At cursor")
FIT_LAYERS = ("components", "envelope", "background")
IDENT_LAYERS = ("secondary", "auger")
KEYS = ("view", "norm", "offset", "z_axis", "reverse", "fit_show",
        "ident_show")
OFFSET_RANGE = (0.0, 3.0)


def is_series(view):
    return view in SERIES


def sanitise(d):
    """The valid part of one panel's override; unknown keys and bad values are
    dropped. ``fit_show`` may name only some layers."""
    out = {}
    if not isinstance(d, dict):
        return out
    if d.get("view") in VIEWS:
        out["view"] = d["view"]
    if d.get("norm") in NORMS:
        out["norm"] = d["norm"]
    if d.get("z_axis") in viewdata.Z_MODES:
        out["z_axis"] = d["z_axis"]
    if isinstance(d.get("reverse"), bool):
        out["reverse"] = d["reverse"]
    v = d.get("offset")
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v:
        lo, hi = OFFSET_RANGE
        out["offset"] = round(max(lo, min(hi, float(v))), 4)
    fs = d.get("fit_show")
    if isinstance(fs, dict):
        fs = {k: fs[k] for k in FIT_LAYERS if isinstance(fs.get(k), bool)}
        if fs:
            out["fit_show"] = fs
    ids = d.get("ident_show")
    if isinstance(ids, dict):
        ids = {k: ids[k] for k in IDENT_LAYERS if isinstance(ids.get(k), bool)}
        if ids:
            out["ident_show"] = ids
    return out


def sanitise_all(views):
    """``{panel label: override}`` with every override cleaned; empty ones
    disappear."""
    out = {}
    if not isinstance(views, dict):
        return out
    for label, d in views.items():
        d = sanitise(d)
        if d:
            out[str(label)] = d
    return out


def resolve(defaults, override=None):
    """The full look of a panel: the page default with the override on top."""
    look = dict(defaults)
    look["fit_show"] = dict(defaults.get("fit_show") or {})
    look["ident_show"] = dict(defaults.get("ident_show") or {})
    ov = sanitise(override)
    fs = ov.pop("fit_show", {})
    ids = ov.pop("ident_show", {})
    look.update(ov)
    look["fit_show"].update(fs)
    look["ident_show"].update(ids)
    return look


def with_value(views, label, key, value):
    """A copy of ``views`` with one key of one panel's override set. For
    ``fit_show``/``ident_show`` pass ``(layer, bool)`` as the value."""
    out = {k: dict(v) for k, v in views.items()}
    cur = out.setdefault(label, {})
    if key in ("fit_show", "ident_show"):
        layer, on = value
        cur[key] = {**cur.get(key, {}), layer: bool(on)}
    else:
        cur[key] = value
    cleaned = sanitise_all(out)
    return cleaned


def reset(views, label=None):
    """A copy of ``views`` without one panel's override (or without any)."""
    if label is None:
        return {}
    return {k: dict(v) for k, v in views.items() if k != label}


def arrange(regs, look, z_order):
    """Order one group's spectra for its view. ``z_order(regs, mode)`` returns
    indices (``viewdata.z_sorted`` in the app). Series views read in z order,
    stacks and fits run in file order, optionally reversed."""
    if is_series(look["view"]):
        return [regs[i] for i in z_order(regs, look["z_axis"])]
    return list(regs)[::-1] if look["reverse"] else list(regs)


def describe(override, defaults=None):
    """A short phrase for tooltips and slide notes, e.g. "Waterfall 3D, by
    Etch level"; only what the override says (or what changes the default)."""
    ov = sanitise(override)
    if not ov:
        return ""
    look = resolve(defaults, ov) if defaults else ov
    view = look.get("view", "Stack")
    parts = [view]
    if is_series(view) and look.get("z_axis") not in (None, "Auto"):
        parts[0] += f", by {look['z_axis']}"
    if "norm" in ov and ov["norm"] != "None":
        parts.append(f"normalised {ov['norm']}")
    if "offset" in ov and view in ("Stack", "Fit"):
        parts.append(f"offset {ov['offset']:g}×")
    if ov.get("reverse"):
        parts.append("reversed")
    if view == "Fit":
        on = [k for k in FIT_LAYERS if look.get("fit_show", {}).get(k, True)]
        if len(on) < len(FIT_LAYERS):
            parts.append("showing " + (", ".join(on) if on else "no layers"))
    ident_on = [k for k in IDENT_LAYERS if look.get("ident_show", {}).get(k)]
    if ident_on:
        parts.append("nearby lines: " + ", ".join(ident_on))
    return ", ".join(parts)
