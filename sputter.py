"""Sputter (ion gun) settings of a depth profile, and what follows from them:
the ion fluence and, with an etch rate, the depth reached at each level.

    fluence = I · t / (q · e · A)        ions / cm²
    depth   = etch rate · t              nm

with ``I`` the ion current, ``t`` the cumulative etch time, ``q`` the charge
state, ``e`` the elementary charge and ``A`` the rastered area. Settings are
entered by the user (per sample, kept beside the data in ``annotations``) and
prefilled from whatever the instrument file records (``from_text`` reads
strings such as ``"5 keV Ar+"``). A value that is not known stays ``None``;
nothing is guessed, and ``missing`` says what to enter for a wanted axis.

Pure functions, no Tk.
"""

from __future__ import annotations

import math
import re

E_CHARGE = 1.602176634e-19          # C

CURRENT_UNITS = {"pA": 1e-12, "nA": 1e-9, "µA": 1e-6, "mA": 1e-3,
                 "A": 1.0}
RATE_UNITS = {"nm/s": 1.0, "nm/min": 1.0 / 60.0, "Å/s": 0.1,
              "Å/min": 0.1 / 60.0}          # value in nm per second

DEFAULTS = {"ion": "", "charge": 1, "energy_ev": None, "current": None,
            "current_unit": "nA", "raster_x": None, "raster_y": None,
            "etch_rate": None, "rate_unit": "nm/min"}
NUMBER_KEYS = ("energy_ev", "current", "raster_x", "raster_y", "etch_rate")


def _num(v):
    """A positive finite float from a number or numeric text, else None."""
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x > 0 else None


def sanitise(s):
    """A complete, valid settings dict from anything (a saved dict, partial
    values from a file); ``None`` values stay ``None``. Never raises."""
    out = dict(DEFAULTS)
    if not isinstance(s, dict):
        return out
    if isinstance(s.get("ion"), str):
        out["ion"] = s["ion"].strip()[:40]
    q = _num(s.get("charge"))
    out["charge"] = int(q) if q and q == int(q) and q <= 20 else 1
    for k in NUMBER_KEYS:
        out[k] = _num(s.get(k))
    if s.get("current_unit") in CURRENT_UNITS:
        out["current_unit"] = s["current_unit"]
    if s.get("rate_unit") in RATE_UNITS:
        out["rate_unit"] = s["rate_unit"]
    if out["raster_x"] and not out["raster_y"]:
        out["raster_y"] = out["raster_x"]          # a single size = square
    return out


def is_empty(s) -> bool:
    s = sanitise(s)
    return not (s["ion"] or any(s[k] for k in NUMBER_KEYS))


# -- derived quantities ---------------------------------------------------------
def current_a(s):
    s = sanitise(s)
    return None if s["current"] is None else \
        s["current"] * CURRENT_UNITS[s["current_unit"]]


def area_cm2(s):
    """Rastered area in cm² (mm × mm / 100)."""
    s = sanitise(s)
    if not (s["raster_x"] and s["raster_y"]):
        return None
    return s["raster_x"] * s["raster_y"] / 100.0


def rate_nm_s(s):
    s = sanitise(s)
    return None if s["etch_rate"] is None else \
        s["etch_rate"] * RATE_UNITS[s["rate_unit"]]


def flux(s):
    """Ions per cm² per second, or None until current and raster are known."""
    i, a = current_a(s), area_cm2(s)
    if i is None or a is None:
        return None
    q = sanitise(s)["charge"]
    return i / (q * E_CHARGE * a)


def fluence(s, t_s):
    """Ions/cm² after ``t_s`` seconds of etching (None if unknown)."""
    f = flux(s)
    return None if f is None or t_s is None else f * float(t_s)


def depth_nm(s, t_s):
    r = rate_nm_s(s)
    return None if r is None or t_s is None else r * float(t_s)


def missing(mode, s) -> str:
    """What to enter to get the z axis ``mode`` ('Depth' or 'Fluence'), or ''
    when the settings already allow it."""
    if mode == "Depth":
        return "" if rate_nm_s(s) else "enter the etch rate"
    if mode == "Fluence":
        need = []
        if current_a(s) is None:
            need.append("the ion current")
        if area_cm2(s) is None:
            need.append("the raster size")
        return ("enter " + " and ".join(need)) if need else ""
    return ""


# -- text --------------------------------------------------------------------------
def _fmt(x, digits=4):
    return f"{x:.{digits}g}"


