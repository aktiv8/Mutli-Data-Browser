r"""Importing a CasaXPS ASCII export ("Export All to ASCII") as an alternative,
literal source of a region's background/component/envelope curves, in place
of ``lineshapes``/``casafit``'s own reconstruction from the ``.vms`` comment
-- see ``casafit.CsvCurves`` for how a match plugs into ``casafit.curves()``.

Two export layouts, auto-detected from the first non-blank row
(:func:`detect_layout`): one block per spectrum stacked vertically
("columns"), or one row per data point with every spectrum's own columns
concatenated side by side ("rows"). Confirmed against real exports of the
same file (``D:\Temp\for claude files\PtCl2_new\PtCl2_casa_output_columns.csv``
/ ``PtCl2_casa_output_rows.csv``, 2026-09-28):

- "columns" carries K.E./raw Counts *and* B.E./CPS, plus each block's own
  photon energy (``Characteristic Energy eV``) and total dwell
  (``Acquisition Time s`` = dwell x n_scans, confirmed exact against the same
  real file's own ``Region.dwell_and_scans()``: Cl 2p's 0.5 s = 0.05 x 10,
  Survey's 0.1 s = 0.01 x 10).
- "rows" carries only B.E./CPS -- no photon energy, no dwell, no scan count
  anywhere. It can only ever supply CPS-scale curve *shape*; matching and
  raw-counts conversion both rely on the already-open host region's own
  data/dwell/scans, never anything from the CSV itself.
- A per-component data column in either layout already has the background
  *added in* (``component_col = background + that component's own curve``,
  confirmed: ``Envelope == Background + sum(component - Background)`` to high
  precision on the real file) -- :func:`parse` subtracts it back out, so
  ``CsvComponent.curve_cps`` here is peak-only, matching this codebase's own
  ``lineshapes.component_curve()`` convention.
- A block's own scan name ("Cl2p Scan") is the raw acquisition label, not
  this app's canonicalised ``Region.name`` ("Cl 2p"), and ``readers/vamas.py``
  never stores the raw label on ``Region`` at all -- so it is never used as a
  matching key (see :func:`match_to_regions`), only carried through as
  informational text.

Tk-free: no Tkinter, no matplotlib. Only ``casafit`` is imported (for
``CsvCurves``/``component_be``); numpy is imported lazily inside
:func:`match_to_regions` (parsing itself needs no numpy).
"""

from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass, field

import casafit

_CYCLE_RE = re.compile(r"^\s*Cycle\s+(\d+)\s*:\s*(.*?)\s*$", re.I)
_PREAMBLE_KEYS = ("name", "position", "fwhm", "area", "lineshape")


