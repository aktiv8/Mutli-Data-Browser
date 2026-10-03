"""Instrument settings a NeXus (NXxps / NXmpes) file asks for and instrument
files rarely state: the type of X-ray source, the analyser's dispersion and
collection-column schemes, the detector, the work function, the energy
resolution and the operator's affiliation (Tk-free).

They are **entered by the user, once per file**, and stored in
``Annotations.instrument`` (file id -> settings). Nothing is guessed: an
unset field is left out of the ``.nxs``. The choices are the enumerations of
the NXmpes application definition (NeXus definitions ``v2026.01``); a value
that is not one of them is dropped by ``sanitise``, so a file written from
them never carries a name the definition does not know."""

from __future__ import annotations

#: ``(key, label, kind, choices)``; kind is "choice", "number" or "text".
FIELDS = (
    ("source_type", "X-ray source type", "choice",
     ("Synchrotron X-ray Source", "Rotating Anode X-ray", "Fixed Tube X-ray",
      "UV Laser", "Free-Electron Laser", "Optical Laser", "UV Plasma Source",
      "Metal Jet X-ray", "HHG laser", "UV lamp",
      "Monochromatized electron source")),
    ("dispersion_scheme", "Energy dispersion", "choice",
     ("tof", "hemispherical", "double hemispherical", "cylindrical mirror",
      "display mirror", "retarding grid")),
    ("collection_scheme", "Collection column", "choice",
     ("angular dispersive", "spatial dispersive", "momentum dispersive",
      "non-dispersive")),
    ("detector_type", "Detector", "choice",
     ("DLD", "Phosphor+CCD", "Phosphor+CMOS", "ECMOS", "Anode",
      "Multi-anode")),
    ("amplifier_type", "Electron amplifier", "choice", ("MCP", "channeltron")),
    ("energy_scan_mode", "Analyser scan mode", "choice",
     ("fixed_analyzer_transmission", "fixed_retarding_ratio")),
    ("work_function_ev", "Analyser work function (eV)", "number", ()),
    ("energy_resolution_ev", "Energy resolution (eV)", "number", ()),
    ("operator", "Operator's name", "text", ()),
    ("affiliation", "Operator's affiliation", "text", ()),
    ("utc_offset_hours", "Recorded times: hours from UTC", "offset", ()),
)

KEYS = tuple(f[0] for f in FIELDS)
_KIND = {f[0]: f[2] for f in FIELDS}
_CHOICES = {f[0]: f[3] for f in FIELDS}


def _number(v):
    """A positive finite float from a number or text, else None."""
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(str(v).strip().replace(",", "."))
    except ValueError:
        return None
    return x if x == x and 0 < x < float("inf") else None


def _offset(v):
    """Hours from UTC, -12 to +14 (zero is a real answer), else None."""
    if v is None or isinstance(v, bool) or str(v).strip() == "":
        return None
    try:
        x = float(str(v).strip().replace(",", "."))
    except ValueError:
        return None
    return x if x == x and -12.0 <= x <= 14.0 else None


def sanitise(s):
    """Only the known fields that hold a valid value: a choice that is one of
    the NXmpes names (case does not matter, the canonical spelling is kept), a
    positive number, a UTC offset in hours (zero allowed), non-empty text. Anything else is dropped."""
    out = {}
    if not isinstance(s, dict):
        return out
    for key in KEYS:
        v = s.get(key)
        kind = _KIND[key]
        if kind == "choice":
            text = str(v).strip().lower() if v is not None else ""
            hit = next((c for c in _CHOICES[key] if c.lower() == text), None)
            if hit:
                out[key] = hit
        elif kind == "number":
            x = _number(v)
            if x is not None:
                out[key] = x
        elif kind == "offset":
            x = _offset(v)
            if x is not None:
                out[key] = x
        else:
            text = str(v).strip() if v is not None else ""
            if text:
                out[key] = text
    return out


def is_empty(s) -> bool:
    return not sanitise(s)


def describe(s) -> str:
    """One line of what is set, for a status text."""
    s = sanitise(s)
    if not s:
        return "nothing set"
    labels = {k: lab for k, lab, _kind, _c in FIELDS}
    return "; ".join(f"{labels[k]}: {s[k]:g}" if isinstance(s[k], float)
                     else f"{labels[k]}: {s[k]}" for k in KEYS if k in s)


def merged(*sources):
    """Settings from several dicts, an earlier one winning field by field."""
    out = {}
    for src in sources:
        for k, v in sanitise(src).items():
            out.setdefault(k, v)
    return out
