r"""KherveFitting ``.kfit`` project reader (github.com/KherveFitting/
KherveFitting) and, where present, its own fitted peak model.

A ``.kfit`` file is HDF5 (confirmed on 10 real sample files, ``D:\Temp\for
claude files\temp\KherveFitting Files\Data-Examples``, since no reader
source for the format is available anywhere -- the app is a PyInstaller
build and the one "source code" folder pointed at was empty): a
``core_levels`` group with one child group per acquired sheet (the sheet's
real name is the group's own ``name`` attribute, not the group's key, which
is an arbitrary ``cl_0``, ``cl_1``, ...), each holding ``B.E.`` / ``Raw
Data`` datasets and, when a background was configured, an already-computed
``Bkg Y`` curve and a ``Transmission`` array -- so **no background algorithm
needs reconstructing at all**, unlike a CasaXPS fit's background, which this
module's ``lineshapes.py`` has to compute from a type name.

A single ``project_json_gz`` dataset is zlib-compressed (its header is
``x\x9c``, not the gzip magic bytes the name suggests -- found by trial)
JSON carrying ``Core levels[<sheet name>]`` (``Fitting.Peaks``, the same
shape KherveFitting's standalone Peaks Library JSON files use, plus a
per-sheet ``Background`` dict with ``Bkg Type``/``Bkg Low``/``Bkg High``)
and per-sheet ``ExperimentalInfo`` (photon energy, pass energy, dwell,
scans, anode label, dates -- explicit numeric fields, not just vendor
strings to guess from).

**"Results TableN"** (one per sample row -- ``N`` matching the row a sheet's
own name suffix gives it, see "Sample rows" below -- of every fitted peak
*across all that row's sheets*, keyed by an arbitrary ``Peak_0``, ``Peak_1``,
...) is where KherveFitting keeps each peak's own RSF (also ``at. %``,
``wt. %``, ``TXFN``, ``ECF``, ``Instrument`` -- not read by this module: area
and at % are recomputed independently by ``quant.py`` from the RSF and the
reconstructed fit, the same as for a CasaXPS region, and no uncertainty
field exists in this table to read). Checked on all 10 sample files: **only
row 0's table is ever populated** (rows 1+ exist as empty ``{"Peak": {}}``
dicts even in multi-row files, e.g. STO_Tilt.kfit's 10 tables) and, more
importantly, **the table is frequently stale relative to the live fit** --
an earlier fit state (SP2 Carbon.kfit: 6 stale entries for a sheet whose
``Fitting.Peaks`` is now empty), a peak renamed since (Al2O3.kfit's
``Al2p3/2 Al2O3`` reads ``Al2p3/2 Al-O`` in its Results Table row, same
Position/Area/FWHM), or simply refit further since it was last computed
(STO.kfit's Ti2p: same Position, Area drifted 6%). A doublet's constrained
partner is also frequently left out of the table altogether -- quantified
once, on its independent peak (Y2O3_Kfitting.kfit's ``Y3d3/2`` components
have no row of their own). So a peak's RSF is cross-referenced by
Position/Area/FWHM agreement, not by name (``_rsf_of``, tolerances
``_RSF_POS_TOL``/``_RSF_AREA_REL_TOL``/``_RSF_FWHM_REL_TOL`` -- chosen
against the real corpus above to accept genuine same-peak drift and reject
staleness), and a peak with no confidently-matching row keeps ``rsf=0.0``,
the same honest "no RSF" ``quant.normalise`` already gives a CasaXPS region
without one.

**Sample rows.** KherveFitting can bundle several samples' repeats of one
sheet in a single file by appending the sample-row number directly to the
sheet's own name with no separator (row 0 has none): confirmed on real
files, ``Fe2p``/``Fe2p1``/``Fe2p2``, ``Survey``/``Survey1``/``Survey2``
(Fe2O3.kfit), ``C1s``..``C1s4`` (STO_Tilt.kfit). ``_split_sheet_name``
strips that suffix so the regions still group by core level; ``sample``
prefers the file's own ``SampleNames`` label for the row, else a generic
"Row N" when the file has more than one row.

**Peak shapes reconstructed** (checked against 88 real fitted peaks across
the 10 sample files): ``GL (Area)``, ``SGL (Area)`` and ``LA (Area, sigma,
gamma)`` map onto this module's own ``lineshapes.py`` shape strings
directly (``LA``'s own formula was ported from KherveFitting's in an
earlier milestone, and its own ``Sigma``/``Gamma`` columns were checked
point-for-point against KherveFitting's ``LA()`` source to get the branch
direction right -- ``Sigma`` is this module's own ``a``, ``Gamma`` its
``b``). ``Voigt (Area, L/G, sigma)`` is a true Voigt, reconstructed via
``lineshapes.py``'s new ``VOIGT(fraction)`` encoding (not a CasaXPS shape
string; see that module's docstring). Nothing else appeared in the real
sample set -- a peak with any other ``Fitting Model`` (skewed Voigt,
ExpGauss, Double Lorentzian, the Gelius/TLA shapes KherveFitting itself
also has) is imported with ``shape=""``, which ``lineshapes.parse_shape``
reads as an honestly-flagged placeholder, same as an unrecognised CasaXPS
shape.

**BEcorrection.** A project's file-wide ``BEcorrection`` and per-sample-row
``BEcorrections`` record a charge-referencing shift KherveFitting applied at
some point -- but, checked directly (no reader source exists to read
instead): **the shift is already baked into the stored ``B.E.``/Position
values, not layered on top of them the way a CasaXPS ``Calib`` line is**.
Confirmed two ways on real files: BaSO4.kfit's ``BEcorrection`` of 1.83 eV
sits beside a C1s ``C-C`` peak stored at exactly 284.8 eV, the standard
adventitious-carbon reference value a correction would be *aiming for*, not
a value still needing 1.83 eV added to reach it; and, decisively,
STO_Tilt.kfit's row 0 has a real, tested fit (``TestRealFiles``) with a
nonzero per-row correction (``BEcorrections["0"] = 0.2``) -- adding that
0.2 eV to every component's position, as a CasaXPS-style shift would need,
makes the reconstruction's residual 13-27x worse across every sample row of
that sheet (0.004-0.016 unshifted vs. 0.074-0.101 shifted). So this module
imports ``Position`` as-is and never touches ``Region.calibration_shift``
(which would double the correction on display, via ``Workspace._display``,
exactly the same real way this shift is proven not to belong a second
time) -- ``_becorrection_of`` only surfaces the value already applied as
read-only metadata (region_metadata's "BE calibration (KherveFitting)" row,
``Region.extra["kf_becorrection"]``), the file's own audit trail, not an
instruction to shift anything again.

**SampleAxis** is a project-wide, user-defined per-sample-row scale --
despite the name suggesting a depth or tilt series specifically, its own
``name`` field is free text a user sets ("Time" by default; STO_Tilt.kfit,
named for a tilt series, still has it as "Time"), so this module treats it
as an opaque labelled value rather than assuming it is depth or angle in
any particular unit. Checked on all 10 sample files: **not one has this
switched on with real values** -- STO_Tilt.kfit is the only file with a
``SampleAxis`` dict at all, and it is ``"enabled": 0`` with empty
``anchors``/``values``. So this module reads only the parts of the schema
that file's own empty example still shows (``enabled``, ``name``,
``format``/``decimals`` -- display hints only -- and ``values``, assumed
row-keyed the same string-digit way ``BEcorrections``/``SampleNames`` are
in the same file, since no populated example exists to confirm it) and
surfaces a row's own value as read-only metadata only
(``_sample_axis_value``, ``Region.extra["kf_sample_axis"]`` ->
region_metadata's "Sample axis (KherveFitting)" row) -- not into
``Region.etch_level``/``etch_time`` or any of this app's own depth-profile
machinery (``viewdata.py``, ``sputter.py``), which assumes a physical depth
or etch time this feature does not confirm it carries. ``anchors`` (unclear
meaning with no example to check) is not read at all. Revisit once a real
file with this switched on and populated is available to check the
``values`` keying and ``anchors``' purpose against.

``import_peak_library`` (D4) reads a standalone Peaks Library ``.json`` file
on its own -- the same ``Core levels[<name>].Fitting.Peaks`` shape as a
``.kfit`` project's own ``project_json_gz``, but with no ``B.E.``/``Raw
Data``/``ExperimentalInfo`` beside it (it is a fitting template, not a
recording). There being no spectrum to import, this is a distinct action
(Tools > "Import KherveFitting peak model...", not the ordinary Open dialog:
see ``Workspace.import_kfit_peak_library``): the region's "data" is the
model's own curve -- background none, its reconstructed components summed on
a synthetic axis spanning the peaks with margin -- at a nominal photon energy
(``xpslines.DEFAULT_HV``, Al Kalpha) needed only to carry the library's BE
positions into ``casafit``'s raw-KE frame; nothing about a real instrument or
acquisition is claimed, and the region says so in its own note.
"""