def _num(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_cycle_label(s, strip_suffix=None):
    """``(cycle, sample, scan_name)`` from ``'Cycle N:sample:scan[:suffix]'``,
    or ``(None, "", s)`` if it doesn't match. ``strip_suffix`` (e.g. ``"CPS"``)
    is removed first when present as a trailing ``:suffix``."""
    s = (s or "").strip().strip('"')
    if strip_suffix and s.lower().endswith(":" + strip_suffix.lower()):
        s = s[: -(len(strip_suffix) + 1)]
    m = _CYCLE_RE.match(s)
    if not m:
        return None, "", s
    sample, _, scan = m.group(2).partition(":")
    return int(m.group(1)), sample.strip(), scan.strip()


def _strip_bg_env(tail):
    """``(component_names, has_background, has_envelope)`` from a header
    tail (after K.E./Counts or B.E./CPS and the component columns), trimming
    blank padding first. Background always precedes Envelope when present."""
    tail = list(tail)
    while tail and not tail[-1].strip():
        tail.pop()
    has_env = bool(tail) and tail[-1].strip().lower() in (
        "envelope", "envelope cps")
    if has_env:
        tail.pop()
    has_bg = bool(tail) and tail[-1].strip().lower() in (
        "background", "background cps")
    if has_bg:
        tail.pop()
    return tail, has_bg, has_env


def _peak_only(raw_curve, bg_curve, has_bg):
    if not has_bg:
        return tuple(raw_curve)
    return tuple((v - b) if v is not None and b is not None else None
                 for v, b in zip(raw_curve, bg_curve))


@dataclass
class CsvComponent:
    name: str
    position_be: float | None
    fwhm: float | None
    area: float | None
    lineshape: str
    curve_cps: tuple             # peak-only (background already subtracted)


@dataclass
class CsvBlock:
    source: str
    block_index: int
    layout: str                  # "columns" | "rows"
    cycle: int | None
    sample: str
    scan_name: str
    hv: float | None             # columns layout only
    dwell_total: float | None    # columns layout only
    ke: tuple | None             # columns layout only, ascending
    counts: tuple | None         # columns layout only
    be: tuple                    # always present
    cps: tuple                   # always present
    background_cps: tuple | None
    envelope_cps: tuple | None
    components: list = field(default_factory=list)     # [CsvComponent]


@dataclass
class CsvImport:
    path: str
    layout: str
    blocks: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def detect_layout(first_row):
    """``"columns"`` for a ``'Cycle N:...'`` block header, ``"rows"`` for the
    Name/Position/... preamble's own first row, else ``None``."""
    if not first_row:
        return None
    first = (first_row[0] or "").strip()
    if first.lower().startswith("cycle"):
        return "columns"
    if first.strip().lower() == "name":
        return "rows"
    return None


def parse(path):
    """Parse a CasaXPS "Export All to ASCII" CSV, auto-detecting its layout.
    Raises ``ValueError`` if neither layout is recognised."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise ValueError(f"{path}: empty file")
    layout = detect_layout(rows[0])
    if layout is None:
        raise ValueError(
            f"{path}: not a recognised CasaXPS ASCII export "
            "(Export All to ASCII)")
    source = os.path.basename(path)
    warnings = []
    blocks = (_parse_columns(rows, source, warnings) if layout == "columns"
              else _parse_rows(rows, source, warnings))
    return CsvImport(path=path, layout=layout, blocks=blocks,
                     warnings=warnings)


def _parse_columns(rows, source, warnings):
    blocks = []
    i, n = 0, len(rows)
    block_index = 0
    while i < n:
        row = rows[i]
        if not (row and row[0].strip().lower().startswith("cycle")):
            i += 1
            continue
        cycle, sample, scan_name = _parse_cycle_label(row[0])
        i += 1

        hv = dwell_total = None
        if i < n and len(rows[i]) >= 5:
            r = rows[i]
            if (r[1].strip().lower() == "characteristic energy ev"
                    and r[3].strip().lower() == "acquisition time s"):
                hv, dwell_total = _num(r[2]), _num(r[4])
                i += 1

        preamble = {}
        while (i < n and rows[i]
               and rows[i][0].strip().lower() in _PREAMBLE_KEYS):
            preamble[rows[i][0].strip().lower()] = rows[i][1:]
            i += 1

        if i >= n or not rows[i] or rows[i][0].strip().lower() != "k.e.":
            warnings.append(f"{source}: block '{scan_name}' has no data "
                            "header row, skipped")
            continue
        header = rows[i]
        i += 1

        be_idx = next((j for j, c in enumerate(header)
                       if c.strip().lower() == "b.e."), None)
        if be_idx is None:
            warnings.append(f"{source}: block '{scan_name}' header has no "
                            "B.E. column, skipped")
            continue

        names, has_bg, has_env = _strip_bg_env(header[be_idx + 2:])
        n_comp = len(names)
        preamble_names = [x for x in preamble.get("name", []) if x.strip()]
        if preamble_names and len(preamble_names) != n_comp:
            warnings.append(
                f"{source}: block '{scan_name}' preamble lists "
                f"{len(preamble_names)} components but the header has "
                f"{n_comp}; using the header count")

        def _column(key, default=None):
            vals = [_num(x) if default is None else x
                    for x in preamble.get(key, []) if x.strip()]
            return vals if vals else [default] * n_comp

        positions = _column("position")
        fwhms = _column("fwhm")
        areas = _column("area")
        lineshapes_ = [x for x in preamble.get("lineshape", []) if x.strip()] \
            or [""] * n_comp

        ke, counts, be, cps = [], [], [], []
        comp_cols = [[] for _ in range(n_comp)]
        bg_col, env_col = [], []
        cps_start = be_idx + 2
        while (i < n and rows[i]
               and not rows[i][0].strip().lower().startswith("cycle")):
            r = rows[i]
            i += 1
            if len(r) <= be_idx + 1:
                continue
            ke.append(_num(r[0])); counts.append(_num(r[1]))
            be.append(_num(r[be_idx])); cps.append(_num(r[be_idx + 1]))
            for k in range(n_comp):
                idx = cps_start + k
                comp_cols[k].append(_num(r[idx]) if len(r) > idx else None)
            if has_bg:
                idx = cps_start + n_comp
                bg_col.append(_num(r[idx]) if len(r) > idx else None)
            if has_env:
                idx = cps_start + n_comp + (1 if has_bg else 0)
                env_col.append(_num(r[idx]) if len(r) > idx else None)

        components = []
        for k in range(n_comp):
            components.append(CsvComponent(
                name=preamble_names[k] if k < len(preamble_names) else "",
                position_be=positions[k] if k < len(positions) else None,
                fwhm=fwhms[k] if k < len(fwhms) else None,
                area=areas[k] if k < len(areas) else None,
                lineshape=lineshapes_[k] if k < len(lineshapes_) else "",
                curve_cps=_peak_only(comp_cols[k], bg_col, has_bg)))

        blocks.append(CsvBlock(
            source=source, block_index=block_index, layout="columns",
            cycle=cycle, sample=sample, scan_name=scan_name,
            hv=hv, dwell_total=dwell_total,
            ke=tuple(ke), counts=tuple(counts), be=tuple(be), cps=tuple(cps),
            background_cps=tuple(bg_col) if has_bg else None,
            envelope_cps=tuple(env_col) if has_env else None,
            components=components))
        block_index += 1
    return blocks


def _parse_rows(rows, source, warnings):
    preamble = {}
    i, n = 0, len(rows)
    while i < n and rows[i] and rows[i][0].strip().lower() in _PREAMBLE_KEYS:
        preamble[rows[i][0].strip().lower()] = rows[i]
        i += 1
    if i >= n or not rows[i] or rows[i][0].strip().lower() != "b.e.":
        raise ValueError(f"{source}: no B.E. header row found")
    header = rows[i]
    i += 1

    starts = [j for j, c in enumerate(header) if c.strip().lower() == "b.e."]
    bounds = list(zip(starts, starts[1:] + [len(header)]))

    groups = []
    for start, end in bounds:
        seg = header[start:end]
        if len(seg) < 2:
            continue
        cycle, sample, scan_name = _parse_cycle_label(seg[1],
                                                       strip_suffix="CPS")
        names, has_bg, has_env = _strip_bg_env(seg[2:])
        n_comp = len(names)
        if ":" in "".join(names):     # rows layout prefixes names with the
            names = [nm.split(":", 1)[-1] for nm in names]   # scan label

        def _pre(key, n_comp=n_comp, start=start, end=end):
            vals = preamble.get(key, [])
            if len(vals) < end:
                return []
            return [x for x in vals[start:end][2:2 + n_comp] if x.strip()]

        preamble_names = _pre("name") or names
        positions = [_num(x) for x in _pre("position")] or [None] * n_comp
        fwhms = [_num(x) for x in _pre("fwhm")] or [None] * n_comp
        areas = [_num(x) for x in _pre("area")] or [None] * n_comp
        lineshapes_ = _pre("lineshape") or [""] * n_comp

        groups.append(dict(
            start=start, end=end, cycle=cycle, sample=sample,
            scan_name=scan_name, n_comp=n_comp, has_bg=has_bg,
            has_env=has_env, names=preamble_names, positions=positions,
            fwhms=fwhms, areas=areas, lineshapes=lineshapes_,
            be=[], cps=[], comp_cols=[[] for _ in range(n_comp)],
            bg=[], env=[]))

    while i < n:
        r = rows[i]
        i += 1
        for g in groups:
            start = g["start"]
            if start >= len(r) or not r[start].strip():
                continue                     # no point for this spectrum here
            g["be"].append(_num(r[start]))
            g["cps"].append(_num(r[start + 1]) if start + 1 < len(r) else None)
            base = start + 2
            for k in range(g["n_comp"]):
                idx = base + k
                g["comp_cols"][k].append(_num(r[idx]) if idx < len(r) else None)
            if g["has_bg"]:
                idx = base + g["n_comp"]
                g["bg"].append(_num(r[idx]) if idx < len(r) else None)
            if g["has_env"]:
                idx = base + g["n_comp"] + (1 if g["has_bg"] else 0)
                g["env"].append(_num(r[idx]) if idx < len(r) else None)

    blocks = []
    for gi, g in enumerate(groups):
        components = []
        for k in range(g["n_comp"]):
            components.append(CsvComponent(
                name=g["names"][k] if k < len(g["names"]) else "",
                position_be=g["positions"][k] if k < len(g["positions"])
                else None,
                fwhm=g["fwhms"][k] if k < len(g["fwhms"]) else None,
                area=g["areas"][k] if k < len(g["areas"]) else None,
                lineshape=g["lineshapes"][k] if k < len(g["lineshapes"])
                else "",
                curve_cps=_peak_only(g["comp_cols"][k], g["bg"], g["has_bg"])))
        blocks.append(CsvBlock(
            source=source, block_index=gi, layout="rows",
            cycle=g["cycle"], sample=g["sample"], scan_name=g["scan_name"],
            hv=None, dwell_total=None, ke=None, counts=None,
            be=tuple(g["be"]), cps=tuple(g["cps"]),
            background_cps=tuple(g["bg"]) if g["has_bg"] else None,
            envelope_cps=tuple(g["env"]) if g["has_env"] else None,
            components=components))
    return blocks


# -- matching -----------------------------------------------------------------
@dataclass
class MatchResult:
    block: CsvBlock
    region: object = None
    fit_region: object = None
    n_components_total: int = 0
    n_components_aligned: int = 0
    reason: str = ""
    csv_curves: object = None    # a built casafit.CsvCurves, ready to attach


@dataclass
class MatchReport:
    results: list = field(default_factory=list)
    unmatched_samples: list = field(default_factory=list)


def match_to_regions(blocks, regions):
    """Pure: match each :class:`CsvBlock` to a ``(region, FitRegion)`` among
    already-loaded ``regions`` (``readers.base.Region`` objects) and align
    its components, without mutating anything.

    Matching priority: (1) a columns-layout block's own raw K.E./Counts
    compared numerically against each same-sample candidate's own data --
    unambiguous even when two regions share name/energy-range (a repeated
    scan such as "Cl2p Scan"/"Cl2p Scan2"), since their raw data differs, or
    one of them isn't fitted at all; (2) failing that (or for a rows-layout
    block, which has no raw counts), the matched region's own BE range +
    point count. Either step reports (never guesses) when more than one
    candidate remains. Only regions that already carry a native CasaXPS fit
    are considered (an unfitted repeat scan is reported, not synthesized).
    Component alignment is by BE-position cost (nearest-first, greedy),
    all-or-nothing per region: if even one fitted component has no matching
    CSV column, that region is skipped and the missing one(s) are named."""
    import numpy as np

    report = MatchReport()
    unmatched = []
    by_sample = {}
    for r in regions:
        by_sample.setdefault((r.sample or "").strip().casefold(), []).append(r)

    for block in blocks:
        key = (block.sample or "").strip().casefold()
        candidates = by_sample.get(key, [])
        if not candidates:
            if block.sample not in unmatched:
                unmatched.append(block.sample)
            report.results.append(MatchResult(
                block=block,
                reason=f"sample '{block.sample}' is not open in any loaded "
                       "document"))
            continue

        region, fit_region = None, None

        if block.ke is not None and block.counts is not None:
            bke = [v for v in block.ke if v is not None]
            bcounts = [v for v in block.counts if v is not None]
            if bke and len(bke) == len(bcounts):
                bke_a, bcounts_a = np.asarray(bke), np.asarray(bcounts)
                hits = []
                for r in candidates:
                    if not r.counts or r.photon_energy is None:
                        continue
                    rke = r.photon_energy - np.asarray(r.energy, dtype=float)
                    rcounts = np.asarray(r.counts, dtype=float)
                    if len(rke) != len(bke_a):
                        continue
                    ro, bo = np.argsort(rke), np.argsort(bke_a)
                    if (np.allclose(rke[ro], bke_a[bo], atol=0.02) and
                            np.allclose(rcounts[ro], bcounts_a[bo],
                                       rtol=2e-3, atol=1.0)):
                        hits.append(r)
                if len(hits) == 1:
                    region = hits[0]
                elif len(hits) > 1:
                    report.results.append(MatchResult(block=block,
                        reason=f"ambiguous: {len(hits)} regions in sample "
                               f"'{block.sample}' have numerically "
                               "identical raw data"))
                    continue

        if region is None:
            b_be = [v for v in block.be if v is not None]
            if not b_be:
                report.results.append(MatchResult(block=block,
                    reason="no usable data in this CSV block"))
                continue
            b_lo, b_hi = min(b_be), max(b_be)
            hits = []
            for r in candidates:
                if not r.fit or r.photon_energy is None:
                    continue
                for fr in r.fit.regions:
                    r_lo = r.photon_energy - fr.end_ke
                    r_hi = r.photon_energy - fr.start_ke
                    if (abs(r_lo - b_lo) <= 0.3 and abs(r_hi - b_hi) <= 0.3
                            and abs(len(r.energy) - len(b_be)) <= 2):
                        hits.append((r, fr))
            if len(hits) == 1:
                region, fit_region = hits[0]
            elif not hits:
                report.results.append(MatchResult(block=block,
                    reason="no matching region found by BE range + point "
                           "count"))
                continue
            else:
                report.results.append(MatchResult(block=block,
                    reason=f"ambiguous: {len(hits)} candidates share this "
                           "BE range/point count (e.g. a repeated scan)"))
                continue

        if region.fit is None:
            report.results.append(MatchResult(block=block, region=region,
                reason="region has no CasaXPS fit to attach curves to"))
            continue

        if fit_region is None:
            frs = region.fit.regions
            if len(frs) == 1:
                fit_region = frs[0]
            else:
                b_be = [v for v in block.be if v is not None]
                b_lo, b_hi = min(b_be), max(b_be)
                hits = [fr for fr in frs
                        if abs((region.photon_energy - fr.end_ke) - b_lo) <= 0.3
                        and abs((region.photon_energy - fr.start_ke) - b_hi)
                        <= 0.3]
                if len(hits) == 1:
                    fit_region = hits[0]
                elif not hits:
                    report.results.append(MatchResult(block=block,
                        region=region,
                        reason=f"region has {len(frs)} separate CasaXPS fit "
                               "windows and none spans this CSV block's "
                               "own BE range (e.g. a Survey with several "
                               "narrow background windows)"))
                    continue
                else:
                    report.results.append(MatchResult(block=block,
                        region=region,
                        reason=f"ambiguous: {len(hits)} of the region's "
                               "own fit windows match this CSV block's BE "
                               "range"))
                    continue

        hv = region.photon_energy
        fit_comps = list(region.fit.region_components(fit_region))
        n_total = len(fit_comps)

        aligned = {}
        if fit_comps and hv is not None:
            pairs = []
            for fc in fit_comps:
                fbe = casafit.component_be(fc, hv, region.fit)
                for cc in block.components:
                    if cc.position_be is None:
                        continue
                    pairs.append((abs(fbe - cc.position_be), fc, cc))
            pairs.sort(key=lambda p: p[0])
            used_fc, used_cc = set(), set()
            for cost, fc, cc in pairs:
                if cost > 0.5:
                    break
                if id(fc) in used_fc or id(cc) in used_cc:
                    continue
                used_fc.add(id(fc)); used_cc.add(id(cc))
                aligned[id(fc)] = cc
        n_aligned = len(aligned)

        if n_total and n_aligned < n_total:
            missing = [fc.name for fc in fit_comps if id(fc) not in aligned]
            report.results.append(MatchResult(block=block, region=region,
                fit_region=fit_region, n_components_total=n_total,
                n_components_aligned=n_aligned,
                reason="not every fitted component matched a CSV column "
                       f"(missing: {', '.join(missing) or '?'})"))
            continue
        if n_total and hv is None:
            report.results.append(MatchResult(block=block, region=region,
                fit_region=fit_region, n_components_total=n_total,
                reason="no photon energy: components not position-matched"))
            continue

        if block.background_cps is None and n_total == 0:
            report.results.append(MatchResult(block=block, region=region,
                fit_region=fit_region,
                reason="CSV block has no background/envelope/components "
                       "to attach"))
            continue

        if block.ke is not None:
            ke_axis = block.ke
        elif hv is not None:
            ke_axis = tuple(hv - be if be is not None else None
                            for be in block.be)
        else:
            ke_axis = None
        if ke_axis is None or any(v is None for v in ke_axis):
            report.results.append(MatchResult(block=block, region=region,
                fit_region=fit_region, n_components_total=n_total,
                n_components_aligned=n_aligned,
                reason="could not build an energy axis for this block (no "
                       "photon energy available)"))
            continue

        csv_curves = casafit.CsvCurves(
            ke=ke_axis, background=block.background_cps,
            components=tuple((fc, aligned[id(fc)].curve_cps)
                             for fc in fit_comps if id(fc) in aligned),
            envelope=block.envelope_cps, source=block.source)
        report.results.append(MatchResult(block=block, region=region,
            fit_region=fit_region, n_components_total=n_total,
            n_components_aligned=n_aligned, csv_curves=csv_curves))

    report.unmatched_samples = unmatched
    return report


def apply_matches(report):
    """Mutate the matched ``FitRegion.csv_curves`` in place. All the matching
    logic already ran in :func:`match_to_regions`; this is the only function
    here that writes to already-open ``Region``/``FitRegion`` objects."""
    for res in report.results:
        if res.csv_curves is not None and res.fit_region is not None:
            res.fit_region.csv_curves = res.csv_curves


def summarise(report):
    """Human-readable text for a dialog: how many blocks matched, which
    samples/regions didn't and why, and the overall component-alignment
    count."""
    ok = sum(1 for r in report.results if r.csv_curves is not None)
    lines = [f"{ok} of {len(report.results)} CSV block(s) matched."]
    for s in report.unmatched_samples:
        lines.append(f"  sample '{s}' is not open in any loaded document")
    for r in report.results:
        if r.csv_curves is None and r.reason:
            label = f"{r.block.sample} / {r.block.scan_name}"
            lines.append(f"  {label}: {r.reason}")
    total_comp = sum(r.n_components_total for r in report.results)
    aligned_comp = sum(r.n_components_aligned for r in report.results)
    if total_comp:
        lines.append(f"{aligned_comp} of {total_comp} fitted components "
                     "aligned to a CSV column.")
    return "\n".join(lines)
