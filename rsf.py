"""Relative sensitivity factors (RSF) for quantification, as a fallback for
a fit that carries none of its own (``assets/xps_rsf.json``, editable),
curated directly from a real CasaXPS installation's own library files
(``D:\\Cloud Services\\...\\CasaXPS.LBD\\casaXPS-scofield.lib`` -- library
"scofield", normalised to C 1s = 1.0 -- and ``casaXPS_KratosAxis-F1s.lib`` --
library "kratos_f1s", normalised to F 1s = 1.0, which gives C 1s ~= 0.278,
the "Wagner-style" scale most real CasaXPS files' own recorded RSFs already
use). Pure functions; no Tk.

**The two libraries are on different absolute scales.** Mixing a fallback
value from one into a total that also has a real, file-recorded RSF from a
different convention would silently produce a wrong split -- not obviously
wrong, just off by whatever the two scales' ratio happens to be for that
pair of lines. This module never picks a library on its own: a caller
supplies one explicitly (``quant.py``'s own fallback stays off by default
for exactly this reason, matching its existing "nothing is guessed" stance
on a missing RSF).

``line`` in the table is this app's own canonical region-name string
(``readers.base.canon_region_name``), matched **exactly** against a fitted
region's own name -- no fuzzy matching, and a whole-subshell entry (e.g.
"Pt 4f") is never combined from or split into its own spin-orbit members
("Pt 4f7/2"/"Pt 4f5/2", separate rows with their own distinct values):
nothing is guessed beyond what the table states verbatim for that exact
line."""

from __future__ import annotations

import json
import os

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "assets", "xps_rsf.json")

LIBRARIES = {"scofield": "Scofield (CasaXPS casaXPS-scofield.lib)",
             "kratos_f1s": "Kratos Axis F1s (CasaXPS "
                          "casaXPS_KratosAxis-F1s.lib)"}
LIBRARY_SHORT = {"scofield": "Scofield", "kratos_f1s": "Kratos F1s"}
AL_HV, MG_HV = 1486.6, 1253.6


def load_rsf(path=None):
    """The RSF table as a list of dicts (``library``, ``anode``, ``line``,
    ``rsf``); [] if the file is missing or unreadable."""
    try:
        with open(path or DEFAULT_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        out = []
        for e in data.get("rsf", []):
            if (isinstance(e, dict) and e.get("library") and e.get("anode")
                    and e.get("line")
                    and isinstance(e.get("rsf"), (int, float))
                    and e["rsf"] > 0):
                out.append(e)
        return out
    except (OSError, ValueError, AttributeError):
        return []


def anode_for(hv):
    """"Mg" if ``hv`` is nearer 1253.6 eV than 1486.6 eV, else "Al" -- the
    default when ``hv`` is None or the two are equidistant, since Al Kalpha
    is by far the common case (the same default this app already assumes
    elsewhere, e.g. ``xpslines.DEFAULT_HV``)."""
    if hv and abs(float(hv) - MG_HV) < abs(float(hv) - AL_HV):
        return "Mg"
    return "Al"


def rsf_of(line, table, library="scofield", hv=None):
    """The RSF of ``line`` (a canonical region name, e.g. "Pt 4f") in
    ``table`` under ``library`` at the anode ``anode_for(hv)`` picks, or
    None when that exact line/anode/library combination is not in the
    table."""
    anode = anode_for(hv)
    for e in table:
        if (e["library"] == library and e["anode"] == anode
                and e["line"] == line):
            return float(e["rsf"])
    return None
