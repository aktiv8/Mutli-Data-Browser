"""The methods paragraph of a report, written from what the files actually
record: instrument, source, pass energies (survey and high-resolution kept
apart), step sizes and dwell times, lens mode, neutraliser, sputtering, depth
profiles and the calibration statement.

Only recorded facts are stated; a setting a file does not hold is left out
rather than guessed. The user may replace the generated text with their own
(``effective``). Pure functions on the dicts of ``SpectrumFile.region_metadata``
— no Tk, no matplotlib.
"""

from __future__ import annotations

import re

import metasummary

DASH = "–"
SURVEY_SPAN = 250.0          # eV: a wider scan is a survey (see readers.base)
_YES = {"yes", "on", "used", "true", "enabled", "1"}
_NO = {"no", "off", "not used", "false", "disabled", "none", "0", "n/a"}


def _num(text):
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return None


def _num_text(x):
    return f"{x:.6g}"


def join_and(items):
    """'a', 'a and b', 'a, b and c'."""
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def values_text(values, unit="", max_list=3):
    """Distinct numbers as a phrase: '40 eV', '20 and 40 eV',
    '20 to 160 eV' (more than ``max_list`` values become a range). Returns
    (text, how_many_distinct); ('', 0) when there are no numbers."""
    nums = sorted({v for v in (_num(x) for x in values) if v is not None})
    if not nums:
        return "", 0
    u = f" {unit}" if unit else ""
    if len(nums) == 1:
        return f"{_num_text(nums[0])}{u}", 1
    if len(nums) <= max_list:
        return join_and([_num_text(n) for n in nums]) + u, len(nums)
    return f"{_num_text(nums[0])} to {_num_text(nums[-1])}{u}", len(nums)


def is_survey(md):
    """True for a survey / wide scan: named so, or spanning over 250 eV."""
    name = str(md.get("Region", "")).lower()
    if any(k in name for k in ("survey", "wide")):
        return True
    a, b = _num(md.get("BE start (eV)")), _num(md.get("BE end (eV)"))
    return a is not None and b is not None and abs(a - b) > SURVEY_SPAN


def _unique(rows, key):
    """Distinct non-empty values of a metadata field, in first-seen order."""
    return [v for v in dict.fromkeys(str(r.get(key, "") or "").strip()
                                     for r in rows) if v]


def _instrument_names(rows):
    names = [n for n in _unique(rows, "Instrument")
             if n.lower() not in ("(unknown)", "unknown")]
    return names


def _source_sentence(rows):
    """'Spectra were excited with Al Kα X-rays (hν = 1486.69 eV) ...'"""
    hv, n_hv = values_text([r.get("Photon energy (eV)") for r in rows], "eV")
    anodes = _unique(rows, "Anode") or _unique(rows, "X-ray source")
    power, _n = values_text([r.get("Source power (W)") for r in rows], "W")
    if not (hv or anodes):
        return ""
    what = join_and(anodes) + (" " if anodes else "") + "X-rays"
    s = f"Spectra were excited with {what}"
    if hv:
        s += (f" (photon energy {hv})" if n_hv == 1
              else f" (photon energies {hv})")
    if power:
        s += f" at a source power of {power}"
        volt = _unique(rows, "Anode voltage (kV)")
        emis = _unique(rows, "Emission current (mA)")
        if len(volt) <= 1 and len(emis) <= 1 and (volt or emis):
            s += " (" + join_and([f"{volt[0]} kV" if volt else "",
                                  f"{emis[0]} mA emission" if emis else ""]) + ")"
    s += "."
    spot = _unique(rows, "X-ray spot (µm)")
    if spot:
        s += f" The X-ray spot size was {join_and(spot)} µm."
    return s


def _settings(rows, plural_noun=""):
    """'a pass energy of 160 eV, a step size of 1 eV and a dwell time of
    0.1 s per point' for the rows given; '' if none is recorded."""
    parts = []
    for key, sing, plur, unit, tail in (
            ("Pass energy (eV)", "a pass energy", "pass energies", "eV", ""),
            ("Step (eV)", "a step size", "step sizes", "eV", ""),
            ("Dwell (s)", "a dwell time", "dwell times", "s", " per point")):
        text, n = values_text([r.get(key) for r in rows], unit)
        if text:
            parts.append(f"{sing if n == 1 else plur} of {text}{tail}")
    return join_and(parts)


