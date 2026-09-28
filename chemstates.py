"""Chemical-state identification: literature-derived binding energies for
named compounds/oxidation states of a core level (``assets/
xps_chemical_states.json``, editable), curated from KherveFitting's Peaks
Library JSON files (github.com/KherveFitting/KherveFitting; mostly the
Biesinger group's Applied Surface Science handbook papers -- each row's own
``source`` cites the paper when its containing folder names one). Pure
functions; no Tk.

This is a level more specific than ``xpslines.py``'s element/line table:
where ``xpslines.candidates`` answers "which element and orbital is this
peak" (e.g. "Fe 2p"), ``state_candidates`` here answers "which chemical
state of that orbital" (e.g. "Fe2p3/2 aFe2O3 peak 1", cited to Biesinger et
al.) -- a stronger, more specific claim, so callers should show the two
tiers distinctly rather than merge them into one ranked list.

A binding energy here is the position from one worked example fit in the
source file, not a guaranteed universal constant: real charge referencing,
instrument and sample variation all shift it. Treat a match as a starting
point for identification, not ground truth."""

from __future__ import annotations

import json
import os

from readers.base import canon_region_name

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "assets", "xps_chemical_states.json")


def _valid_range(r):
    return (isinstance(r, (list, tuple)) and len(r) == 2
            and all(isinstance(v, (int, float)) for v in r) and r[0] <= r[1])


def load_states(path=None):
    """The chemical-state table as a list of dicts (``core_level``, ``state``,
    ``be``, ``fwhm``, ``model``, ``source``, optional ``range``); [] if the
    file is missing or unreadable. A present-but-malformed ``range`` is
    dropped (not the whole entry), the same as a state with none at all."""
    try:
        with open(path or DEFAULT_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        out = []
        for e in data.get("states", []):
            if (isinstance(e, dict) and e.get("core_level") and e.get("state")
                    and isinstance(e.get("be"), (int, float))):
                if "range" in e and not _valid_range(e["range"]):
                    e = {k: v for k, v in e.items() if k != "range"}
                out.append(e)
        return out
    except (OSError, ValueError, AttributeError):
        return []


def label_of(entry):
    return str(entry["state"])


def state_candidates(be, window, states, core_level=None):
    """Chemical states within ``window`` eV of ``be``, plus any state whose
    own (empirical) ``range`` contains ``be`` even if that falls outside
    ``window``: ``[(delta, entry)]``, nearest first by ``delta`` (still
    ``entry["be"] - be``, so a range-admitted candidate simply sorts after
    the true near matches). ``core_level`` (a region name such as "Fe2p" or
    "Fe 2p", canonicalised the same way regions are grouped elsewhere in the
    app) restricts the match to that core level only; without it every state
    in the table is a candidate, which is rarely what a caller wants since
    the same binding-energy range can hold states of unrelated core levels."""
    want = canon_region_name(core_level) if core_level else None
    out = []
    for e in states:
        if want is not None and e["core_level"] != want:
            continue
        d = float(e["be"]) - be
        rng = e.get("range")
        in_range = rng is not None and rng[0] <= be <= rng[1]
        if abs(d) <= window or in_range:
            out.append((d, e))
    out.sort(key=lambda t: abs(t[0]))
    return out


def core_levels(states):
    """The distinct core levels the table covers, sorted."""
    return sorted({e["core_level"] for e in states})
