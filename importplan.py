"""Deciding what to import when a folder holds the same data twice.

Thermo Avantage writes both ``.avg`` and ``.vgd`` for one acquisition and the
data are identical, so loading both just doubles everything in the tree. Pure
functions here; the dialog lives in the app.
"""

from __future__ import annotations

import os

CHOICES = ("avg", "vgd", "both")


def find_pairs(paths):
    """``[(avg_path, vgd_path)]`` for files in the same folder that share a
    (case-insensitive) name stem and have both extensions. Order follows the
    first appearance of each pair in ``paths``."""
    groups = {}
    for p in paths:
        stem, ext = os.path.splitext(os.path.basename(p))
        ext = ext.lower()
        if ext in (".avg", ".vgd"):
            key = (os.path.normcase(os.path.dirname(os.path.abspath(p))),
                   stem.lower())
            groups.setdefault(key, {}).setdefault(ext, p)
    return [(g[".avg"], g[".vgd"]) for g in groups.values()
            if ".avg" in g and ".vgd" in g]


def apply_choice(paths, pairs, choice):
    """The paths to load after resolving ``pairs``.

    ``choice`` is ``"avg"``, ``"vgd"`` or ``"both"``, or a dict mapping a
    pair's ``.avg`` path to one of those (pairs missing from the dict load
    both). Files that are not part of a pair are always kept, in order."""
    drop = set()
    for avg, vgd in pairs:
        c = choice.get(avg, "both") if isinstance(choice, dict) else choice
        if c not in CHOICES:
            raise ValueError(f"Unknown choice {c!r}")
        if c == "avg":
            drop.add(vgd)
        elif c == "vgd":
            drop.add(avg)
    return [p for p in paths if p not in drop]