from __future__ import annotations

import io
import json
import os
import re
import zlib

import casafit
import lineshapes
import xpslines
from .base import Region, SpectrumFile, canon_region_name, is_survey_name, \
    read_bytes

_HDF5_SIG = b"\x89HDF\r\n\x1a\n"
_ELEM_LIKE_RE = re.compile(r"^[A-Z][a-z]?\d[spdf](\d/\d)?$")
_TRAILING_DIGITS_RE = re.compile(r"^(.*?)(\d+)$")


def sniff(head: bytes, ext: str) -> bool:
    return head[:8] == _HDF5_SIG


def _h5py():
    try:
        import h5py
        return h5py
    except ImportError:
        raise ValueError(
            "KherveFitting .kfit files need the h5py package (pip install "
            "h5py, or run: python launch.py --reinstall).")


def _looks_like_a_core_level(name):
    return is_survey_name(name) or bool(_ELEM_LIKE_RE.match(name))


def _split_sheet_name(name):
    """``(canonical core-level name, sample-row index)`` from a
    KherveFitting sheet name (see the module docstring)."""
    name = (name or "").strip()
    if _looks_like_a_core_level(name):
        return canon_region_name(name), 0
    m = _TRAILING_DIGITS_RE.match(name)
    if m and m.group(1) and _looks_like_a_core_level(m.group(1)):
        return canon_region_name(m.group(1)), int(m.group(2))
    return name, 0