def _analyser_paragraph(rows):
    survey = [r for r in rows if is_survey(r)]
    detail = [r for r in rows if not is_survey(r)]
    sentences = []
    if survey and detail:
        s = _settings(survey)
        if s:
            sentences.append(f"Survey spectra ({len(survey)}) were acquired "
                             f"with {s}.")
        names = metasummary.compact_labels(
            [str(r.get("Region", "")) for r in detail], limit=8)
        s = _settings(detail)
        if s:
            sentences.append(f"High-resolution spectra ({len(detail)}: "
                             f"{names}) used {s}.")
    else:
        kind = "Survey spectra" if survey else "Spectra"
        s = _settings(rows)
        if s:
            sentences.append(f"{kind} ({len(rows)}) were acquired with {s}.")
    lens = _unique(rows, "Lens mode")
    aper = _unique(rows, "Aperture")
    mode = _unique(rows, "Analyser mode")
    bits = []
    if lens:
        bits.append(f"lens mode {join_and(lens)}")
    if aper:
        bits.append(f"aperture {join_and(aper)}")
    if mode:
        bits.append(join_and([m[0].lower() + m[1:] for m in mode]) + " mode")
    if bits:
        sentences.append(f"The analyser used {join_and(bits)}.")
    sentences.append(_acquisition_sentence(rows))
    return " ".join(s for s in sentences if s)


def _acquisition_sentence(rows):
    """Scan or snapshot, and how many scans were accumulated."""
    parts = []
    modes = {}
    for r in rows:
        m = str(r.get("Acquisition mode", "") or "").strip()
        if m:
            modes[m] = modes.get(m, 0) + 1
    if modes:
        parts.append("Spectra were recorded in " + join_and(
            [f"{m.lower()} mode ({n})" for m, n in modes.items()]) + ".")
    text, n = values_text([r.get("Scans") for r in rows])
    if text:
        parts.append(f"Each spectrum accumulated {text} scan"
                     f"{'' if text == '1' else 's'}."
                     if n == 1 else
                     f"Spectra accumulated {text} scans, depending on the "
                     "region.")
    return " ".join(parts)


def timing_sentence(summary):
    """When the analysis ran and how long the instrument was in use, from a
    ``timing.Summary``; '' when the files record neither."""
    import timing
    if summary is None:
        return ""
    parts = []
    if summary.start and summary.end:
        z = f" {summary.tz}" if summary.tz else ""
        a, b = summary.start, summary.end
        if a.date() == b.date():
            parts.append(f"Data were acquired on {a:%Y-%m-%d} between "
                         f"{a:%H:%M} and {b:%H:%M}{z}.")
        else:
            parts.append(f"Data were acquired from {a:%Y-%m-%d %H:%M} to "
                         f"{b:%Y-%m-%d %H:%M}{z}.")
    if summary.active is not None and summary.net is not None \
            and not summary.n_without_net and not summary.n_without_run:
        parts.append(
            f"The instrument was in use for "
            f"{timing.fmt_duration(summary.active)}, of which "
            f"{timing.fmt_duration(summary.net)} was counting time.")
    elif summary.net is not None and not summary.n_without_net:
        parts.append(f"The total counting time was "
                     f"{timing.fmt_duration(summary.net)}.")
    elif summary.active is not None and not summary.n_without_run:
        parts.append(f"The instrument was in use for "
                     f"{timing.fmt_duration(summary.active)}.")
    return " ".join(parts)


def _flag(value):
    v = value.strip().lower()
    return True if v in _YES else (False if v in _NO else None)


def _state_sentence(rows, key, noun, used, unused):
    vals = _unique(rows, key)
    if not vals:
        return ""
    flags = {v: _flag(v) for v in vals}
    if len(vals) == 1:
        v = vals[0]
        if flags[v] is True:
            return used
        if flags[v] is False:
            return unused
        return f"{noun}: {v}."
    if all(f is True for f in flags.values()):
        return used
    return f"{noun}: {join_and(vals)}."


def _depth_sentence(rows):
    """Depth profiles: levels per sample and the etch times."""
    per = {}
    for r in rows:
        lvl = _num(r.get("Etch level"))
        if lvl is None:
            continue
        d = per.setdefault(str(r.get("Sample", "")), {"levels": set(),
                                                     "times": set()})
        d["levels"].add(int(lvl))
        t = _num(r.get("Etch time (s)"))
        if t is not None:
            d["times"].add(t)
    if not per:
        return ""
    counts = sorted({len(d["levels"]) for d in per.values()})
    times = sorted({t for d in per.values() for t in d["times"]})
    s = ("Depth profiling was performed by alternating sputter etching and "
         "spectrum acquisition: ")
    n_text = (f"{counts[0]}" if len(counts) == 1
              else f"{counts[0]}{DASH}{counts[-1]}")
    s += f"{n_text} levels per profile"
    if len(per) > 1:
        s += f" on {len(per)} samples"
    if times and times[-1] > 0:
        s += f", to a cumulative etch time of {_num_text(times[-1])} s"
    s += "."
    return (s + " " + _beam_sentence(rows)).strip()


