"""Writer: NeXus (HDF5, ``.nxs``) following the NXxps / NXmpes application
definitions (Tk-free).

``export_nexus`` writes one ``NXentry`` per spectrum (``definition`` = NXxps),
the way the FAIRmat ``pynxtools-xps`` converter lays out a file, straight from
``Region`` objects with h5py: no pynxtools is needed or imported. h5py is an
optional library (``HAVE_H5PY``); without it the export says so.

**Nothing is guessed.** Only what the file or the user's annotations record is
written; NXxps also asks for things instrument files rarely state (electron
detector, source type, collection-column scheme, energy resolution) and those
are left out, so a strict NXxps validation lists them as missing. Everything
else we hold travels in the entry's ``metadata`` note (the ``region_metadata``
dict as JSON), so no field is lost for lack of a NeXus name.

Binding-energy axes are written as they are: pass the display copies
(``Workspace._display``) to export the corrected axis; the shift is then in
``energy_referencing``. The CasaXPS fit, when there is one, becomes an NXfit
group per fit region (peaks, backgrounds, envelope, residual) built from the
same ``quant.fit_rows`` the report uses."""

from __future__ import annotations

import importlib.util
import json
import os
import re

import appinfo
import timing
import viewdata

HAVE_H5PY = importlib.util.find_spec("h5py") is not None

#: the NeXus definitions release the group and field names were checked
#: against (pynxtools 0.16.0's ``validate_nexus``); written to ``definition@version``
NXDL_VERSION = "v2026.01"

#: our analyser-mode words -> the NXxps ``energy_scan_mode`` values
SCAN_MODES = {"constant analyser energy": "fixed_analyzer_transmission",
              "constant retard ratio": "fixed_retarding_ratio"}

#: CasaXPS shape name (before the first "(") -> NXxps peak function name
PEAK_FUNCTIONS = {"GL": "Gaussian-Lorentzian Product",
                  "SGL": "Gaussian-Lorentzian Sum",
                  "LA": "Asymmetric Lorentzian",
                  "LF": "Asymmetric Finite",
                  "DS": "Doniach-Sunjic",
                  "VOIGT": "Voigt"}

_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _h5py():
    try:
        import h5py
    except ImportError:
        raise ValueError("Writing NeXus files needs the h5py package "
                         "(pip install h5py, or run: python launch.py "
                         "--reinstall).")
    return h5py