def _num(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _becorrection_of(row, becorrections, file_level):
    """The BE correction KherveFitting already applied to sample row
    ``row``'s stored positions (see the module docstring's "BEcorrection"
    section), or None when nothing is recorded or it is zero. ``row``'s own
    entry of ``becorrections`` (``BEcorrections``, per row) wins when the
    file records one -- even a zero, over a nonzero file-wide
    ``BEcorrection`` (real case, Y2O3_Kfitting.kfit: file-wide 0.4 but row
    0's own entry is 0.0) -- since it is the more specific record; the
    file-wide value is a fallback for a file that only ever recorded that
    one (SP2 Carbon.kfit and Metal_Bi.kfit record neither)."""
    val = becorrections.get(row)
    if val is None:
        val = file_level
    return val if val else None


def _sample_axis_value(sample_axis, row):
    """``"<name>: <formatted value>"`` for sample row ``row``'s own entry of
    the project's ``SampleAxis`` (a user-defined per-row scale -- named
    "Time" by default, but the name is free text a user could set to
    "Depth (nm)" or "Tilt angle" for a depth or tilt series, hence this
    module's own name for the feature), or None when the file has none, it
    is switched off, or this row has no value of its own recorded -- see
    the module docstring's "SampleAxis" section: not one of the 10 real
    sample files has this switched on with real values (the one file that
    has the dict at all, STO_Tilt.kfit -- named for a tilt series -- has it
    disabled and empty), so only the parts of the schema directly observed
    (``enabled``/``name``/``decimals``/``values``, ``values`` assumed
    row-keyed the same string-digit way ``BEcorrections``/``SampleNames``
    are in the same file, since no populated example exists to confirm it)
    are read; ``anchors`` (unclear meaning with no example to check) is
    not."""
    if not isinstance(sample_axis, dict) or not sample_axis.get("enabled"):
        return None
    values = sample_axis.get("values")
    if not isinstance(values, dict):
        return None
    val = values.get(str(row))
    if val is None:
        return None
    name = str(sample_axis.get("name") or "").strip() or "Sample axis"
    num = _num(val)
    if num is None:
        text = str(val)
    else:
        nd = int(_num(sample_axis.get("decimals"), 2) or 2)
        text = f"{num:.{nd}f}"
    return f"{name}: {text}"


def _shape_string(peak):
    """A ``lineshapes.py`` shape string for one KherveFitting peak dict, or
    "" when the model is not one this module reconstructs (see the module
    docstring -- only the shapes seen in real fitted files are attempted)."""
    model = str(peak.get("Fitting Model") or "")
    lg = _num(peak.get("L/G"), 30.0)
    if model.startswith("GL"):
        return f"GL({lg:g})"
    if model.startswith("SGL"):
        return f"SGL({lg:g})"
    if model.startswith("Voigt"):
        return f"VOIGT({lg:g})"
    if model.startswith("LA"):
        a = _num(peak.get("Sigma"), 1.0)
        b = _num(peak.get("Gamma"), 1.0)
        return f"LA({a:g},{b:g},0)"
    return ""


# RSF cross-reference tolerances (see _rsf_of's docstring for how these were
# chosen against real files): a peak's Position/Area/FWHM in "Results
# TableN" must still agree this closely with its live Fitting.Peaks entry
# for the RSF to be trusted as still describing the same peak.
_RSF_POS_TOL = 0.03          # eV
_RSF_AREA_REL_TOL = 0.02     # 2% of the fitted area
_RSF_FWHM_REL_TOL = 0.05     # 5% of the fitted FWHM


def _rsf_of(pos, area, fwhm, candidates, used):
    """The RSF of whichever unused entry of ``candidates`` (one sheet's
    "Results TableN" peaks) matches (``pos``, ``area``, ``fwhm``) closely
    enough to trust, else 0.0 -- see the module docstring's "Results Table"
    section: matched by these numbers, not by name (a peak can be renamed
    after its RSF was last computed) and only within tolerance (the table
    is frequently stale -- an earlier fit state, sometimes emptied
    altogether -- and a doublet's constrained partner is often left out of
    it, quantified once on its independent peak). ``used`` (a set of
    ``candidates`` indices already claimed by an earlier component in this
    sheet) is updated in place so two fit peaks never claim the same row."""
    best_i, best_err = None, None
    for i, cand in enumerate(candidates):
        if i in used:
            continue
        cpos, carea = _num(cand.get("Position")), _num(cand.get("Area"))
        cfwhm, crsf = _num(cand.get("FWHM")), _num(cand.get("RSF"))
        if None in (cpos, carea, cfwhm, crsf):
            continue
        if abs(cpos - pos) > _RSF_POS_TOL:
            continue
        if area and abs(carea - area) / abs(area) > _RSF_AREA_REL_TOL:
            continue
        if fwhm and abs(cfwhm - fwhm) / abs(fwhm) > _RSF_FWHM_REL_TOL:
            continue
        err = abs(cpos - pos)
        if best_err is None or err < best_err:
            best_i, best_err = i, err
    if best_i is None:
        return 0.0
    used.add(best_i)
    return _num(candidates[best_i].get("RSF"), 0.0)


def _components_from_peaks(peaks, hv, k, region_name, results_row=None,
                           sheet_name=None):
    """``[FitComponent]`` from a ``Fitting.Peaks`` dict (shared by a
    ``.kfit`` sheet and a standalone Peaks Library file): ``k`` divides
    ``Area`` down from whatever raw scale it was stored in (1.0 -- no
    division -- for a Peaks Library file, which has no dwell/scans of its
    own to have been multiplied up by). ``results_row`` (a ``.kfit``
    project's own "Results TableN" for this sample row, or None -- a
    standalone Peaks Library file has no such table) supplies each
    component's RSF via :func:`_rsf_of`, restricted to the entries naming
    this ``sheet_name``."""
    candidates = [p for p in ((results_row or {}).get("Peak") or {}).values()
                 if isinstance(p, dict) and p.get("Sheetname") == sheet_name]
    used = set()
    components = []
    for pname, p in peaks.items():
        if not isinstance(p, dict):
            continue
        pos = _num(p.get("Position"))
        fwhm = _num(p.get("FWHM"))
        area = _num(p.get("Area"))
        if pos is None or fwhm is None or area is None:
            continue
        rsf = _rsf_of(pos, area, fwhm, candidates, used) if candidates else 0.0
        area = area / k
        # an unreconstructed model (e.g. a skewed Voigt) gets a fixed,
        # well-formed placeholder shape name lineshapes.py cannot parse
        # as GL/SGL, so is_exact() still honestly flags it -- same
        # convention as an unrecognised CasaXPS shape (H/F/QF; see
        # lineshapes.py's own docstring). The real model name is kept
        # in `line`, not folded into the shape string: KherveFitting's
        # own model names can carry parentheses of their own ("Voigt
        # (Area, L/G, sigma, S)"), which would corrupt lineshapes.py's
        # own NAME(params) parsing if embedded there directly.
        shape = _shape_string(p)
        components.append(casafit.FitComponent(
            name=str(pname), shape=shape or "KFUnknown(0)", area=area,
            fwhm=fwhm, pos_ke=hv - pos, rsf=rsf, region=region_name,
            line="" if shape else str(p.get("Fitting Model") or "")))
    return components


class KherveFittingKfitFile(SpectrumFile):
    format_name = "KherveFitting (.kfit)"

    def load(self, path: str):
        self.path = path
        h5py = _h5py()
        raw = read_bytes(path)
        with h5py.File(io.BytesIO(raw), "r") as f:
            if f.attrs.get("format") != "kfitting":
                raise ValueError(
                    f"{os.path.basename(path)} is an HDF5 file but not a "
                    "KherveFitting .kfit project (no 'kfitting' format tag)")
            cls_group = f.get("core_levels")
            if cls_group is None:
                raise ValueError(
                    f"{os.path.basename(path)} has no core_levels group")
            project = self._project_json(f)
            core_levels_json = (project or {}).get("Core levels") or {}
            sample_names = (project or {}).get("SampleNames") or {}
            results_tables = {}
            for key, val in (project or {}).items():
                m = re.match(r"^Results Table(\d+)$", key)
                if m and isinstance(val, dict):
                    results_tables[int(m.group(1))] = val
            becorrections = {}
            raw_bc = (project or {}).get("BEcorrections")
            if isinstance(raw_bc, dict):
                for k, v in raw_bc.items():
                    n = _num(v)
                    if n is not None:
                        try:
                            becorrections[int(k)] = n
                        except (TypeError, ValueError):
                            pass
            becorrection_file = _num((project or {}).get("BEcorrection"))
            sample_axis = (project or {}).get("SampleAxis")
            n_rows = len({r for _n, r in (
                _split_sheet_name(cls_group[k].attrs.get("name") or k)
                for k in cls_group.keys())})
            pending = []            # (Region, sheet_json) -- fit built after
                                    # every sheet's own hv is known
            for idx, key in enumerate(sorted(cls_group.keys())):
                grp = cls_group[key]
                raw_name = grp.attrs.get("name") or key
                built = self._load_sheet(grp, raw_name, idx,
                                         core_levels_json.get(raw_name) or {},
                                         sample_names, n_rows)
                if built:
                    pending.append(built)
            # XPS instruments essentially never change anode mid-session, so
            # a sheet with no ExperimentalInfo of its own (real files: seen
            # both ways -- some carry it on every sheet, some on none, some
            # only some) borrows the file's own session-wide value.
            session_hv = next((r.photon_energy for r, _j in pending
                               if r.photon_energy), None)
            if session_hv is None:
                self.warnings.append(
                    "No photon energy recorded anywhere in this file, so "
                    "no fitted peak model could be reconstructed (the raw "
                    "spectra still loaded).")
            for r, sheet_json in pending:
                if r.photon_energy is None:
                    r.photon_energy = session_hv
                grp = cls_group[r.extra.pop("_h5_key")]
                tx = grp.get("Transmission")
                if tx is not None and r.photon_energy:
                    r.tf_ke = [r.photon_energy - b for b in r.energy]
                    r.tf_values = [float(v) for v in tx[()]]
                row = r.extra.pop("_row")
                results_row = results_tables.get(row)
                bec = _becorrection_of(row, becorrections, becorrection_file)
                if bec:
                    r.extra["kf_becorrection"] = bec
                sax = _sample_axis_value(sample_axis, row)
                if sax:
                    r.extra["kf_sample_axis"] = sax
                r.fit = self._build_fit(grp, r, sheet_json, results_row)
                self.regions.append(r)
        self.instrument = {k: v for k, v in self.instrument.items() if v}
        return self._finish()

    @staticmethod
    def _project_json(f):
        """The decoded ``project_json_gz`` blob, or {} when it is missing or
        unreadable (the raw spectra still load without it)."""
        ds = f.get("project_json_gz")
        if ds is None:
            return {}
        try:
            raw = bytes(ds[()])
            return json.loads(zlib.decompress(raw).decode("utf-8"))
        except (OSError, ValueError, zlib.error, UnicodeDecodeError):
            return {}

    def _load_sheet(self, grp, raw_name, idx, sheet_json, sample_names,
                    n_rows):
        """A ``(Region, sheet_json)`` pair, or None for a degenerate/absent
        sheet. The region's fit is *not* built yet -- ``load()`` fills in a
        session-wide photon energy first (see there) and builds every
        sheet's fit in a second pass, once every sheet's own ``hv`` is
        settled."""
        be = grp.get("B.E.")
        counts = grp.get("Raw Data")
        if be is None or counts is None:
            return None
        energy = [float(v) for v in be[()]]
        vals = [float(v) for v in counts[()]]
        if len(energy) < 3 or len(energy) != len(vals):
            return None
        canon, row = _split_sheet_name(raw_name)
        info = sheet_json.get("ExperimentalInfo") or {}
        hv = _num(info.get("Source Energy"))
        sample = sample_names.get(str(row)) or (
            f"Row {row}" if n_rows > 1 else "")
        r = Region(
            name=canon, index=idx, offset=idx, technique="XPS",
            energy=energy, counts=vals, energy_label="Binding Energy",
            energy_units="eV", count_label="Intensity", count_units="counts",
            decodable=True, sample=sample, photon_energy=hv,
            pass_energy=_num(info.get("Pass Energy")),
            dwell=_num(info.get("Dwell Time")),
            step=_num(info.get("BE Step")), anode=info.get("Source Label", ""),
            date=str(info.get("Date Created") or ""))
        if info.get("Periods"):
            r.extra["n_scans"] = int(_num(info["Periods"], 1))
        wf = _num(info.get("Work Function"))
        if wf:
            self.instrument.setdefault("Work function (eV)", f"{wf:g}")
        r.extra["_h5_key"] = grp.name.rsplit("/", 1)[-1]
        r.extra["_row"] = row
        return r, sheet_json

    @staticmethod
    def _build_fit(grp, region, sheet_json, results_row=None):
        """A ``casafit.Fit`` for this sheet, or None when it has no peaks.
        ``results_row`` is this sample row's own "Results TableN" (see
        ``_components_from_peaks``/``_rsf_of``), or None."""
        fitting = sheet_json.get("Fitting") or {}
        peaks = fitting.get("Peaks") or {}
        if not peaks or not region.photon_energy:
            return None
        bkg = sheet_json.get("Background") or {}
        bkg_y = grp.get("Bkg Y")
        known_bg = [float(v) for v in bkg_y[()]] \
            if bkg_y is not None and len(bkg_y) == len(region.energy) else None
        bkg_type = str(bkg.get("Bkg Type") or "") or "Unknown"
        lo = _num(bkg.get("Bkg Low"))
        hi = _num(bkg.get("Bkg High"))
        if lo is None or hi is None:
            los = [p.get("Bkg Low") for p in peaks.values()
                  if _num(p.get("Bkg Low")) is not None]
            his = [p.get("Bkg High") for p in peaks.values()
                  if _num(p.get("Bkg High")) is not None]
            lo = _num(los[0]) if los else min(region.energy)
            hi = _num(his[0]) if his else max(region.energy)
        hv = region.photon_energy
        reg = casafit.FitRegion(
            name=region.name, background=bkg_type,
            start_ke=hv - hi, end_ke=hv - lo, rsf=0.0,
            known_background=tuple(known_bg) if known_bg else None)
        # KherveFitting's own Position/Height/Area/FWHM are counted over the
        # whole acquisition (the same raw-counts scale as "Raw Data"/"Bkg
        # Y"), not counts/s the way CasaXPS's own Area already is -- checked
        # against a real fit (Al2O3.kfit's O1s): dividing by dwell x scans
        # dropped the reconstruction's residual from 15.6% to 0.4%.
        dwell, scans = region.dwell_and_scans()
        k = (dwell * scans) if dwell else 1.0
        raw_name = grp.attrs.get("name") or grp.name.rsplit("/", 1)[-1]
        components = _components_from_peaks(peaks, hv, k, region.name,
                                            results_row, raw_name)
        if not components:
            return None
        return casafit.Fit(regions=[reg], components=components)


# -- D4: a standalone Peaks Library .json file, no spectrum ------------------

class KherveFittingPeakLibraryFile(SpectrumFile):
    """A standalone KherveFitting Peaks Library ``.json`` file: a fitting
    template someone else measured and fitted, not this file's own data (see
    the module docstring). Not registered in ``readers.READERS`` -- opened
    only through :func:`import_peak_library` (``Workspace.
    import_kfit_peak_library``, Tools menu), never the ordinary Open dialog,
    because there is no spectrum to plot it against."""

    format_name = "KherveFitting peak library (.json)"

    def load(self, path: str):
        self.path = path
        raw = read_bytes(path)
        try:
            project = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError(
                f"{os.path.basename(path)} is not a readable JSON file "
                f"({exc})")
        core_levels = project.get("Core levels") if isinstance(
            project, dict) else None
        if not core_levels:
            raise ValueError(
                f"{os.path.basename(path)} has no 'Core levels' -- not a "
                "KherveFitting peak library file")
        hv = xpslines.DEFAULT_HV
        for idx, raw_name in enumerate(sorted(core_levels)):
            region = self._load_region(raw_name, core_levels[raw_name],
                                       idx, hv)
            if region is not None:
                self.regions.append(region)
        if not self.regions:
            raise ValueError(
                f"{os.path.basename(path)} has no peak with a Position, "
                "FWHM and Area")
        self.warnings.append(
            f"{os.path.basename(path)} is a KherveFitting peak-model "
            "template, not a measured spectrum: each region's curve is the "
            f"model itself, at a nominal photon energy ({hv:g} eV, Al "
            "Kα) used only to carry its binding-energy positions into "
            "the raw-KE frame this app's fits work in.")
        return self._finish()

    @staticmethod
    def _load_region(raw_name, entry, idx, hv):
        """One ``Region`` synthesised from a ``Core levels[name]`` entry, or
        None when it has no peak with a usable Position/FWHM/Area."""
        fitting = entry.get("Fitting") if isinstance(entry, dict) else None
        peaks = {k: v for k, v in ((fitting or {}).get("Peaks") or {}).items()
                 if isinstance(v, dict)}
        valid = [p for p in peaks.values()
                if _num(p.get("Position")) is not None
                and _num(p.get("FWHM")) is not None
                and _num(p.get("Area")) is not None]
        if not valid:
            return None
        canon, _row = _split_sheet_name(raw_name)
        components = _components_from_peaks(peaks, hv, 1.0, canon)
        if not components:
            return None
        positions = [_num(p["Position"]) for p in valid]
        fwhms = [_num(p["FWHM"]) for p in valid]
        margin = max(3.0, 3.0 * max(fwhms))
        lo_be, hi_be = min(positions) - margin, max(positions) + margin
        n = max(200, min(4000, int((hi_be - lo_be) / 0.02)))

        import numpy as np
        ke = np.linspace(hv - hi_be, hv - lo_be, n)     # ascending KE
        be = hv - ke                                    # matching, descending
        total = np.zeros(n)
        for c in components:
            total += lineshapes.component_curve(ke, c.shape, c.pos_ke,
                                                 c.fwhm, c.area)

        region = Region(
            name=canon, index=idx, offset=idx, technique="XPS",
            energy=be.tolist(), counts=total.tolist(),
            energy_label="Binding Energy", energy_units="eV",
            count_label="Fit model", count_units="a.u.", decodable=True,
            sample="", photon_energy=hv,
            note="KherveFitting peak-library template -- not a measured "
                 "spectrum; the curve is the model's own components, not "
                 "acquired data.")
        reg = casafit.FitRegion(
            name=canon, background="None", start_ke=hv - hi_be,
            end_ke=hv - lo_be, rsf=0.0)
        region.fit = casafit.Fit(regions=[reg], components=components)
        return region


def import_peak_library(path: str) -> KherveFittingPeakLibraryFile:
    return KherveFittingPeakLibraryFile().load(path)
