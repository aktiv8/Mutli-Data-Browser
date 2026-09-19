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

UNSET = 1e36        # VAMAS uses 1e37 for "not specified"


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

    @property
    def n_points(self) -> int:
        return len(self.counts) if self.counts else 0

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
            r.source = name
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

    def sample_positions(self):
        """One representative position per sample: {sample: (x, y)}."""
        return dict(getattr(self, "_sample_pos", {}))

    def extract_jpeg(self, blob):
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
        md["Technique"] = r.technique
        md["Source file"] = r.source
        md["File format"] = self.format_name
        md["Date acquired"] = self.date_for_region(r)
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
        md["Pass energy (eV)"] = fmt(r.pass_energy, "", 0) if r.pass_energy else ""
        md["Lens mode"] = r.lens_mode or self.instrument.get("Lens mode", "")
        md["Aperture"] = r.aperture or self.instrument.get("Aperture", "")
        md["BE start (eV)"] = fmt(be0, "", 2)
        md["BE end (eV)"] = fmt(be1, "", 2)
        md["Step (eV)"] = fmt(r.step, "", 3)
        md["Dwell (s)"] = fmt(r.dwell, "", 3)
        md["Points"] = str(r.n_points) if r.n_points else ""
        md["Quality"] = r.conditions.get("Quality", "")
        md["Charge neutraliser"] = self.instrument.get("Charge neutraliser", "")
        md["Ion gun / sputtering"] = self.instrument.get("Ion gun / sputtering", "")
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