def number(value):
    """The leading number of a recorded value ('150 W', '4.5', 12) or None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = _NUM.match(str(value).strip())
    return float(m.group(0)) if m else None


def nx_name(text, fallback="spectrum"):
    """A name safe as an HDF5 / NeXus group name (letters, digits, '_')."""
    s = re.sub(r"\W+", "_", str(text or ""), flags=re.UNICODE).strip("_")
    return s or fallback


def unique(name, taken):
    """``name`` made different from everything in ``taken`` (then added)."""
    out, n = name, 2
    while out in taken:
        out, n = f"{name}_{n}", n + 1
    taken.add(out)
    return out


def peak_function(shape):
    """The NXxps function name for a CasaXPS shape string, or None when the
    shape has no counterpart there (``A(a,b,n)GL(m)``, ``TLA``, ``QF`` ...)."""
    return PEAK_FUNCTIONS.get(str(shape or "").split("(")[0].strip().upper())


def background_function(kind):
    """'Shirley' / 'Linear' / 'Tougaard' (any ``U ... Tougaard``) or None."""
    k = str(kind or "").strip().lower()
    if k.startswith("shirley"):
        return "Shirley"
    if k.startswith("linear"):
        return "Linear"
    if "tougaard" in k:
        return "Tougaard"
    return None


def start_time(r):
    """ISO 8601 start of the acquisition: with its zone when the reader knows
    it ('UTC' -> +00:00), otherwise the bare local time; '' when unknown."""
    when = timing.parse_ts(r.extra.get("t_start")) or timing.parse_ts(r.date)
    if when is None:
        return ""
    text = when.strftime("%Y-%m-%dT%H:%M:%S")
    return text + "+00:00" if str(r.extra.get("tz") or "").upper() == "UTC" \
        else text


def end_time(r):
    when = timing.parse_ts(r.extra.get("t_end"))
    if when is None:
        return ""
    text = when.strftime("%Y-%m-%dT%H:%M:%S")
    return text + "+00:00" if str(r.extra.get("tz") or "").upper() == "UTC" \
        else text


# -- small HDF5 helpers --------------------------------------------------------
def _group(parent, name, nx_class):
    g = parent.create_group(name)
    g.attrs["NX_class"] = nx_class
    return g


def _put(parent, name, value, units=None):
    """A dataset, skipped when ``value`` is None or empty text."""
    if value is None or (isinstance(value, str) and not value):
        return None
    ds = parent.create_dataset(name, data=value)
    if units:
        ds.attrs["units"] = units
    return ds


def _nxdata(parent, name, signal, axes=None, **arrays):
    """An NXdata holding ``arrays`` (name -> (values, units)); ``signal`` and
    ``axes`` name members of it."""
    g = _group(parent, name, "NXdata")
    for key, (vals, units) in arrays.items():
        _put(g, key, vals, units)
    g.attrs["signal"] = signal
    if axes:
        g.attrs["axes"] = axes
        for ax in ([axes] if isinstance(axes, str) else axes):
            g.attrs[f"{ax}_indices"] = 0
    return g


def _nan_list(values):
    import numpy as np
    return np.array([np.nan if v is None else v for v in values], float)


# -- one entry -------------------------------------------------------------------
def _write_entry(entry, r, md, exp_md, inst, fit_rows):
    import numpy as np
    inst = inst or {}
    binding = viewdata.is_binding(r)
    entry.attrs["NX_class"] = "NXentry"
    _put(entry, "definition", "NXxps").attrs["version"] = NXDL_VERSION
    _put(entry, "method", "XPS")
    _put(entry, "title", " ".join(x for x in (r.sample, r.name) if x))
    _put(entry, "start_time", start_time(r))
    _put(entry, "end_time", end_time(r))
    prog = _put(entry, "program_name", appinfo.NAME)
    prog.attrs["version"] = appinfo.VERSION
    if inst.get("Operator") or inst.get("Institution"):
        user = _group(entry, "user", "NXuser")
        _put(user, "name", inst.get("Operator"))
        _put(user, "affiliation", inst.get("Institution"))

    # --- instrument -------------------------------------------------------
    ins = _group(entry, "instrument", "NXinstrument")
    if inst.get("Instrument"):
        dev = _group(ins, "device_information", "NXfabrication")
        _put(dev, "model", inst["Instrument"])
    ana = _group(ins, "electronanalyzer", "NXelectronanalyzer")
    _put(ana, "work_function", number(inst.get("Work function (eV)")), "eV")
    col = _group(ana, "collectioncolumn", "NXcollectioncolumn")
    _put(col, "lens_mode", r.lens_mode)
    disp = _group(ana, "energydispersion", "NXenergydispersion")
    _put(disp, "pass_energy", r.pass_energy, "eV")
    mode = str(r.extra.get("analyser_mode") or "")
    _put(disp, "energy_scan_mode", next(
        (v for k, v in SCAN_MODES.items() if mode.lower().startswith(k)), None))
    _put(disp, "description", mode)
    dwell, scans = r.dwell_and_scans()
    _put(ana, "dwell_time", dwell, "s")
    _put(ana, "number_of_scans", int(scans) if r.extra.get("n_scans") else None)
    _put(ana, "energy_step", r.step, "eV")
    tf = r.transmission()
    if tf:
        ke = r.kinetic_energy
        _nxdata(ana, "transmission_function", "relative_intensity",
                ["kinetic_energy"],
                kinetic_energy=(np.asarray(ke, float), "eV"),
                relative_intensity=(np.asarray(tf, float), None))

    src = _group(ins, "source_probe", "NXsource")
    _put(src, "associated_beam", f"{entry.name}/instrument/beam_probe")
    _put(src, "probe", "x-ray" if r.photon_energy else None)
    _put(src, "name", r.anode)
    c = r.conditions or {}
    _put(src, "power", number(c.get("X-ray Power")), "W")
    _put(src, "voltage", (lambda v: None if v is None else v * 1000.0)(
        number(c.get("Anode voltage (kV)"))), "V")
    _put(src, "emission_current", number(c.get("Emission current (mA)")), "mA")
    beam = _group(ins, "beam_probe", "NXbeam")
    _put(beam, "incident_energy", r.photon_energy, "eV")
    _put(beam, "extent", number(c.get("X-ray spot (µm)")), "µm")

    # --- sample -------------------------------------------------------------
    smp = _group(entry, "sample", "NXsample")
    _put(smp, "name", r.sample)
    tilt = number(c.get("Sample tilt (°)"))
    if tilt is not None:
        tr = _group(smp, "transformations", "NXtransformations")
        _put(tr, "sample_normal_polar_angle_of_tilt", tilt, "degree")
    if r.pos_x is not None and r.pos_y is not None:
        _put(smp, "stage_position", np.array([r.pos_x, r.pos_y], float), "mm")
    if r.etch_level is not None:
        _put(smp, "etch_level", int(r.etch_level))
    _put(smp, "etch_time", r.etch_time, "s")

    # --- charge correction ----------------------------------------------------
    shift = r.shift_applied or r.calibration_shift
    if shift:
        cal = _group(entry, "energy_referencing", "NXcalibration")
        _put(cal, "applied", bool(r.shift_applied))
        _put(cal, "offset", float(shift), "eV")
        cc = r.extra.get("casa_calib") or {}
        _put(cal, "measured", number(cc.get("measured")), "eV")
        _put(cal, "assigned", number(cc.get("assigned")), "eV")

    # --- the spectrum -----------------------------------------------------------
    energy = np.asarray(r.energy, float)
    counts = np.asarray(r.counts, float)
    data = _nxdata(entry, "data", "data", "energy",
                   energy=(energy, r.energy_units or "eV"),
                   data=(counts, r.count_units or "counts"))
    data["energy"].attrs["type"] = "binding" if binding else "kinetic"
    data["data"].attrs["long_name"] = r.count_label or "Intensity"

    # --- fit ----------------------------------------------------------------------
    taken = set()
    for row in fit_rows:
        cur = row.get("curves")
        # NXfit needs a peak and the fitted sum: a region with only a
        # background (or one whose background is not reproduced) is no fit
        if row["components"] and cur and cur["env"] is not None:
            _write_fit(entry, r, row, energy, counts, taken)

    # --- everything else, verbatim ----------------------------------------------
    note = _group(entry, "metadata", "NXnote")
    doc = {"region": md or {}}
    if exp_md:
        doc["experiment"] = exp_md
    _put(note, "type", "application/json")
    _put(note, "description", "All the metadata SpectraDeck holds for this "
                              "spectrum (display strings).")
    _put(note, "data", np.bytes_(json.dumps(
        doc, ensure_ascii=False, indent=1, default=str).encode("utf-8")))
    if r.source:
        _put(note, "source_file", r.source)


def _write_fit(entry, r, row, energy, counts, taken):
    import numpy as np
    cur = row.get("curves")
    name = unique("fit_" + nx_name(row["region"], "region"), taken)
    fit = _group(entry, name, "NXfit")
    _put(fit, "label", row["region"])
    chi = row.get("chi2_red")
    if chi is not None:
        fm = _put(fit, "figure_of_merit", float(chi))
        fm.attrs["metric"] = "reduced chi-square (Poisson weighted)"
    if not cur:
        return
    i0 = cur["i0"]
    n = len(next(v for v in (cur["bg"], cur["env"]) + tuple(cur["comps"])
                 if v is not None))
    x = energy[i0:i0 + n]
    env = None if cur["env"] is None else _nan_list(cur["env"])
    arrays = {"input_independent": (x, "eV"),
              "input_dependent": (counts[i0:i0 + n], "counts")}
    if env is not None:
        arrays["fit_sum"] = (env, "counts")
        arrays["residual"] = (counts[i0:i0 + n] - env, "counts")
    _nxdata(fit, "data", "input_dependent", "input_independent", **arrays)

    taken_peaks = set()
    for k, (comp, vals) in enumerate(zip(row["components"], cur["comps"])):
        pk = _group(fit, unique(f"peak{k + 1}", taken_peaks), "NXpeak")
        _put(pk, "label", comp["name"])
        _put(pk, "total_area", float(comp["area"]), "counts/s eV")
        if comp.get("rsf"):
            _put(pk, "rsf", float(comp["rsf"]))
        if vals is not None:
            _nxdata(pk, "data", "intensity", "position",
                    position=(x, "eV"), intensity=(_nan_list(vals), "counts"))
        func = _group(pk, "function", "NXfit_function")
        _put(func, "function_type", peak_function(comp["shape"]))
        _put(func, "shape", comp["shape"])
        prm = _group(pk, "fit_parameters", "NXparameters")
        _put(prm, "position", float(comp["be"]), "eV")
        _put(prm, "width", float(comp["fwhm"]), "eV")
        _put(prm, "area", float(comp["area"]), "counts/s eV")
    bg = _group(fit, "background1", "NXpeak")      # NXfit's own class for it
    _put(bg, "label", row["background"])
    if cur["bg"] is not None:
        _nxdata(bg, "data", "intensity", "position",
                position=(x, "eV"), intensity=(_nan_list(cur["bg"]), "counts"))
    func = _group(bg, "function", "NXfit_function")
    _put(func, "function_type", background_function(row["background"]))
    _put(func, "shape", row["background"])


# -- the file ---------------------------------------------------------------------
def export_nexus(regions, path, metadata=None, experiment_metadata=None,
                 instrument=None, include_fits=True, prefer_csv=False):
    """Write the regions to ``path`` as one NeXus file, an ``NXentry`` per
    spectrum. ``metadata`` is one ``region_metadata`` dict per input region
    (as ``exporters.export_vamas`` takes), ``instrument`` the reader's
    ``instrument`` dict (operator, instrument, work function). Only decodable
    regions with counts are written; returns how many."""
    pairs = [(r, metadata[i] if metadata and i < len(metadata) else None)
             for i, r in enumerate(regions) if r.decodable and r.counts]
    if not pairs:
        raise ValueError("None of the selected regions contain decodable data.")
    h5py = _h5py()
    import datetime
    import quant
    tmp = f"{path}.part"
    names, taken = [], set()
    try:
        with h5py.File(tmp, "w") as f:
            for r, md in pairs:
                rows = []
                if include_fits and getattr(r, "fit", None) is not None:
                    rows = quant.fit_rows(r, curves=True, prefer_csv=prefer_csv)
                nm = unique(nx_name(" ".join(x for x in (r.sample, r.name)
                                             if x)), taken)
                names.append(nm)
                _write_entry(f.create_group(nm), r, md, experiment_metadata,
                             instrument, rows)
            f.attrs["default"] = names[0]
            f.attrs["creator"] = appinfo.NAME
            f.attrs["creator_version"] = appinfo.VERSION
            f.attrs["file_name"] = os.path.basename(path)
            f.attrs["file_time"] = datetime.datetime.now().astimezone() \
                .isoformat(timespec="seconds")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return len(pairs)
