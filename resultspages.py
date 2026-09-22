"""Quantification as report pages and slides (Tk-free; matplotlib only to draw
a chart).

What the pages say is what the desktop and the HTML browser say: atomic percent
from CasaXPS's own areas and sensitivity factors (``quant``), each sample at
each depth level normalised on its own. Nothing is fitted or guessed here.
:func:`collect` reads the loaded files into a :class:`Results`; the report and
the deck then lay out the same numbers (``composition_cells`` for a sample at
one level, ``profile_cells`` for a depth profile, ``profile_png`` for its
chart), so the PDF, the slides and the numbers on screen agree.

Rules for what counts, stated on the pages (``Results.method`` / ``notes``):

* the areas are the integral of data minus background over the fit region, in
  counts/s x eV, as CasaXPS reports them; the transmission function is not
  applied (it is not known whether CasaXPS applies it to every instrument);
* a region name that appears in more than one spectrum at the same position and
  depth is counted once (the dedicated scan, else the first), so the total is
  not inflated by a survey and its own high-resolution scan of the same line;
  an element counted from two of its lines (2p and 1s) is counted from both and
  the page says so;
* a region with no sensitivity factor or no area is listed and says why.
"""

from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass, field

import quant
import reportspec

METHOD = ("Atomic percent is each fitted region's area divided by its "
          "sensitivity factor (RSF), as a share of the sum over the regions "
          "of the same sample and depth level. Areas are the integral of the "
          "data minus the background over the fit region, in counts/s·eV, "
          "with the RSFs and fits recorded by CasaXPS; no transmission "
          "correction is applied.")

COMPOSITION_HEADER = ("Region", "Background", "RSF", "Area (counts/s·eV)",
                      "Area / RSF", "at %")
PROFILE_AXES = (("depth", "Depth (nm)"), ("etch", "Etch time (s)"),
                ("fluence", "Ion fluence (ions/cm²)"), ("level", "Level"))


@dataclass
class Level:
    """One sample at one depth level (``level`` None: not a depth profile)."""
    level: int | None
    etch: float | None = None
    depth: float | None = None
    fluence: float | None = None
    entries: list = field(default_factory=list)   # [{"spectrum", "row"}]
    include: list = field(default_factory=list)   # counts in the total?
    why: list = field(default_factory=list)       # reason it does not
    res: list = field(default_factory=list)       # quant.normalise output

    def group(self):
        """The dict ``quant.profile`` takes."""
        return {"level": self.level, "entries": self.entries}


@dataclass
class Sample:
    key: str
    label: str
    levels: list = field(default_factory=list)
    notes: list = field(default_factory=list)     # what a reader should know

    @property
    def is_profile(self):
        return len(self.levels) >= 2


@dataclass
class Results:
    samples: list = field(default_factory=list)
    method: str = METHOD

    def __bool__(self):
        return bool(self.samples)

    def children(self):
        """``[(sample key, label)]`` for the Report generator."""
        return [(s.key, s.label) for s in self.samples]

    def chosen(self, skip=()):
        return [s for s in self.samples if s.key not in skip]

    @staticmethod
    def notes_for(samples):
        """The notes of these samples, each said once."""
        return list(dict.fromkeys(n for s in samples for n in s.notes))


def _num(md, key):
    try:
        return float(str((md or {}).get(key, "")).strip())
    except ValueError:
        return None


