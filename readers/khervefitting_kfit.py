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
strings to guess from). ``Results TableN`` (one per sample row, RSF/at %/
uncertainty) is not read by this module yet -- see the module docstring's
own note below; a region imports with no RSF, same honest "no RSF" handling
``quant.normalise`` already gives a CasaXPS region without one.

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

**Not attempted in this version** (deliberately, not an oversight): the
``Results TableN`` RSF/at %/uncertainty cross-reference, KherveFitting's own
``BEcorrection``/``BEcorrections`` charge-referencing values (a component's
``Position`` is imported as-is), and the depth/tilt ``SampleAxis``. Revisit
once this first version has been used on more real files.
"""

from __future__ import annotations

import io
import json
import os
import re
import zlib

import casafit
import lineshapes
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
                r.fit = self._build_fit(grp, r, sheet_json)
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
        return r, sheet_json

    @staticmethod
    def _build_fit(grp, region, sheet_json):
        """A ``casafit.Fit`` for this sheet, or None when it has no peaks."""
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
        components = []
        for pname, p in peaks.items():
            if not isinstance(p, dict):
                continue
            pos = _num(p.get("Position"))
            fwhm = _num(p.get("FWHM"))
            area = _num(p.get("Area"))
            if pos is None or fwhm is None or area is None:
                continue
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
                fwhm=fwhm, pos_ke=hv - pos, rsf=0.0, region=region.name,
                line="" if shape else str(p.get("Fitting Model") or "")))
        if not components:
            return None
        return casafit.Fit(regions=[reg], components=components)
