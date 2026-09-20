"""User edits kept *beside* the data: display names, notes, edited metadata,
binding-energy shifts, peak markers and the calibration statement.

The readers' output is never modified. The app applies these annotations when
it draws, exports and reports, and stores them in the workbook, so they
survive reloading the (unchanged) instrument files. Keys use the workbook's
file id (``f1``...) plus the sample and region names as read from the file:

* sample key  ``"<fid>|<sample>"``
* region key  ``"<fid>|<sample>|<region name>"`` (all levels of that region)
* metadata key ``"<fid>|<position in parser.regions>"`` (one spectrum)

Tk-free and JSON-serialisable.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

import sputter as sputter_mod

VERSION = 1


def sample_key(fid, sample):
    return f"{fid}|{sample}"


def region_key(fid, sample, name):
    return f"{fid}|{sample}|{name}"


def meta_key(fid, pos):
    return f"{fid}|{pos}"


def _clean_reels(d):
    """A valid REELS construction ``{elastic, p1, p2, gap, base, slope}``
    (gap, base and slope may be absent) or None."""
    import math
    if not isinstance(d, dict):
        return None
    try:
        out = {"elastic": float(d["elastic"]),
               "p1": [float(d["p1"][0]), float(d["p1"][1])],
               "p2": [float(d["p2"][0]), float(d["p2"][1])]}
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    for k in ("gap", "base", "slope"):
        try:
            v = float(d[k])
            out[k] = v if math.isfinite(v) else None
        except (KeyError, TypeError, ValueError):
            out[k] = None
    if not all(math.isfinite(v) for v in (out["elastic"], *out["p1"],
                                          *out["p2"])):
        return None
    return out


@dataclass
class Annotations:
    sample_names: dict = field(default_factory=dict)     # sample key -> name
    region_names: dict = field(default_factory=dict)     # region key -> name
    sample_notes: dict = field(default_factory=dict)     # sample key -> text
    region_notes: dict = field(default_factory=dict)     # region key -> text
    md_edits: dict = field(default_factory=dict)         # meta key -> {k: v}
    shifts: dict = field(default_factory=dict)           # scope key -> eV
    calibration: list = field(default_factory=list)      # log of calibrations
    calibration_statement: str = ""                      # optional override
    markers: dict = field(default_factory=dict)          # region key -> [...]
    experiment_notes: str = ""
    sputter: dict = field(default_factory=dict)          # sample key -> settings
    reels: dict = field(default_factory=dict)            # region key -> band gap
    extra: dict = field(default_factory=dict)            # unknown keys kept

    # -- names -----------------------------------------------------------------
    def sample_label(self, fid, sample):
        return self.sample_names.get(sample_key(fid, sample)) or sample

    def region_label(self, fid, sample, name):
        return self.region_names.get(region_key(fid, sample, name)) or name

    def set_name(self, table, key, new, original):
        """Rename (or, with an empty / unchanged name, reset)."""
        new = (new or "").strip()
        d = getattr(self, table)
        if not new or new == original:
            d.pop(key, None)
        else:
            d[key] = new

    # -- notes -----------------------------------------------------------------
    def set_note(self, table, key, text):
        text = (text or "").strip()
        d = getattr(self, table)
        if text:
            d[key] = text
        else:
            d.pop(key, None)

    def notes_for(self, fid, sample, name):
        """Sample note and region note, joined for display."""
        parts = [self.sample_notes.get(sample_key(fid, sample), ""),
                 self.region_notes.get(region_key(fid, sample, name), "")]
        return " / ".join(p for p in parts if p)

    # -- metadata edits ---------------------------------------------------------
    def edited_keys(self, fid, pos):
        return set(self.md_edits.get(meta_key(fid, pos), {}))

    def set_meta(self, fid, pos, key, value):
        d = self.md_edits.setdefault(meta_key(fid, pos), {})
        d[key] = str(value)

    def reset_meta(self, fid, pos, key=None):
        k = meta_key(fid, pos)
        if key is None:
            self.md_edits.pop(k, None)
        elif k in self.md_edits:
            self.md_edits[k].pop(key, None)
            if not self.md_edits[k]:
                del self.md_edits[k]

    def apply_metadata(self, fid, pos, region, md):
        """``md`` (a region's metadata dict) with names, notes, the BE shift
        and any edits applied. Returns a new dict; key order is kept."""
        out = dict(md)
        if "Sample" in out:
            out["Sample"] = self.sample_label(fid, region.sample)
        if "Region" in out:
            out["Region"] = self.region_label(fid, region.sample, region.name)
        shift = self.shift_for(fid, region.sample, region.name,
                               getattr(region, "calibration_shift", 0.0))
        if shift:
            out["BE shift (eV)"] = f"{shift:+.3f}"
        if region.etch_level is not None:
            sset = self.sputter.get(sample_key(fid, region.sample))
            if sset:
                for k, v in sputter_mod.metadata_rows(
                        sset, region.etch_time).items():
                    out[k] = v
        rl = self.reels.get(region_key(fid, region.sample, region.name))
        if rl and rl.get("gap") is not None:
            out["REELS band gap (eV)"] = f"{rl['gap']:.2f}"
            out["REELS elastic peak (eV KE)"] = f"{rl['elastic']:.2f}"
        note = self.notes_for(fid, region.sample, region.name)
        if note:
            out["Notes"] = note
        for k, v in self.md_edits.get(meta_key(fid, pos), {}).items():
            out[k] = v
        return out

    # -- binding-energy shifts ---------------------------------------------------
    def shift_for(self, fid, sample, name, default=0.0):
        """The BE shift for a region: the most specific scope wins (region,
        then sample, then the whole file). ``default`` is returned when the
        user set none: pass the region's ``calibration_shift`` so the charge
        correction recorded in the file applies until the user's own
        calibration replaces it (``None`` tells the two cases apart)."""
        for key in (region_key(fid, sample, name), sample_key(fid, sample),
                    str(fid)):
            if key in self.shifts:
                return float(self.shifts[key])
        return default

    def set_shift(self, scope_key, shift, entry=None):
        if abs(shift) < 1e-12:
            self.shifts.pop(scope_key, None)
        else:
            self.shifts[scope_key] = float(shift)
        if entry:
            self.calibration.append(dict(entry, scope=scope_key,
                                         shift=float(shift)))

    # -- markers -----------------------------------------------------------------
    def markers_for(self, fid, sample, name):
        return list(self.markers.get(region_key(fid, sample, name), []))

    def add_marker(self, fid, sample, name, be, label, kin=False):
        """A peak marker. ``be`` is a binding energy, or with ``kin=True`` a
        kinetic energy (ISS peaks): it then does not move with an energy
        calibration."""
        lst = self.markers.setdefault(region_key(fid, sample, name), [])
        if not any(abs(m["be"] - be) < 1e-6 and m["label"] == label
                   for m in lst):
            m = {"be": float(be), "label": label}
            if kin:
                m["kin"] = True
            lst.append(m)

    # -- REELS band gaps (per spectrum) ---------------------------------------
    def reels_for(self, fid, sample, name):
        """The stored REELS construction of a spectrum, or None."""
        d = self.reels.get(region_key(fid, sample, name))
        return dict(d) if d else None

    def set_reels(self, fid, sample, name, data):
        key = region_key(fid, sample, name)
        clean = _clean_reels(data)
        if clean:
            self.reels[key] = clean
        else:
            self.reels.pop(key, None)

    def remove_marker(self, fid, sample, name, be, label):
        key = region_key(fid, sample, name)
        lst = [m for m in self.markers.get(key, [])
               if not (m["label"] == label and abs(m["be"] - be) < 1e-6)]
        if lst:
            self.markers[key] = lst
        else:
            self.markers.pop(key, None)

    def clear_markers(self, fid, sample, name):
        self.markers.pop(region_key(fid, sample, name), None)

    # -- sputter settings (per sample) ---------------------------------------------
    def sputter_for(self, fid, sample):
        """The sample's sputter settings (complete dict), or None."""
        s = self.sputter.get(sample_key(fid, sample))
        return sputter_mod.sanitise(s) if s else None

    def set_sputter(self, fid, sample, settings):
        key = sample_key(fid, sample)
        if settings is None or sputter_mod.is_empty(settings):
            self.sputter.pop(key, None)
        else:
            self.sputter[key] = sputter_mod.sanitise(settings)

    # -- state ---------------------------------------------------------------------
    def is_empty(self):
        return not (self.sample_names or self.region_names
                    or self.sample_notes or self.region_notes or self.md_edits
                    or self.shifts or self.calibration or self.markers
                    or self.calibration_statement or self.experiment_notes
                    or self.sputter or self.reels)

    def copy(self):
        return copy.deepcopy(self)

    def to_json(self):
        d = {"version": VERSION}
        for name in ("sample_names", "region_names", "sample_notes",
                     "region_notes", "md_edits", "shifts", "calibration",
                     "calibration_statement", "markers", "experiment_notes",
                     "sputter", "reels"):
            d[name] = copy.deepcopy(getattr(self, name))
        d.update(self.extra)
        return d

    @classmethod
    def from_json(cls, data):
        """Tolerant loader: wrong types are ignored, unknown keys kept."""
        a = cls()
        if not isinstance(data, dict):
            return a
        known = {"version", "sample_names", "region_names", "sample_notes",
                 "region_notes", "md_edits", "shifts", "calibration",
                 "calibration_statement", "markers", "experiment_notes",
                 "sputter", "reels"}
        for name in ("sample_names", "region_names", "sample_notes",
                     "region_notes"):
            v = data.get(name)
            if isinstance(v, dict):
                setattr(a, name, {str(k): str(x) for k, x in v.items()})
        v = data.get("md_edits")
        if isinstance(v, dict):
            a.md_edits = {str(k): {str(i): str(j) for i, j in e.items()}
                          for k, e in v.items() if isinstance(e, dict)}
        v = data.get("shifts")
        if isinstance(v, dict):
            for k, x in v.items():
                try:
                    a.shifts[str(k)] = float(x)
                except (TypeError, ValueError):
                    pass
        v = data.get("calibration")
        if isinstance(v, list):
            a.calibration = [e for e in v if isinstance(e, dict)]
        v = data.get("markers")
        if isinstance(v, dict):
            for k, lst in v.items():
                if not isinstance(lst, list):
                    continue
                good = []
                for m in lst:
                    try:
                        item = {"be": float(m["be"]), "label": str(m["label"])}
                        if m.get("kin") is True:
                            item["kin"] = True
                        good.append(item)
                    except (KeyError, TypeError, ValueError):
                        pass
                if good:
                    a.markers[str(k)] = good
        v = data.get("reels")
        if isinstance(v, dict):
            for k, x in v.items():
                clean = _clean_reels(x)
                if clean:
                    a.reels[str(k)] = clean
        v = data.get("sputter")
        if isinstance(v, dict):
            a.sputter = {str(k): sputter_mod.sanitise(x) for k, x in v.items()
                         if isinstance(x, dict)
                         and not sputter_mod.is_empty(x)}
        for name in ("calibration_statement", "experiment_notes"):
            if isinstance(data.get(name), str):
                setattr(a, name, data[name])
        a.extra = {k: v for k, v in data.items() if k not in known}
        return a