def describe(s) -> str:
    """'5 keV Ar+, 1 nA, 2 x 2 mm raster' (only what is known)."""
    s = sanitise(s)
    parts = []
    head = " ".join(p for p in (
        (f"{_fmt(s['energy_ev'] / 1000)} keV" if s["energy_ev"] and
         s["energy_ev"] >= 1000 else
         (f"{_fmt(s['energy_ev'])} eV" if s["energy_ev"] else "")),
        s["ion"]) if p)
    if head:
        parts.append(head)
    if s["current"]:
        parts.append(f"{_fmt(s['current'])} {s['current_unit']}")
    if s["raster_x"]:
        parts.append(f"{_fmt(s['raster_x'])} × {_fmt(s['raster_y'])} mm "
                     f"raster")
    if s["etch_rate"]:
        parts.append(f"etch rate {_fmt(s['etch_rate'])} {s['rate_unit']}")
    return ", ".join(parts)


def metadata_rows(s, etch_time=None) -> dict:
    """Metadata entries for a region of a depth profile (empty when the
    settings hold nothing)."""
    s = sanitise(s)
    md = {}
    if s["ion"]:
        md["Sputter ion"] = s["ion"]
    if s["energy_ev"]:
        md["Sputter energy (eV)"] = _fmt(s["energy_ev"])
    if s["current"]:
        md["Sputter current"] = f"{_fmt(s['current'])} {s['current_unit']}"
    if s["raster_x"]:
        md["Raster (mm)"] = f"{_fmt(s['raster_x'])} × {_fmt(s['raster_y'])}"
    if s["etch_rate"]:
        md["Etch rate"] = f"{_fmt(s['etch_rate'])} {s['rate_unit']}"
    d = depth_nm(s, etch_time)
    if d is not None:
        md["Depth (nm)"] = _fmt(d, 5)
    f = fluence(s, etch_time)
    if f is not None:
        md["Fluence (ions/cm²)"] = f"{f:.4g}"
    return md


# -- reading settings out of instrument text -------------------------------------------
_ENERGY = re.compile(r"(\d+(?:\.\d+)?)\s*(keV|kV|eV|V)\b", re.I)
_CURRENT = re.compile(r"(\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*(pA|nA|uA|µA|"
                      r"μA|mA|A)\b")
_RASTER = re.compile(r"(\d+(?:\.\d+)?)\s*(?:mm)?\s*[x×X]\s*"
                     r"(\d+(?:\.\d+)?)\s*(mm|um|µm|μm)\b")
_ION = re.compile(r"\b(Ar\d*|He|Ne|Xe|Kr|O2|N2|Cs|Ga|Bi\d*|C60|H2O)"
                  r"(\d*[+-])?(?![A-Za-z])")


def from_text(text) -> dict:
    """Whatever settings a line of instrument text states, as a partial
    settings dict, e.g. ``"5 keV Ar+"`` or ``"Ar+ 3 kV 1.0 uA 2x2 mm"``."""
    t = str(text or "")
    out = {}
    m = _ION.search(t)
    if m:
        out["ion"] = m.group(1) + (m.group(2) or "")
    m = _ENERGY.search(t)
    if m:
        v = float(m.group(1))
        out["energy_ev"] = v * (1000.0 if m.group(2).lower() in ("kev", "kv")
                                else 1.0)
    m = _CURRENT.search(t)
    if m:
        unit = m.group(2).replace("u", "µ").replace("μ", "µ")
        out["current"] = float(m.group(1))
        out["current_unit"] = unit
    m = _RASTER.search(t)
    if m:
        scale = 1.0 if m.group(3) == "mm" else 0.001
        out["raster_x"] = float(m.group(1)) * scale
        out["raster_y"] = float(m.group(2)) * scale
    return sanitise(out) if out else {}


def from_properties(props) -> dict:
    """Settings from a mapping of instrument properties (Avantage
    ``...DepthProfileIonGun...``): keys holding 'IONGUN' or 'SPUTTER' are
    read. Only what is unambiguous is taken: text values go through
    ``from_text`` ("500 eV", "Ar+"), and a bare number is taken only as an
    energy when its key says eV. A unit is never guessed (a wrong one would
    silently give a wrong fluence): anything else is left for the user."""
    out = {}
    for key, value in (props or {}).items():
        k = str(key).upper()
        flat = k.replace("_", "")
        if not ("IONGUN" in flat or "SPUTTER" in flat):
            continue
        if isinstance(value, str):
            for name, v in from_text(value).items():
                if v not in (None, "") and name not in out and (
                        name != "current_unit" or "current" in out):
                    out[name] = v
            if "ion" not in out and any(w in k for w in ("SPECIES", "GAS"))                     and value.strip():
                out["ion"] = value.strip()
        elif ("ENERGY" in k and re.search(r"(^|_)EV$", k)
              and _num(value) is not None and "energy_ev" not in out):
            out["energy_ev"] = _num(value)
    return sanitise(out) if out else {}


def merge_prefill(*sources) -> dict:
    """Combine partial settings from several sources; earlier ones win."""
    out = {}
    for src in sources:
        for k, v in (src or {}).items():
            if v not in (None, "") and k not in out:
                out[k] = v
    return sanitise(out) if out else {}