def _beam_sentence(rows):
    """The ion beam of a depth profile, from the sputter settings the user
    entered (or the file stated): only what is known."""
    ions = _unique(rows, "Sputter ion")
    energy, _n = values_text([r.get("Sputter energy (eV)") for r in rows],
                             "eV")
    current = _unique(rows, "Sputter current")
    raster = _unique(rows, "Raster (mm)")
    rate = _unique(rows, "Etch rate")
    if not (ions or energy or current or raster or rate):
        return ""
    beam = " ".join(x for x in (energy, join_and(ions)) if x) or "ion"
    s = f"Etching used a {beam} beam"
    if current:
        s += f" at {join_and(current)}"
    if raster:
        s += f", rastered over {join_and(raster)} mm"
    if rate:
        s += f", with an etch rate of {join_and(rate)}"
    s += "."
    fl = [v for v in (_num(r.get("Fluence (ions/cm²)")) for r in rows)
          if v is not None]
    dp = [v for v in (_num(r.get("Depth (nm)")) for r in rows)
          if v is not None]
    tail = []
    if fl:
        tail.append(f"an ion fluence of {max(fl):.3g} ions/cm²")
    if dp:
        tail.append(f"a depth of {max(dp):.3g} nm")
    if tail:
        s += " The deepest level corresponds to " + join_and(tail) + "."
    return s


def _data_sentence(rows):
    samples = _unique(rows, "Sample")
    text = f"The data set comprises {len(rows)} spectra"
    if samples:
        shown = ", ".join(samples[:6]) + (
            f" and {len(samples) - 6} more" if len(samples) > 6 else "")
        text += (f" from {len(samples)} sample"
                 f"{'s' if len(samples) != 1 else ''} ({shown})")
    dates = metasummary.date_range([("", r) for r in rows], sep=f" {DASH} ")
    if dates:
        text += f", acquired {dates}"
    return text + "."


def generate(rows, calibration="", timing_summary=None):
    """The methods text for ``rows`` (region metadata dicts of every loaded
    file) plus the calibration statement, and, when ``timing_summary`` (a
    ``timing.Summary``) is given, when and for how long the data were acquired.
    Paragraphs are separated by blank lines. Returns '' when there is nothing
    to describe."""
    rows = [r for r in rows if r]
    if not rows:
        return ""
    paras = []
    inst = _instrument_names(rows)
    operator = _unique(rows, "Operator")
    intro = ("X-ray photoelectron spectroscopy (XPS) measurements were made "
             + (f"on a {join_and(inst)} spectrometer" if inst
                else "on the instrument recorded in the data files"))
    if operator:
        intro += f" (operator: {join_and(operator)})"
    paras.append(intro + ". " + _source_sentence(rows))
    ana = _analyser_paragraph(rows)
    if ana:
        paras.append(ana)
    extra = [s for s in (
        _state_sentence(rows, "Charge neutraliser", "Charge neutraliser",
                        "Charge neutralisation was used.",
                        "No charge neutralisation was used."),
        _state_sentence(rows, "Ion gun / sputtering", "Ion gun",
                        "The ion gun was used for sputtering.",
                        "No ion sputtering was used."),
        _depth_sentence(rows)) if s]
    if extra:
        paras.append(" ".join(extra))
    paras.append(" ".join(s for s in (_data_sentence(rows),
                                      timing_sentence(timing_summary)) if s))
    if calibration and calibration.strip():
        paras.append(calibration.strip())
    else:
        paras.append("Binding energies are not charge-corrected.")
    return "\n\n".join(p.strip() for p in paras if p.strip())


def effective(override, generated):
    """The user's own text when they wrote one, else the generated text."""
    return override.strip() if override and override.strip() else generated


def paragraphs(text):
    """Blank-line separated paragraphs (single newlines kept)."""
    return [b.strip("\n") for b in re.split(r"\n\s*\n", text or "")
            if b.strip()]
