"""What the desktop Quantification tab lets the user change, without Tk
(``quant_ui.QuantPanel`` draws it): which fitted regions count, whether the
transmission function is divided out, which depth level is shown and how a
depth profile is drawn.

``resultspages.collect`` decides what counts *by default* (a region fitted in
several spectra counts once, an element with a known standard line counts
that line) and stores it on each ``Level``. The user's ticks are kept apart in
a ``ViewState`` -- an absent key means "the default" -- and ``effective``
re-runs ``quant.normalise`` on a copy of the level, so the report's own
numbers are never touched. Ticking a region the report leaves out is allowed,
as on the HTML page (``viewer.js`` ``renderFitQuant``); the panel marks every
row whose tick differs from the default (``changed``).

Every number comes from ``quant`` / ``resultspages``; nothing is computed here.
"""

from __future__ import annotations

import copy

import quant
import resultspages

PROFILE_MODES = (("element", "Element (at %)"),
                 ("state", "Chemical state (at %)"),
                 ("share", "State share of its region (%)"))


class ViewState:
    """The user's choices. ``include`` maps ``(sample key, level index, entry
    index)`` to a tick; a missing key follows the level's own default."""

    def __init__(self):
        self.include = {}
        self.transmission = False
        self.level = {}                 # sample key -> level index; None = the
                                        # depth profile
        self.profile_mode = "element"
        self._sigs = {}                 # sample key -> signature(sample)

    def ticked(self, skey, li, ei, default):
        return self.include.get((skey, li, ei), default)

    def toggle(self, skey, li, ei, default):
        """Flip one tick; returns the new value. A tick that is back at the
        default is forgotten, so ``changed`` stays truthful."""
        now = not self.ticked(skey, li, ei, default)
        if now == default:
            self.include.pop((skey, li, ei), None)
        else:
            self.include[(skey, li, ei)] = now
        return now

    def reset(self, skey=None):
        """Forget the ticks of one sample (or of all)."""
        if skey is None:
            self.include.clear()
        else:
            for k in [k for k in self.include if k[0] == skey]:
                del self.include[k]

    def level_index(self, sample):
        """The level shown for ``sample`` (clamped: levels can disappear)."""
        n = len(sample.levels)
        return max(0, min(self.level.get(sample.key) or 0, n - 1)) if n else 0

    def shown(self, sample):
        """What the table shows for ``sample``: a level index, or ``None``
        for the depth profile (the default for a sample with two or more
        levels, as in the report)."""
        if sample.is_profile and self.level.get(sample.key, None) is None:
            return None
        return self.level_index(sample)

    def sync(self, samples):
        """Forget the ticks of any sample whose regions are no longer the
        ones they were made for (a file added, a spectrum unticked, a rename):
        a tick is stored by position, so it must not slide onto another
        row."""
        for s in samples:
            sig = signature(s)
            if self._sigs.get(s.key, sig) != sig:
                self.reset(s.key)
            self._sigs[s.key] = sig


def signature(sample):
    """Which regions a sample's levels hold, in order (what a tick refers
    to)."""
    return tuple((lv.level, tuple((e["spectrum"], e["row"]["region"])
                                  for e in lv.entries))
                 for lv in sample.levels)


def level_label(lv, i):
    """"Level 3 (etch 40 s, 2.5 nm)" for a choice list."""
    bits = []
    if lv.etch is not None:
        bits.append(f"etch {lv.etch:g} s")
    if lv.depth is not None:
        bits.append(f"{lv.depth:g} nm")
    n = lv.level if lv.level is not None else i + 1
    return f"Level {n}" + (f" ({', '.join(bits)})" if bits else "")


def transmission_available(samples):
    """True when any row has an area with the transmission function divided
    out (``quant.fit_rows`` gives ``area_t`` only when the file has one)."""
    return any(e["row"].get("area_t") is not None
               for s in samples for lv in s.levels for e in lv.entries)


def includes(sample, li, state):
    """The tick of every entry of one level of ``sample``."""
    lv = sample.levels[li]
    return [state.ticked(sample.key, li, ei, lv.include[ei])
            for ei in range(len(lv.entries))]


def changed(sample, li, state):
    """Per entry: does the user's tick differ from the default?"""
    lv = sample.levels[li]
    return [(sample.key, li, ei) in state.include
            for ei in range(len(lv.entries))]


def effective(sample, li, state):
    """A copy of level ``li`` of ``sample`` with the user's ticks and the
    transmission choice applied: ``include``, ``why`` and ``res`` (the output
    of ``quant.normalise`` with the sample's own RSF-fallback arguments).

    A row left out by default keeps the report's reason ("counted once", "not
    the preferred line") while it stays unticked; one the user unticks says
    "not included"; one the user ticks anyway has no reason."""
    base = sample.levels[li]
    inc = includes(sample, li, state)
    out = copy.copy(base)
    out.include = inc
    out.why = [base.why[i] if (not inc[i] and not base.include[i]) else ""
               for i in range(len(inc))]
    out.res = quant.normalise([e["row"] for e in base.entries], inc,
                              state.transmission, sample.rsf_table,
                              sample.rsf_library)
    for x, why in zip(out.res, out.why):
        if why:
            x["why"] = why
    return out


def composition(sample, li, state):
    """``resultspages.composition_cells`` of the level as the user sees it."""
    return resultspages.composition_cells(effective(sample, li, state))


def profile(sample, state):
    """``quant.profile`` of a sample for the chosen mode, with the user's
    ticks and the transmission choice."""
    return quant.profile(
        [lv.group() for lv in sample.levels], state.profile_mode,
        [includes(sample, li, state) for li in range(len(sample.levels))],
        state.transmission, sample.rsf_table, sample.rsf_library)


def profile_cells(sample, state):
    """``(header, rows)`` of the depth profile in the chosen mode, laid out
    like ``resultspages.profile_cells`` (level, the axis when it is not the
    level, one column per series)."""
    label, xs = resultspages.profile_axis(sample)
    series = profile(sample, state)["series"]
    header = ["Level"] + ([label] if label != "Level" else []) \
        + [s["name"] for s in series]
    rows = []
    for i, lv in enumerate(sample.levels):
        row = [str(lv.level if lv.level is not None else i + 1)]
        if label != "Level":
            row.append(f"{xs[i]:g}")
        row += [resultspages._fmt(s["values"][i], ".1f") for s in series]
        rows.append(row)
    return header, rows


def csv_table(samples, state):
    """The quantification table of ``samples`` (``quant.csv_rows``, header
    first) with the user's ticks and transmission choice. Each sample's own
    RSF-fallback arguments are used, so samples are written one block at a
    time and the header appears once."""
    out = [list(quant.CSV_HEADER)]
    for s in samples:
        if not s.levels:
            continue
        groups = [{"sample": s.label, "level": lv.level,
                   "entries": lv.entries} for lv in s.levels]
        inc = [includes(s, li, state) for li in range(len(s.levels))]
        out += quant.csv_rows(groups, inc, state.transmission, s.rsf_table,
                              s.rsf_library)[1:]
    return out
