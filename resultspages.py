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
  the page says so -- unless one of the two is that element's known "standard"
  line (``_PREFERRED_LINE``, e.g. Pt 4f over Pt 4d), in which case only that
  one is counted and the page says so instead;
* a region with no sensitivity factor or no area is listed and says why; an
  optional reference-table fallback (``collect(..., rsf_table=)``, off by
  default -- ``quant.py``'s own "nothing is guessed" stance) can supply one
  when the file records none, and the page marks it as a substitute, never
  as though it were the file's own recorded value; when the fallback is off
  and it would have applied, a note points at the Report generator option
  instead of leaving "no RSF" looking like a dead end (``_rsf_hint_note``).
"""

from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass, field

import casaquant
import quant
import reportspec
import rsf as rsf_lib

METHOD = ("Atomic percent is each fitted region's area divided by its "
          "sensitivity factor (RSF), as a share of the sum over the regions "
          "of the same sample and depth level. Areas are the integral of the "
          "data minus the background over the fit region, in counts/s·eV, "
          "with the RSFs and fits recorded by CasaXPS; no transmission "
          "correction is applied.")

COMPOSITION_HEADER = ("Region", "Background", "RSF", "Area (counts/s·eV)",
                      "Area / RSF", "at %", "Fit RMS", "Reduced χ²")
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
    casaxps: object = None    # casaquant.SampleQuant: CasaXPS's own export,
                              # preferred over the levels above when present
                              # (see collect(); levels is then empty)
    rsf_table: list | None = None    # quant.normalise's RSF-fallback args,
    rsf_library: str = "scofield"    # carried so profile_series() can reuse
                                     # them when it re-normalises fresh

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


CASAXPS_NOTE = ("Quantification for this sample is CasaXPS's own exported "
               "result (Quant_survey.txt / Quant_regions.txt / "
               "Quant_Dparam.txt), not recomputed from an embedded fit.")


def collect(docs, display=None, key_of=None, casa_quant=None, ticked=None,
           rsf_table=None, rsf_library="scofield"):
    """Read the CasaXPS fits of the loaded files (``display`` maps a region to
    the copy that is drawn, with the user's names and binding-energy shift).

    ``rsf_table``/``rsf_library`` are ``quant.normalise``'s own RSF-fallback
    args (a list from ``rsf.load_rsf()``, off by default) -- carried onto
    each ``Sample`` so ``profile_series`` can reuse them later.

    ``casa_quant`` (a ``casaquant.CasaQuant``, see that module) is preferred
    over a fit for any sample it names: no fit-derived level is built for
    that sample at all, and its ``Sample.casaxps`` carries CasaXPS's own
    exported numbers instead (three independent flat tables -- see
    ``casaquant.py`` for why they are not nested one inside another). The
    match strips a "Sample Name: " prefix from the region's own sample
    identifier before comparing: a VAMAS file CasaXPS itself exported can
    carry that same cosmetic prefix in its SAMPLE IDENTIFIER field, while
    the quant text files never repeat it in the samples they list.

    ``ticked`` (a region predicate, e.g. ``lambda r: id(r) in app.checked``)
    restricts the report to what is ticked in the tree: a fit-derived region
    that fails it is skipped, and a ``casa_quant`` sample name is only kept
    when at least one ticked region's sample matches it. ``None`` (the
    default) reads every loaded region, ticked or not, as before."""
    key_of = key_of or reportspec.doc_key
    out = Results()
    by_sample, order = {}, []
    approx = set()
    casa_names = set(casa_quant.samples) if casa_quant else set()
    ticked_casa_names = casa_names if ticked is None else set()
    if casa_names and ticked is not None:
        for p in docs:
            for r in p.regions:
                if not ticked(r):
                    continue
                d = display(r) if display else r
                label = (d.sample or r.sample
                        or os.path.basename((p.path or "").rstrip("\\/"))
                        or "sample")
                name = casaquant.strip_sample_prefix(label)
                if name in casa_names:
                    ticked_casa_names.add(name)
    for p in docs:
        for r in p.regions:
            if ticked is not None and not ticked(r):
                continue
            if getattr(r, "fit", None) is None or not r.decodable:
                continue
            d = display(r) if display else r
            label = (d.sample or r.sample
                    or os.path.basename((p.path or "").rstrip("\\/"))
                    or "sample")
            if casaquant.strip_sample_prefix(label) in casa_names:
                continue                # CasaXPS's own export is preferred
            rows = quant.fit_rows(d)
            if not rows:
                continue
            k = (key_of(p), r.sample)
            if k not in by_sample:
                by_sample[k] = Sample(f"{k[0]}/{k[1]}", label,
                                      rsf_table=rsf_table,
                                      rsf_library=rsf_library)
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
            _prefer_lines(level, sample.label, sample.notes, rsf_table,
                         rsf_library)
        sample.notes = list(dict.fromkeys(sample.notes))
        _element_note(sample)
        _source_note(sample)
        _rsf_note(sample)
        _rsf_hint_note(sample)
        if sample.label in approx:
            sample.notes.append(
                "The background under some of the fits of "
                f"{sample.label} is not reproduced exactly, so their areas "
                "are approximate.")
        out.samples.append(sample)
    for name in sorted(casa_names):
        if name not in ticked_casa_names:
            continue
        sample = Sample(f"casaxps:{name}", name,
                        casaxps=casa_quant.samples[name],
                        notes=[CASAXPS_NOTE])
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


# The standard "workhorse" line for an element that has a real, commonly-
# fitted choice between more than one core level -- checked against the
# curated RSF library's own numbers (see rsf.py): the 4f/4d "heavy metal"
# block, where 4f is the accepted standard line even though 4d's RSF can be
# higher (Au: 4f 17.12 vs 4d 19.80, Scofield/Al -- the user's own example).
# Pd/Ag are deliberately NOT here: their libraries show 3d overwhelmingly
# dominant in real use (Ag 3d 18.04 vs 4d 1.55), so there is no genuine
# ambiguity to resolve for them. An element absent from this table is left
# to _element_note's existing "counted from both, with a note" handling.
_PREFERRED_LINE = {"Pt": "4f", "Au": "4f", "Ir": "4f", "Os": "4f", "Re": "4f",
                   "W": "4f", "Ta": "4f", "Hf": "4f", "Hg": "4f", "Tl": "4f",
                   "Pb": "4f", "Bi": "4f"}


def _prefer_lines(level, label, notes, rsf_table=None, rsf_library="scofield"):
    """After ``_settle``: when more than one of an element's distinct region
    names is still included and one of them is that element's known
    preferred line (``_PREFERRED_LINE``), the others are excluded (``why =
    "not the preferred line"``) and a note is added -- an element absent
    from the table, or whose preferred line was not itself fitted here, is
    left untouched (``_element_note`` still says both are counted). Re-runs
    ``quant.normalise`` the same way ``_settle`` does, this time with
    ``rsf_table``/``rsf_library`` (``quant.normalise``'s own RSF-fallback
    args, off by default) so the final numbers reflect both changes."""
    entries = level.entries
    by_element = {}                   # element -> {region name: entry index}
    for i, e in enumerate(entries):
        if not level.include[i]:
            continue
        region = e["row"]["region"]
        el = element_of(region)
        if el:
            by_element.setdefault(el, {})[region] = i
    for el, regions in by_element.items():
        preferred_orbital = _PREFERRED_LINE.get(el)
        if not preferred_orbital or len(regions) < 2:
            continue
        preferred_name = f"{el} {preferred_orbital}"
        if preferred_name not in regions:
            continue
        losers = sorted(name for name in regions if name != preferred_name)
        if not losers:
            continue
        for name in losers:
            level.include[regions[name]] = False
            level.why[regions[name]] = "not the preferred line"
        notes.append(
            f"{el} is fitted from more than one line ({preferred_name}, "
            + ", ".join(losers) + f") in {label}; only {preferred_name}, "
            "the standard line for quantification, is counted.")
    level.res = quant.normalise([e["row"] for e in entries], level.include,
                                rsf_table=rsf_table, rsf_library=rsf_library)
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


def _rsf_note(sample):
    """One note per region whose atomic percent used a reference-table
    substitute RSF (``quant.normalise``'s ``rsf_source`` -- "component" is
    not noted here, since that is the file's own cross-referenced data, just
    read from a different place, not a substitute). When the substitute is
    one of the IMFP-corrected Scofield tiers (``x["imfp_nm"]``/
    ``x["ke_power_factor"]`` set), the note also says what kinetic-energy
    factor was used, so a reader sees exactly what was assumed, not just a
    combined number."""
    seen = set()
    for level in sample.levels:
        for e, x in zip(level.entries, level.res):
            src = x.get("rsf_source")
            if not src or src == "component":
                continue
            region = e["row"]["region"]
            if region in seen:
                continue
            seen.add(region)
            lib_label = rsf_lib.LIBRARY_SHORT.get(src, src)
            extra = ""
            if x.get("imfp_nm"):
                extra = (f", scaled by a TPP-2M mean free path of "
                        f"{x['imfp_nm']:.3g} nm at that line's own "
                        "kinetic energy")
            elif x.get("ke_power_factor"):
                extra = (", scaled by (kinetic energy)^0.6 -- Thermo "
                        "Avantage's own convention")
            sample.notes.append(
                f"{region}'s sensitivity factor is not recorded in "
                f"{sample.label}; the {lib_label} library's value "
                f"({x['rsf_value']:g}, {x['rsf_anode']} Kα) is used "
                f"instead{extra}.")


def _rsf_hint_note(sample):
    """One note when the RSF reference-table fallback was off (``sample.
    rsf_table`` falsy) and at least one region was left out purely for lack
    of a recorded RSF -- points at the option that might resolve it, so "no
    RSF" in the table doesn't read as a dead end. Never fires when the
    fallback was on (that region simply has no entry in the library either
    -- turning it on again would not help, so no further hint is useful)."""
    if sample.rsf_table:
        return
    if any(x.get("why") == "no RSF"
          for level in sample.levels for x in level.res):
        sample.notes.append(
            f"{sample.label} has a region with no recorded sensitivity "
            "factor, left out of the total. The Report generator's RSF "
            "fallback option (Scofield or Kratos Axis F1s) may be able to "
            "supply one.")


# -- cells ----------------------------------------------------------------------------
def _fmt(v, spec):
    return "" if v is None else format(v, spec)


SURVEY_FOOTNOTE = ("† survey-scan quantification, not a dedicated "
                   "high-resolution scan.")


def has_survey_rows(level):
    """True if any region at this level was quantified from a survey scan
    (marked with "†" in ``composition_cells``; see ``SURVEY_FOOTNOTE``)."""
    return any(e["row"].get("source") == "survey" for e in level.entries)


def _fmt_rms(v):
    """Residual RMS (a fraction of the region's data range) as a percentage,
    or "" when there is no envelope to compare against (a component-less
    survey region, or one whose background is not reproduced)."""
    return "" if v is None else f"{100 * v:.1f}%"


def _fmt_chi2(v):
    """Poisson-weighted reduced chi-square, or "" when it could not be
    computed (no envelope, or dwell/scans -- and so true counts -- unknown)."""
    return "" if v is None else f"{v:.2f}"


def _fmt_rsf(row, x):
    """The RSF cell: the row's own recorded value normally, or, when
    ``quant.normalise``'s reference-table fallback supplied a substitute
    (``rsf_source`` is the library name, not "component"), that value
    labelled with its library and anode so it never reads like a real
    recorded RSF -- e.g. "15.45 (Scofield, Al Kα)"."""
    src = x.get("rsf_source")
    if src and src != "component":
        label = rsf_lib.LIBRARY_SHORT.get(src, src)
        return f"{x['rsf_value']:.4g} ({label}, {x['rsf_anode']} Kα)"
    return _fmt(row.get("rsf"), ".4g")


def composition_cells(level):
    """``[(kind, [cells])]`` for one sample at one level: a "region" row
    (region, background, RSF, area, area / RSF, at %, fit RMS, reduced
    chi-square; the reason instead of the percent when it is left out) with
    a "state" row under it for each chemical state. A region quantified from
    a survey scan rather than a dedicated high-resolution scan is marked "†"
    (``SURVEY_FOOTNOTE``). Fit RMS is the residual between the data and the
    fitted envelope as a percentage of the region's data range; reduced
    chi-square is the same residual weighted by Poisson counting statistics
    (data - envelope)^2 / max(data, 1), summed over the region's points and
    divided by points - 1 -- the standard XPS goodness-of-fit figure, and
    comparable across regions in a way the RMS fraction is not. Both are
    blank where there is no envelope (a component-less survey region, or an
    unreproduced background); chi-square is also blank when dwell/scans are
    unknown, since there are then no true counts to weight by. The RSF cell
    shows a substitute's own value and provenance (e.g. "15.45 (Scofield,
    Al Kα)") in place of the row's own (blank/zero) recorded RSF when
    ``quant.normalise``'s reference-table fallback supplied one -- see
    ``_fmt_rsf``; a component-level fallback (the file's own data, just
    summed a different way) leaves the cell as the plain, unlabelled area
    ratio, matching the file's own honest style."""
    rows = []
    for e, x in zip(level.entries, level.res):
        row = e["row"]
        pct = f"{x['at_pct']:.1f}" if x["at_pct"] is not None else x["why"]
        name = row["region"] + (" †" if row.get("source") == "survey"
                                else "")
        rows.append(("region", [name, row.get("background") or "",
                                _fmt_rsf(row, x),
                                _fmt(row.get("area"), ".4g"),
                                _fmt(x["corrected"], ".4g"), pct,
                                _fmt_rms(row.get("rms")),
                                _fmt_chi2(row.get("chi2_red"))]))
        states = (quant.states(row, x["at_pct"])
                  if x["at_pct"] is not None else [])
        if len(states) > 1:                 # one state says nothing more
            for st in states:
                rows.append(("state", ["    " + st["name"], "", "", "",
                                       f"{100 * st['frac']:.0f}% of region",
                                       f"{st['at_pct']:.1f}", "", ""]))
    return rows


def composition_png(level, size=(7.0, 3.0), dpi=200):
    """The composition of one sample at one level as a bar chart (PNG bytes),
    or None without matplotlib: one bar per region with a usable at %, in the
    same order as ``composition_cells``. Chemical states are not broken out
    (the table already does that); a survey-derived region keeps its "†"."""
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
    except ImportError:
        return None
    import themes
    names, values, survey = [], [], []
    for e, x in zip(level.entries, level.res):
        if x["at_pct"] is None:
            continue
        row = e["row"]
        names.append(row["region"]
                     + (" †" if row.get("source") == "survey" else ""))
        values.append(x["at_pct"])
        survey.append(row.get("source") == "survey")
    if not names:
        return None
    fig = Figure(figsize=size, dpi=dpi)
    FigureCanvasAgg(fig)
    ax = fig.add_axes((0.09, 0.22, 0.88, 0.72))
    cycle = themes.PALETTES["Light"]["cycle"]
    bars = ax.bar(names, values,
                  color=[cycle[i % len(cycle)] for i in range(len(names))])
    for bar, is_survey in zip(bars, survey):
        if is_survey:
            bar.set_alpha(0.55)
            bar.set_hatch("//")
    ax.set_ylabel("Atomic %", fontsize=9)
    ax.set_ylim(bottom=0)
    ax.tick_params(labelsize=8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="y", linewidth=0.4, alpha=0.5)
    for i, v in enumerate(values):
        ax.text(i, v, f"{v:.1f}", ha="center", va="bottom", fontsize=7)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi)
    return buf.getvalue()


def profile_axis(sample):
    """``(label, [x per level])``: depth if every level has a distinct one,
    else etch time, else fluence, else the level number."""
    for attr, label in PROFILE_AXES:
        vals = [getattr(lv, attr) for lv in sample.levels]
        if all(v is not None for v in vals) and len(set(vals)) > 1:
            return label, vals
    return "Level", list(range(1, len(sample.levels) + 1))


def profile_series(sample):
    """``quant.profile`` (atomic percent of each region) for a sample, with
    the same RSF fallback (if any) ``collect()`` used for it."""
    return quant.profile([lv.group() for lv in sample.levels], "element",
                         [lv.include for lv in sample.levels],
                         rsf_table=sample.rsf_table,
                         rsf_library=sample.rsf_library)


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