def collect(docs, display=None, key_of=None):
    """Read the CasaXPS fits of the loaded files (``display`` maps a region to
    the copy that is drawn, with the user's names and binding-energy shift)."""
    key_of = key_of or reportspec.doc_key
    out = Results()
    by_sample, order = {}, []
    approx = set()
    for p in docs:
        for r in p.regions:
            if getattr(r, "fit", None) is None or not r.decodable:
                continue
            d = display(r) if display else r
            rows = quant.fit_rows(d)
            if not rows:
                continue
            k = (key_of(p), r.sample)
            if k not in by_sample:
                by_sample[k] = Sample(
                    f"{k[0]}/{k[1]}", d.sample or r.sample
                    or os.path.basename((p.path or "").rstrip("\\/"))
                    or "sample")
                order.append(k)
            sample = by_sample[k]
            lv = r.etch_level
            level = next((x for x in sample.levels if x.level == lv), None)
            if level is None:
                md = p.region_metadata(r)
                level = Level(lv, r.etch_time, _num(md, "Depth (nm)"),
                              _num(md, "Fluence (ions/cm²)"))
                sample.levels.append(level)
            for row in rows:
                level.entries.append({"spectrum": d.name, "row": row})
                if row["basis"] != "data" or row["approximate"]:
                    approx.add(sample.label)
    for k in order:
        sample = by_sample[k]
        sample.levels.sort(key=lambda x: (x.level is None, x.level or 0))
        for level in sample.levels:
            _settle(level, sample.label, sample.notes)
        sample.notes = list(dict.fromkeys(sample.notes))
        _element_note(sample)
        _source_note(sample)
        if sample.label in approx:
            sample.notes.append(
                "The background under some of the fits of "
                f"{sample.label} is not reproduced exactly, so their areas "
                "are approximate.")
        out.samples.append(sample)
    return out


def _same(a, b):
    """Two names alike apart from case and spaces ("C 1s" and "C1s")."""
    strip = lambda t: "".join(str(t).lower().split())        # noqa: E731
    return strip(a) == strip(b)


_LINE = re.compile(r"^([A-Z][a-z]?)\s*\d+\s*[spdf]")


def element_of(region):
    """The element of a core-level name ("Ti 2p" -> "Ti"), else ''."""
    m = _LINE.match(str(region).strip())
    return m.group(1) if m else ""


def _settle(level, label, notes):
    """Decide what counts at one level, then normalise it. A region name that
    is fitted in more than one spectrum counts once: the dedicated scan (the
    spectrum named after the region) if there is one, else the first."""
    entries = level.entries
    chosen = {}                                  # region -> index counted
    for i, e in enumerate(entries):
        name = e["row"]["region"]
        if name not in chosen or (_same(e["spectrum"], name) and not _same(
                entries[chosen[name]]["spectrum"], name)):
            chosen[name] = i
    level.include, level.why = [], []
    for i, e in enumerate(entries):
        name = e["row"]["region"]
        keep = chosen[name]
        level.include.append(i == keep)
        if i == keep:
            level.why.append("")
        else:
            src = entries[keep]["spectrum"]
            level.why.append("counted once")
            notes.append(f"{name} is fitted in more than one spectrum of "
                         f"{label}; only the fit in {src} is counted.")
    level.res = quant.normalise([e["row"] for e in entries], level.include)
    for res, why in zip(level.res, level.why):
        if why:
            res["why"] = why


def _element_note(sample):
    """One note when an element is counted from two of its lines (its 2p and
    its 1s, say): its share then includes both."""
    lines = {}
    for level in sample.levels:
        for e, inc in zip(level.entries, level.include):
            el = element_of(e["row"]["region"])
            if inc and el and e["row"]["region"] not in lines.setdefault(
                    el, []):
                lines[el].append(e["row"]["region"])
    for el, names in lines.items():
        if len(names) > 1:
            sample.notes.append(
                f"{el} is counted from more than one line ("
                + ", ".join(names) + "), so its share includes both.")


def _source_note(sample):
    """One note when a level's counted total mixes CasaXPS regions
    quantified from a survey scan with others from a dedicated
    high-resolution scan: the elements only available from the survey are
    named, since a survey's cruder background and coarser point spacing
    typically make its quantification less precise than a dedicated scan's."""
    survey_only = set()
    for level in sample.levels:
        survey_els, hr_els = set(), set()
        for e, inc in zip(level.entries, level.include):
            if not inc:
                continue
            el = element_of(e["row"]["region"])
            if not el:
                continue
            dest = survey_els if e["row"].get("source") == "survey" else hr_els
            dest.add(el)
        if hr_els:
            survey_only |= survey_els - hr_els
    if survey_only:
        names = sorted(survey_only)
        verb = "is" if len(names) == 1 else "are"
        sample.notes.append(
            f"{', '.join(names)} {verb} quantified only from a survey scan "
            f"of {sample.label}, not a dedicated high-resolution scan, so "
            "this total mixes quantification of different precision.")


