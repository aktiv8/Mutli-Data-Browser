"""Common data model and base class shared by every file reader.

A reader subclasses :class:`SpectrumFile`, fills ``regions`` (plus optionally
``instrument``, ``images``, ``depth_profile``, ``_sample_pos``) in ``load()``
and calls :meth:`_finish`. The tree the GUI shows, the per-region metadata and
the sample positions then come for free from this base class.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional

import timing

UNSET = 1e36        # VAMAS uses 1e37 for "not specified"
# Facts about the job or the analyser that a reader may put in ``instrument``
# and that region_metadata passes on when they are there.
SESSION_KEYS = ("Institution", "Project", "Experiment", "Platter",
                "Experiment ID", "Sample description", "Work function (eV)",
                "Comments")


def read_bytes(path) -> bytes:
    """Whole file as bytes, with the handle closed straight away."""
    with open(path, "rb") as fh:
        return fh.read()


def unset(x) -> bool:
    return x is None or abs(x) >= UNSET


def clean(x):
    """A number, or None when it is the 'not specified' sentinel."""
    return None if unset(x) else x


_ELEM_RE = re.compile(r"^([A-Z][a-z]?)\s*(\d[spdf])(\d/\d)?$")
_SURVEY_RE = re.compile(r"^(xps\s+)?(survey|wide|sur)(\s+scan)?(\s*/\s*\d+)?$", re.I)
_JUNK = {"not specified", "none", "n/a", "unknown"}


def guess_region_name(name: str, energy) -> str:
    """A 'core level' name on a very wide axis is really a survey/wide scan
    (some instruments leave the default element in the region label)."""
    if energy and len(energy) > 1 and _ELEM_RE.match(name or ""):
        if abs(max(energy) - min(energy)) > 250:
            return "Survey"
    return name


def clean_text(s) -> str:
    s = (s or "").strip()
    return "" if s.lower() in _JUNK else s


CAE = "Constant analyser energy (CAE)"
CRR = "Constant retard ratio (CRR)"
_ANALYSER = {"fat": CAE, "cae": CAE, "frr": CRR, "crr": CRR}


def analyser_mode_name(text) -> str:
    """VAMAS / vendor analyser mode as words: FAT and CAE are the same fixed
    pass-energy mode, FRR and CRR the fixed retard ratio one; anything else
    (or "not specified") is returned as written, or "" when empty."""
    t = clean_text(text)
    return _ANALYSER.get(t.lower(), t)


def canon_region_name(s) -> str:
    """'C1s' / 'C 1s' -> 'C 1s'; 'Cu2p3/2' -> 'Cu 2p3/2'; others unchanged.
    Makes the same core level group together across file formats."""
    s = clean_text(s)
    if _SURVEY_RE.match(s):
        return "Survey"
    m = _ELEM_RE.match(s)
    if m:
        return f"{m.group(1)} {m.group(2)}{m.group(3) or ''}"
    return s


_KV_RE = re.compile(r"^\s*([A-Za-z][\w /()\.%\-]*?)\s*[:=]\s*(.*?)\s*$")


def kv_from_lines(lines) -> dict:
    """Mine ``Key: value`` / ``Key=value`` pairs from free-text comment lines.
    Keys are lower-cased. A line holding several fields separated by 3+
    spaces (Kratos/Casa style) is split first; the first occurrence wins."""
    out = {}
    for line in lines:
        line = line.strip()
        chunks = re.split(r"\s{3,}", line) if line.count(":") > 1 else [line]
        for ch in chunks:
            m = _KV_RE.match(ch)
            if m and m.group(2) != "":
                out.setdefault(m.group(1).strip().lower(), m.group(2).strip())
    return out


@dataclass
class Region:
    name: str
    index: int
    offset: int
    technique: str = "XPS"
    conditions: dict = field(default_factory=dict)
    energy: Optional[list] = None
    counts: Optional[list] = None
    energy_label: str = "Binding Energy"
    energy_units: str = "eV"
    count_label: str = "Intensity"
    count_units: str = "counts"
    decodable: bool = False
    note: str = ""
    sample: str = ""
    # acquisition metadata
    photon_energy: Optional[float] = None
    pass_energy: Optional[float] = None
    dwell: Optional[float] = None
    step: Optional[float] = None
    lens_mode: str = ""
    aperture: str = ""
    anode: str = ""
    tf_ke: Optional[list] = None       # transmission-function kinetic energies
    tf_values: Optional[list] = None   # transmission-function values
    etch_level: Optional[int] = None   # depth-profile level (0 = surface)
    etch_time: Optional[float] = None  # cumulative etch time (s) at this level
    pos_x: Optional[float] = None      # stage analysis position X (mm)
    pos_y: Optional[float] = None      # stage analysis position Y (mm)
    source: str = ""                   # basename of the file it came from
    date: str = ""                     # acquisition date/time (display string)
    extra: dict = field(default_factory=dict)   # reader-specific leftovers
    fit: object = None                 # casafit.Fit: a CasaXPS fit read from VAMAS
    calibration_shift: float = 0.0     # eV the file itself says to add to the
                                       # BE axis (CasaXPS charge correction);
                                       # applied on display, never to `energy`
    shift_applied: float = 0.0         # set on the display copy: eV already
                                       # added to `energy` and `photon_energy`

    @property
    def n_points(self) -> int:
        return len(self.counts) if self.counts else 0

    def dwell_and_scans(self):
        """(dwell per sweep, sweeps), so that their product is the time each
        point was counted for. Kratos ESCApe stores the dwell already summed
        over the sweeps (``extra["dwell_total"]``); VAMAS, CasaXPS and the
        curve scaling want it per sweep."""
        scans = int(self.extra.get("n_scans") or 1)
        if self.dwell and self.extra.get("dwell_total"):
            return self.dwell / scans, scans
        return self.dwell, scans

    @property
    def kinetic_energy(self):
        """Kinetic-energy axis (eV), or None if not decoded."""
        if self.photon_energy is None or not self.energy:
            return None
        return [self.photon_energy - be for be in self.energy]

    def transmission(self):
        """Per-point transmission function, linearly interpolated from the
        instrument's calibration pairs onto this spectrum's KE axis.
        Returns None if no transmission function is available."""
        if not self.tf_ke or not self.tf_values:
            return None
        ke = self.kinetic_energy
        if ke is None:
            return None
        xs, ys = self.tf_ke, self.tf_values
        out = []
        for x in ke:
            if x <= xs[0]:
                # linear extrapolation using the first segment
                if len(xs) > 1 and xs[1] != xs[0]:
                    f = (x - xs[0]) / (xs[1] - xs[0])
                    out.append(ys[0] + f * (ys[1] - ys[0]))
                else:
                    out.append(ys[0])
            elif x >= xs[-1]:
                # linear extrapolation using the last segment
                if len(xs) > 1 and xs[-1] != xs[-2]:
                    f = (x - xs[-2]) / (xs[-1] - xs[-2])
                    out.append(ys[-2] + f * (ys[-1] - ys[-2]))
                else:
                    out.append(ys[-1])
            else:
                lo = 0
                for i in range(len(xs) - 1):
                    if xs[i] <= x <= xs[i + 1]:
                        lo = i
                        break
                x0, x1 = xs[lo], xs[lo + 1]
                y0, y1 = ys[lo], ys[lo + 1]
                f = (x - x0) / (x1 - x0) if x1 != x0 else 0.0
                out.append(y0 + f * (y1 - y0))
        return out


@dataclass
class ImageBlob:
    name: str
    offset: int
    data: bytes
    is_jpeg_intact: bool
    note: str = ""
    fmt: str = "jpeg"             # "jpeg" or "png": what ``data`` holds
    loader: object = None         # callable -> bytes, for images decoded on demand
    sample: str = ""              # the sample / point this picture belongs to
    taken: str = ""               # acquisition date/time (display string)
    # sample-view camera images carry their own stage calibration:
    #   {"x_mm", "y_mm": stage position of the image centre,
    #    "um_per_px_x", "um_per_px_y", "width", "height"}
    # (see snapshot.py for the pixel <-> stage mapping)
    calib: Optional[dict] = None

    def get_bytes(self):
        """The image file bytes (decoding them first when they were left for
        later); None if there is nothing to show."""
        if not self.data and self.loader is not None:
            try:
                self.data = self.loader() or b""
            except Exception as exc:          # a broken file must not crash the GUI
                self.note = f"{self.note} Could not decode: {exc}".strip()
                self.loader = None
        return self.data or None


@dataclass
class TreeNode:
    label: str
    type_name: str = ""
    offset: int = 0
    children: list = field(default_factory=list)
    region: Optional[Region] = None
    image: Optional[ImageBlob] = None
    cols: tuple = ()          # extra column values for the browser tree


class SpectrumFile:
    """Base class / interface the GUI relies on (see Workspace)."""

    format_name = ""

    def __init__(self):
        self.path = None
        self.regions: list = []
        self.images: list = []
        self.samples: list = []        # list[(offset, name)]
        self.tree: Optional[TreeNode] = None
        self.instrument = {}           # system-wide metadata
        self.depth_profile = {"is_profile": False, "n_levels": 0,
                              "regions_per_level": 0, "etch_per_level": 0.0,
                              "total_etch_time": 0.0, "cumulative": [],
                              "etch_source": ""}
        self.corruption = {"corrupted": False, "message": ""}
        self.summary = {}
        self.warnings: list = []       # non-fatal notes shown after loading
        self._sample_pos = {}
        self.sputter_hint = {}         # ion gun settings the file states
        # set by the app: user edits kept beside the data (annotations.py)
        self.annotations = None
        self.file_id = ""
        self._pos = {}                 # id(region) -> position in regions

    def load(self, path: str):
        raise NotImplementedError

    def _finish(self):
        """Stamp the source file name, then build the tree and summary."""
        name = os.path.basename(self.path or "")
        for r in self.regions:
            r.source = r.source or name     # a session reader sets its own
        self._pos = {id(r): i for i, r in enumerate(self.regions)}
        self._build_tree()
        self._build_summary()
        return self

    def date_for_region(self, r) -> str:
        return r.date

    def region_pos(self, r):
        """Position of ``r`` in ``self.regions`` (None if it is not ours)."""
        return self._pos.get(id(r))

    # -- positions / images ---------------------------------------------
    def analysis_positions(self):
        """Distinct analysis positions as (label, x_mm, y_mm) per sample."""
        return [(s, xy[0], xy[1])
                for s, xy in getattr(self, "_sample_pos", {}).items()]

    def sputter_prefill(self):
        """Sputter settings the file states (ion, energy, and whatever else it
        records), as a partial ``sputter`` settings dict; {} when it says
        nothing. Never invents a value."""
        import sputter
        return sputter.merge_prefill(
            self.sputter_hint,
            sputter.from_text(self.instrument.get("Ion gun / sputtering",
                                                  "")))

    def sample_positions(self):
        """One representative position per sample: {sample: (x, y)}."""
        return dict(getattr(self, "_sample_pos", {}))

    def extract_jpeg(self, blob):
        """Bytes of an image Pillow can open (JPEG or PNG), or None."""
        if blob.fmt == "png" or blob.loader is not None:
            return blob.get_bytes()
        if not blob.is_jpeg_intact:
            return None
        d = blob.data
        s = d.find(b"\xff\xd8")
        if s == -1:
            return None
        e = d.find(b"\xff\xd9", s)
        return d[s:(e + 2) if e != -1 else len(d)]

    # -- tree -----------------------------------------------------------
    @staticmethod
    def _be_str(r):
        if r.decodable and r.energy:
            return f"{r.energy[0]:.0f}-{r.energy[-1]:.0f} eV"
        return "no data"

    @staticmethod
    def _pe_str(r):
        return f"{r.pass_energy:g}" if r.pass_energy else ""

    def _build_tree(self):
        base = os.path.basename(self.path) if self.path else "Experiment"
        root = TreeNode(base, "experiment")
        is_profile = self.depth_profile.get("is_profile")
        pos = self.sample_positions()

        order, groups = [], {}
        for r in self.regions:
            if r.sample not in groups:
                groups[r.sample] = []
                order.append(r.sample)
            groups[r.sample].append(r)
        if not order:
            order = [s for _, s in self.samples] or ["Sample"]
            groups = {s: [] for s in order}

        for sample_name in order:
            pstr = ""
            if sample_name in pos:
                pstr = f"({pos[sample_name][0]:.1f}, {pos[sample_name][1]:.1f} mm)"
            flat = len(order) == 1 and not sample_name
            sample_node = (root if flat else
                           TreeNode(sample_name or "(unnamed)",
                                    "sample", cols=(pstr, "", "", "")))

            if (not is_profile and not flat
                    and len(groups[sample_name]) == 1):
                # one spectrum in this sample: a single row, not three levels
                r = groups[sample_name][0]
                tag = "" if r.decodable else "  [no data]"
                root.children.append(TreeNode(
                    f"{r.name} ({sample_name}){tag}", "EscaSpectrum", r.offset,
                    region=r,
                    cols=(self._be_str(r), str(r.n_points), self._pe_str(r),
                          "")))
                continue

            if is_profile:
                # Sample -> Region type -> per-level leaves
                byname, rorder = {}, []
                for r in groups[sample_name]:
                    if r.name not in byname:
                        byname[r.name] = []
                        rorder.append(r.name)
                    byname[r.name].append(r)
                for rname in rorder:
                    rl = byname[rname]
                    folder = TreeNode(rname, "regionfolder",
                                      cols=(f"{len(rl)} levels", "",
                                            self._pe_str(rl[0]), ""))
                    for r in rl:
                        et = (f"{r.etch_time:g} s" if r.etch_time is not None
                              else "")
                        folder.children.append(TreeNode(
                            f"Level {r.etch_level}", "EscaSpectrum", r.offset,
                            region=r,
                            cols=(self._be_str(r), str(r.n_points),
                                  self._pe_str(r), et)))
                    sample_node.children.append(folder)
            else:
                for r in groups[sample_name]:
                    tag = "" if r.decodable else "  [no data]"
                    sample_node.children.append(TreeNode(
                        f"{r.name}{tag}", "EscaSpectrum", r.offset, region=r,
                        cols=(self._be_str(r), str(r.n_points),
                              self._pe_str(r), "")))
            if not flat:
                root.children.append(sample_node)

        if self.images:
            imgs = TreeNode(f"Images ({len(self.images)})",
                            "HolderSnapshotFolder")
            for n, im in enumerate(self.images, 1):
                lbl = im.name if len(self.images) == 1 else f"{im.name} {n}"
                imgs.children.append(
                    TreeNode(lbl, "HolderContentSnapshot", im.offset, image=im))
            root.children.append(imgs)

        self.tree = root

    def _file_size(self):
        raw = getattr(self, "raw", None)
        if raw is not None:
            return len(raw)
        try:
            return os.path.getsize(self.path)
        except (OSError, TypeError):
            return 0

    def _build_summary(self):
        self.summary = {
            "file": self.path, "size": self._file_size(),
            "n_regions": len(self.regions),
            "region_names": [r.name for r in self.regions],
            "n_images": len(self.images),
            "n_decodable": sum(1 for r in self.regions if r.decodable),
            "corrupted": self.corruption["corrupted"],
            "format": self.format_name,
        }

    # -- metadata -------------------------------------------------------
    def region_metadata(self, r: "Region") -> dict:
        """Full, ordered acquisition metadata for one region."""
        def fmt(v, unit="", nd=None):
            if v is None:
                return ""
            if nd is not None:
                return f"{v:.{nd}f}{unit}"
            return f"{v}{unit}"

        be0 = r.energy[0] if r.decodable and r.energy else None
        be1 = r.energy[-1] if r.decodable and r.energy else None
        md = {}
        md["Sample"] = r.sample
        md["Region"] = r.name
        if r.extra.get("scan"):
            md["Scan"] = r.extra["scan"]
        md["Technique"] = r.technique
        md["Source file"] = r.source
        md["File format"] = self.format_name
        sw = r.extra.get("acq_software") or self.instrument.get(
            "Acquisition software", "")
        if sw:
            md["Acquisition software"] = sw
        md["Date acquired"] = self.date_for_region(r)
        t0 = timing.parse_ts(r.extra.get("t_start"))
        if t0:
            zone = r.extra.get("tz", "")
            md["Run started"] = timing.fmt_ts(t0, zone)
            t1 = timing.parse_ts(r.extra.get("t_end"))
            if t1 and t1 >= t0:
                md["Run finished"] = timing.fmt_ts(t1, zone)
        if r.pos_x is not None:
            md["Position X (mm)"] = f"{r.pos_x:.3f}"
            md["Position Y (mm)"] = f"{r.pos_y:.3f}"
        if r.etch_level is not None:
            md["Etch level"] = str(r.etch_level)
            md["Etch time (s)"] = (f"{r.etch_time:g}"
                                   if r.etch_time is not None else "")
        md["Instrument"] = self.instrument.get("Instrument", "")
        md["Operator"] = self.instrument.get("Operator", "")
        md["Acquisition computer"] = self.instrument.get("Acquisition computer", "")
        md["X-ray source"] = self.instrument.get("X-ray source", "")
        md["Anode"] = r.anode or self.instrument.get("X-ray source", "")
        md["Photon energy (eV)"] = fmt(r.photon_energy, "", 2)
        md["Source power (W)"] = (r.conditions.get("X-ray Power", "")
                                  .replace("W", "").strip())
        for key in ("Anode voltage (kV)", "Emission current (mA)",
                    "X-ray spot (µm)", "Sample tilt (°)", "Take-off angle (°)"):
            if r.conditions.get(key):
                md[key] = r.conditions[key]
        md["Pass energy (eV)"] = fmt(r.pass_energy, "", 0) if r.pass_energy else ""
        md["Lens mode"] = r.lens_mode or self.instrument.get("Lens mode", "")
        md["Aperture"] = r.aperture or self.instrument.get("Aperture", "")
        if r.extra.get("analyser_mode"):
            md["Analyser mode"] = r.extra["analyser_mode"]
        if r.extra.get("acq_mode"):
            md["Acquisition mode"] = r.extra["acq_mode"]
        md["BE start (eV)"] = fmt(be0, "", 2)
        md["BE end (eV)"] = fmt(be1, "", 2)
        md["Step (eV)"] = fmt(r.step, "", 3)
        md["Dwell (s)"] = fmt(r.dwell, "", 3)
        md["Points"] = str(r.n_points) if r.n_points else ""
        if r.extra.get("n_scans"):
            md["Scans"] = str(int(r.extra["n_scans"]))
        net = timing.net_seconds(r)
        if net is not None:
            md["Counting time"] = timing.fmt_duration(net)
        md["Quality"] = r.conditions.get("Quality", "")
        md["Charge neutraliser"] = (r.extra.get("neutraliser")
                                    or self.instrument.get("Charge neutraliser", ""))
        md["Ion gun / sputtering"] = self.instrument.get("Ion gun / sputtering", "")
        for key in SESSION_KEYS:              # what the file says about the job
            if self.instrument.get(key):
                md[key] = self.instrument[key]
        if r.extra.get("config"):
            md["Source configuration"] = r.extra["config"]
        if r.fit is not None:
            bgs = sorted({g.background for g in r.fit.regions})
            md["CasaXPS fit"] = (
                f"{len(r.fit.components)} component(s)"
                + (f", {'/'.join(bgs)} background" if bgs else "")
                + (f", BE calibration {r.fit.calib_shift:+.2f} eV"
                   if r.fit.calib_shift else ""))
        cc = r.extra.get("casa_calib")
        if cc and cc.get("shift"):
            md["BE calibration (CasaXPS)"] = (
                f"{cc['shift']:+.3f} eV ({cc['measured']:.4f} to "
                f"{cc['assigned']:.4f})"
                + (", taken from the other regions of this sample"
                   if cc.get("inherited") else ""))
        for k, v in (r.extra.get("preserved_metadata") or {}).items():
            if not md.get(k):              # restored from a VAMAS comment
                md[k] = v
        if self.annotations is not None:
            md = self.annotations.apply_metadata(
                self.file_id, self._pos.get(id(r)), r, md)
        return md

    def metadata_rows(self):
        """One metadata dict per region, in file order."""
        return [self.region_metadata(r) for r in self.regions]

    def samples_metadata(self):
        """Grouped: {sample_name: [region_metadata, ...]} preserving order."""
        groups, order = {}, []
        for r in self.regions:
            groups.setdefault(r.sample, []).append(self.region_metadata(r))
            if r.sample not in order:
                order.append(r.sample)
        ann = self.annotations
        return [(ann.sample_label(self.file_id, s) if ann else s, groups[s])
                for s in order]