# -- cells ----------------------------------------------------------------------------
def _fmt(v, spec):
    return "" if v is None else format(v, spec)


SURVEY_FOOTNOTE = ("† survey-scan quantification, not a dedicated "
                   "high-resolution scan.")


def has_survey_rows(level):
    """True if any region at this level was quantified from a survey scan
    (marked with "†" in ``composition_cells``; see ``SURVEY_FOOTNOTE``)."""
    return any(e["row"].get("source") == "survey" for e in level.entries)


def composition_cells(level):
    """``[(kind, [cells])]`` for one sample at one level: a "region" row
    (region, background, RSF, area, area / RSF, at %; the reason instead of
    the percent when it is left out) with a "state" row under it for each
    chemical state. A region quantified from a survey scan rather than a
    dedicated high-resolution scan is marked "†" (``SURVEY_FOOTNOTE``)."""
    rows = []
    for e, x in zip(level.entries, level.res):
        row = e["row"]
        pct = f"{x['at_pct']:.1f}" if x["at_pct"] is not None else x["why"]
        name = row["region"] + (" †" if row.get("source") == "survey"
                                else "")
        rows.append(("region", [name, row.get("background") or "",
                                _fmt(row.get("rsf"), ".4g"),
                                _fmt(row.get("area"), ".4g"),
                                _fmt(x["corrected"], ".4g"), pct]))
        states = (quant.states(row, x["at_pct"])
                  if x["at_pct"] is not None else [])
        if len(states) > 1:                 # one state says nothing more
            for st in states:
                rows.append(("state", ["    " + st["name"], "", "", "",
                                       f"{100 * st['frac']:.0f}% of region",
                                       f"{st['at_pct']:.1f}"]))
    return rows


def profile_axis(sample):
    """``(label, [x per level])``: depth if every level has a distinct one,
    else etch time, else fluence, else the level number."""
    for attr, label in PROFILE_AXES:
        vals = [getattr(lv, attr) for lv in sample.levels]
        if all(v is not None for v in vals) and len(set(vals)) > 1:
            return label, vals
    return "Level", list(range(1, len(sample.levels) + 1))


def profile_series(sample):
    """``quant.profile`` (atomic percent of each region) for a sample."""
    return quant.profile([lv.group() for lv in sample.levels], "element",
                         [lv.include for lv in sample.levels])


def profile_cells(sample):
    """``(header, rows)`` of the depth profile: level, the axis when it is not
    the level, then a column of atomic percent per region."""
    label, xs = profile_axis(sample)
    series = profile_series(sample)["series"]
    header = ["Level"] + ([label] if label != "Level" else []) \
        + [s["name"] for s in series]
    rows = []
    for i, lv in enumerate(sample.levels):
        row = [str(lv.level if lv.level is not None else i + 1)]
        if label != "Level":
            row.append(f"{xs[i]:g}")
        row += [_fmt(s["values"][i], ".1f") for s in series]
        rows.append(row)
    return header, rows


def profile_png(sample, size=(7.0, 3.4), dpi=200, accent=None):
    """The depth profile as a PNG (bytes), or None without matplotlib."""
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
    except ImportError:
        return None
    import themes
    label, xs = profile_axis(sample)
    series = profile_series(sample)["series"]
    if not series:
        return None
    fig = Figure(figsize=size, dpi=dpi)
    FigureCanvasAgg(fig)
    ax = fig.add_axes((0.09, 0.17, 0.72, 0.78))
    cycle = themes.PALETTES["Light"]["cycle"]
    for i, s in enumerate(series):
        pts = [(x, v) for x, v in zip(xs, s["values"]) if v is not None]
        if pts:
            ax.plot(*zip(*pts), marker="o", markersize=3.5, linewidth=1.4,
                    color=cycle[i % len(cycle)], label=s["name"])
    ax.set_xlabel(label, fontsize=9)
    ax.set_ylabel("Atomic %", fontsize=9)
    ax.set_ylim(bottom=0)
    ax.tick_params(labelsize=8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="y", linewidth=0.4, alpha=0.5)
    ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), frameon=False,
              fontsize=8)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi)
    return buf.getvalue()
