"""Thermo Scientific / VG Avantage "DataSpace" files.

* ``.avg`` is the ASCII dump of a DataSpace (``;Dump of DataSpace ...``,
  ``$FORMAT=3``): typed properties, the axis definitions and ``LIST@`` rows of
  values. The binary ``.vgd`` (see thermo_vgd.py) holds the same DataSpace, so
  both readers build a :class:`DataSpace` and share
  :meth:`ThermoDataSpaceFile._from_dataspace`.
* The energy axis is stored as kinetic energy (``EV_SCALE = 1``); binding
  energy is hv - KE, verified against CasaXPS's VAMAS export of the same data.
"""

from __future__ import annotations

import os
import re
from array import array

from .base import (Region, ImageBlob, SpectrumFile, canon_region_name,
                   read_bytes)

_PROP_RE = re.compile(r"^(DS_\w+(?:\[\d+\])?)\s*:\s*(VT_\w+)\s*=\s*(.*)$")
_AXISVALUE_RE = re.compile(
    r"SPACEAXIS=(\d+)\s+LABEL='([^']*)'\s+POINT=(\d+)\s+VALUE=(?:'([^']*)'|([^;\s]+))")
_INT_TYPES = ("VT_I1", "VT_I2", "VT_I4", "VT_I8", "VT_UI1", "VT_UI2", "VT_UI4",
              "VT_UI8", "VT_INT", "VT_UINT")
K_ENERGY = "DS_SOPROPID_ENERGY"
K_VALUE_TYPE = "DS_GEPROPID_VALUE_TYPE"
VALUE_RGB = 13                       # a camera image: one packed colour per pixel
# axis type codes of the binary VGSpaceAxes stream (the .avg dump spells them out)
AXIS_CODES = {1: "ENERGY", 3: "X", 4: "Y", 6: "ETCHLEVEL", 8: "ETCHTIME",
              10: "POSITION"}
AXIS_DEFAULTS = {          # symbol, unit, label the dump would print
    "ENERGY": ("E", "eV", "Energy"), "X": ("X", "µm", "X"),
    "Y": ("Y", "µm", "Y"), "ETCHTIME": ("EtchTime", "s", "Etch Time"),
    "ETCHLEVEL": ("EtchLevel", "", "Etch Level"),
    "POSITION": ("Pos", "", "Position")}


def typed_value(vt: str, raw: str):
    raw = raw.strip()
    if vt == "VT_BSTR":
        m = re.match(r"^'(.*)'$", raw, re.S)
        return m.group(1) if m else raw
    try:
        if vt in _INT_TYPES:
            return int(raw)
        if vt in ("VT_R4", "VT_R8"):
            return float(raw)
    except ValueError:
        return raw
    if vt == "VT_BOOL":
        return raw.lower() in ("true", "1", "-1")
    return raw                      # VT_DATE etc. stay text (D/M/Y H:M:S)


class DataSpace:
    """Parsed Avantage DataSpace (independent of the container format)."""

    def __init__(self):
        self.props = {}
        self.dump_path = ""
        self.data_axes = []      # (start, end, n_space_axes) per data axis
        self.space_axes = []     # dict(start,width,n,type,linear,symbol,unit,label)
        self.blocks = []         # dict(index=tuple, labels={space_idx: value}, values=[..])
        self.pixels = None       # camera images: callable -> packed pixels, row by row
        self.raw = None          # SnapMap: array('d') [iy][ix][channel], blocks left empty

    @property
    def n_energy(self):
        return self.space_axes[0]["n"] if self.space_axes else 0

    def axis_types(self):
        return [a["type"].upper() for a in self.space_axes]

    def space_of_data_axis(self):
        """[[space axis indices]] for every data axis (a multi-point axis
        drives Position, X and Y together)."""
        out, first = [], 0
        for (_s, _e, nsp) in self.data_axes:
            out.append(list(range(first, first + nsp)))
            first += nsp
        return out


def dataspace_kind(ds: DataSpace) -> str:
    """What a DataSpace holds: ``spectrum``, ``position`` (one spectrum per
    analysis point), ``levels`` (a depth profile), ``map`` (a SnapMap: a
    spectrum per pixel), ``image`` (a camera picture), ``table`` (one value
    per point, e.g. the auto-height Z values) or ``other``."""
    types = ds.axis_types()
    if not types:
        return "other"
    if types[0] != "ENERGY":
        if (ds.props.get(K_VALUE_TYPE) == VALUE_RGB
                or (types[:2] == ["X", "Y"] and len(ds.data_axes) == 2)):
            return "image"
        return "table" if "POSITION" in types else "other"
    extra = ds.space_of_data_axis()[1:]
    if not extra:
        return "spectrum"
    kinds = {types[i] for sp in extra for i in sp if i < len(types)}
    if "POSITION" in kinds:
        return "position"
    if kinds <= {"X", "Y"}:
        return "map"
    return "levels"


def sniff(head: bytes, ext: str) -> bool:
    return b"Dump of DataSpace" in head[:400] or (
        ext in (".avg", ".avx") and b"$FORMAT" in head[:3000])


def parse_avg(text: str) -> DataSpace:
    ds = DataSpace()
    mode = ""
    pending = {}
    cur = None
    for raw_line in text.split("\n"):
        s = raw_line.strip()
        if not s:
            continue
        if s.startswith(";"):
            m = re.match(r";Dump of DataSpace '(.*)'", s)
            if m:
                ds.dump_path = m.group(1)
            continue
        m = _PROP_RE.match(s)
        if m:
            ds.props[m.group(1)] = typed_value(m.group(2), m.group(3))
            continue
        if s.startswith("$DATAAXES="):
            mode = "dax"
            continue
        if s.startswith("$SPACEAXES="):
            mode = "sax"
            continue
        if s.startswith("$PROPERTIES=") or s.startswith("$FORMAT="):
            mode = ""
            continue
        if s.startswith("$AXISVALUE="):
            mv = _AXISVALUE_RE.search(s)
            if mv:
                val = mv.group(4) if mv.group(4) is not None else mv.group(5)
                try:
                    val = float(val) if mv.group(4) is None else val
                except ValueError:
                    pass
                pending[int(mv.group(1))] = val
            continue
        if s.startswith("$DATA="):
            spec = s[len("$DATA="):].split(",")
            idx = tuple(int(x) for x in spec[1:] if x.strip().lstrip("-").isdigit())
            n = ds.n_energy
            cur = {"index": idx, "labels": dict(pending), "values": [None] * n}
            ds.blocks.append(cur)
            pending = {}
            mode = "data"
            continue
        if mode == "dax":
            m = re.match(r"^\d+\s*=\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(\d+)", s)
            if m:
                ds.data_axes.append(tuple(int(g) for g in m.groups()))
            continue
        if mode == "sax":
            m = re.match(
                r"^\d+\s*=\s*([^,]+),\s*([^,]+),\s*(\d+),\s*([^,]+),\s*([^,]+),"
                r"\s*'([^']*)',\s*'([^']*)',\s*'([^']*)'", s)
            if m:
                ds.space_axes.append({
                    "start": float(m.group(1)), "width": float(m.group(2)),
                    "n": int(m.group(3)), "type": m.group(4).strip(),
                    "linear": m.group(5).strip(), "symbol": m.group(6),
                    "unit": m.group(7), "label": m.group(8)})
            continue
        if mode == "data" and s.startswith("LIST@") and cur is not None:
            m = re.match(r"LIST@\s*(\d+)\s*=\s*(.*)$", s)
            if not m:
                continue
            base = int(m.group(1))
            for k, tok in enumerate(m.group(2).split(",")):
                tok = tok.strip()
                if tok and tok != "#empty#" and base + k < len(cur["values"]):
                    try:
                        cur["values"][base + k] = float(tok)
                    except ValueError:
                        pass
    return ds


def _dmy(s):
    """'12/5/2008   17:34:00' (D/M/Y) -> '2008-05-12 17:34:00'."""
    m = re.match(r"^\s*(\d+)/(\d+)/(\d+)\s+(\d+):(\d+):(\d+)", s or "")
    if not m:
        return (s or "").strip()
    d, mo, y, hh, mi, ss = (int(x) for x in m.groups())
    return f"{y:04d}-{mo:02d}-{d:02d} {hh:02d}:{mi:02d}:{ss:02d}"


_LINE = r"[A-Z][a-z]?\s*\d[spdf](?:\d(?:/\d)?)?"


def _line_name(tok: str) -> str:
    """'C1s' -> 'C 1s'; 'Cu2p3' (a spin-orbit component) -> 'Cu 2p3/2'."""
    m = re.fullmatch(r"([A-Z][a-z]?)\s*(\d[spdf])(\d)", tok)
    if m:
        return f"{m.group(1)} {m.group(2)}{m.group(3)}/2"
    return canon_region_name(tok)


def region_name_from_title(title: str) -> str:
    """'C1s Scan' -> 'C 1s'; a scan of two lines ('Si2p Al2p Scan') keeps both
    ('Si 2p Al 2p'); anything with 'survey' / 'wide' is a survey."""
    t = (title or "").strip()
    m = re.match(rf"^({_LINE})\b", t)
    if m:
        names, rest = [_line_name(m.group(1))], t[m.end():]
        while True:
            m = re.match(rf"^\s+({_LINE})\b", rest)
            if not m:
                break
            names.append(_line_name(m.group(1)))
            rest = rest[m.end():]
        return " ".join(names)
    if re.search(r"survey|wide", t, re.I):
        return "Survey"
    return t or "Region"


class ThermoDataSpaceFile(SpectrumFile):
    """Shared logic: DataSpace -> Regions + metadata."""

    kind = "spectrum"            # what dataspace_kind() found in the file
    value_table = None           # {"label", "unit", "rows": [(label, x_mm, y_mm, value)]}

    @staticmethod
    def _stage(p):
        """Stage position in mm from the property block (stored in nm)."""
        x, y = p.get("DS_STPROPID_POS_X"), p.get("DS_STPROPID_POS_Y")
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            return x / 1e6, y / 1e6
        return None

    def _from_dataspace(self, ds: DataSpace):
        p = ds.props
        if not ds.space_axes:
            raise ValueError("this DataSpace is empty (no axes or data)")
        self.kind = dataspace_kind(ds)
        self._instrument_from(p)
        if self.kind == "image":
            return self._image_from(ds)
        if self.kind == "table":
            return self._table_from(ds)
        hv = p.get(K_ENERGY)
        hv = round(float(hv), 3) if hv else None    # stored as float32
        title = p.get("DS_EXT_SUPROPID_TITLE") or os.path.splitext(
            os.path.basename(self.path or ""))[0]
        name = region_name_from_title(title)
        ax0 = ds.space_axes[0]
        if ax0["type"].upper() != "ENERGY":
            self.warnings.append(
                f"First axis is '{ax0['type']}', not ENERGY; shown on its "
                "native axis.")
        native = [ax0["start"] + i * ax0["width"] for i in range(ax0["n"])]
        ev_scale = p.get("DS_ACPROPID_EV_SCALE", 1)
        is_ke = ax0["type"].upper() == "ENERGY" and ev_scale != 2
        if ev_scale not in (1, 2):
            self.warnings.append(
                f"Unknown energy scale flag ({ev_scale}); assumed kinetic.")
        if is_ke and hv:
            energy, e_label = [hv - ke for ke in native], "Binding Energy"
        elif is_ke:
            energy, e_label = native, "Kinetic Energy"
            self.warnings.append(
                "Photon energy not found: shown on a kinetic-energy axis.")
        else:
            energy, e_label = native, ax0["label"] or "Energy"

        extra_kind = {"spectrum": "none"}.get(self.kind, self.kind)
        types = ds.axis_types()
        extra_space = [i for sp in ds.space_of_data_axis()[1:] for i in sp]
        stage = self._stage(p)

        regions = []

        def make(idx, values, sample="", note="", pos=None, level=None,
                 etch_time=None):
            ok = values is not None and any(v is not None for v in values)
            counts = None
            if ok:
                counts = [v if v is not None else 0.0 for v in values]
            r = Region(
                name=name, index=idx, offset=idx, technique="XPS",
                energy=energy if ok else None, counts=counts,
                energy_label=e_label, energy_units=ax0["unit"] or "eV",
                count_label=p.get("DS_GEPROPID_VALUE_LABEL") or "Counts",
                count_units="counts", decodable=ok,
                note=note or ("" if ok else
                              "Header only: this file contains no spectrum "
                              "values (#empty#)."),
                sample=sample, photon_energy=hv,
                pass_energy=p.get("DS_ANPROPID_PASS"),
                dwell=p.get("DS_ACPROPID_ACQ_TIME"),
                step=abs(ax0["width"]) or None,
                lens_mode=p.get("DS_ANPROPID_LENS_MODE_NAME", ""),
                date=_dmy(p.get("DS_ACPROPID_START_TIME")
                          or p.get("DS_EXT_SUPROPID_CREATED")),
                anode=("Al Kα (mono)" if p.get("DS_SOPROPID_MONO") and hv
                       and 1480 < hv < 1490 else ""),
                etch_level=level, etch_time=etch_time,
            )
            v, i_ = p.get("DS_SOPROPID_VOLTAGE"), p.get("DS_SOPROPID_CURRENT")
            if v and i_:
                r.conditions["X-ray Power"] = f"{v * i_:.1f} W"
            spot = p.get("DS_SOPROPID_WIDTH")
            if spot:
                r.conditions["X-ray spot (µm)"] = f"{spot:g}"
            if pos:
                r.pos_x, r.pos_y = pos
            elif stage:
                r.pos_x, r.pos_y = stage
            r.extra["props"] = p
            regions.append(r)
            return r

        blocks = ds.blocks or [{"index": (), "labels": {}, "values": []}]
        if extra_kind == "map":
            self._map_from(ds, blocks, make, stage, energy)
        elif extra_kind == "none" or len(blocks) == 1 and extra_kind != "position":
            make(0, blocks[0]["values"])
        else:
            for k, b in enumerate(blocks):
                labels = b["labels"]
                sample, pos, etch = "", None, None
                if extra_kind == "position":
                    lab = next((labels[i] for i in extra_space
                                if i in labels and isinstance(labels[i], str)),
                               f"Pt {k + 1}")
                    sample = str(lab)
                    xy = {}
                    for i in extra_space:
                        t = types[i] if i < len(types) else ""
                        if t in ("X", "Y") and isinstance(labels.get(i), float):
                            xy[t] = labels[i] / 1000.0            # um -> mm
                    if "X" in xy and "Y" in xy:
                        pos = (xy["X"], xy["Y"])
                else:
                    for i in extra_space:
                        if (types[i] == "ETCHTIME"
                                and isinstance(labels.get(i), float)):
                            etch = labels[i]
                make(k, b["values"], sample=sample, pos=pos,
                     level=k if extra_kind == "levels" else None,
                     etch_time=etch)
                if pos and sample:
                    self._sample_pos[sample] = pos

        self.regions = regions
        if extra_kind == "levels":
            times = sorted({r.etch_time for r in regions
                            if r.etch_time is not None})
            self.depth_profile = {
                "is_profile": True, "n_levels": len(regions),
                "regions_per_level": 1, "etch_per_level": 0.0,
                "total_etch_time": times[-1] if times else 0.0,
                "cumulative": times, "etch_source": "data axis"}

    def _instrument_from(self, p):
        hv = p.get(K_ENERGY)
        hv = round(float(hv), 3) if hv else None
        instr = {"Instrument": p.get("DS_GEPROPID_INSTRUMENT", ""),
                 "Operator": p.get("DS_EXT_SUPROPID_AUTHOR", ""),
                 "Lens mode": p.get("DS_ANPROPID_LENS_MODE_NAME", "")}
        if hv:
            instr["X-ray source"] = ("Al Kα, monochromated"
                                     if p.get("DS_SOPROPID_MONO") and 1480 < hv < 1490
                                     else "") + f" ({hv:g} eV)"
            instr["X-ray source"] = instr["X-ray source"].strip()
        if "DS_SOURCE_FLOODGUNPROPID_DESCRIPTION" in p:
            instr["Charge neutraliser"] = (
                f"{p['DS_SOURCE_FLOODGUNPROPID_DESCRIPTION']}, "
                f"{p.get('DS_SOURCE_FLOODGUNPROPID_CURRENT', 0):g} µA")
        self.instrument = {k: v for k, v in instr.items() if v}
        import sputter
        self.sputter_hint = sputter.from_properties(p)

    # -- SnapMap -----------------------------------------------------------------
    def _map_from(self, ds, blocks, make, stage, energy):
        """A spectrum at every pixel: the summed spectrum is the region, the
        pixels ride along as ``extra["cube"]`` (see snapmap.py)."""
        import snapmap
        types = ds.axis_types()
        xi, yi = types.index("X"), types.index("Y")
        ax_x, ax_y = ds.space_axes[xi], ds.space_axes[yi]
        dax = ds.space_of_data_axis()
        pos_x = next(k for k, sp in enumerate(dax[1:]) if xi in sp)
        pos_y = next(k for k, sp in enumerate(dax[1:]) if yi in sp)
        nx, ny = ax_x["n"], ax_y["n"]
        n = ds.n_energy
        note = (f"SnapMap ({nx} x {ny} pixels): the summed spectrum is "
                "shown; open the map to see where the signal comes from.")
        if ds.raw is not None:               # binary file: no per-pixel lists
            from array import array as _array
            cube = snapmap.MapCube(
                list(energy), nx, ny, ax_x["start"], ax_x["width"],
                ax_y["start"], ax_y["width"], _array("f", ds.raw))
            r = make(0, cube.total(), note=note)
            cube.label = r.count_label
            if stage:
                cube.stage_x_mm, cube.stage_y_mm = stage
            r.extra["cube"] = cube
            return
        tot = [0.0] * n
        seen = False
        for b in blocks:
            for i, v in enumerate(b["values"]):
                if v is not None:
                    tot[i] += v
                    seen = True
        r = make(0, tot if seen else None, note=note)
        if seen and r.energy:
            cube = snapmap.build(
                r.energy, nx, ny, ax_x["start"], ax_x["width"], ax_y["start"],
                ax_y["width"],
                (((b["index"][pos_x], b["index"][pos_y]), b["values"])
                 for b in blocks if len(b["index"]) > max(pos_x, pos_y)),
                label=r.count_label)
            if stage:
                cube.stage_x_mm, cube.stage_y_mm = stage
            r.extra["cube"] = cube

    # -- camera images and value tables -----------------------------------------
    def _image_from(self, ds):
        p = ds.props
        ax_x, ax_y = ds.space_axes[0], ds.space_axes[1]
        w, h = ax_x["n"], ax_y["n"]
        stage = self._stage(p)
        calib = {"width": w, "height": h,
                 "um_per_px_x": abs(ax_x["width"]),
                 "um_per_px_y": abs(ax_y["width"])}
        if stage:
            calib["x_mm"], calib["y_mm"] = stage
        pixels = ds.pixels

        def decode():
            from .imaging import encode_png, unpack_rgb
            return encode_png(w, h, unpack_rgb(pixels()))

        stem = os.path.splitext(os.path.basename(self.path or ""))[0]
        self.images = [ImageBlob(
            name=stem or "Image", offset=0, data=b"", is_jpeg_intact=False,
            fmt="png", loader=decode if pixels else None,
            taken=_dmy(p.get("DS_ACPROPID_START_TIME")
                       or p.get("DS_EXT_SUPROPID_CREATED")),
            calib=calib, note=f"Sample-view camera image, {w} x {h} pixels.")]
        self.regions = []

    def _table_from(self, ds):
        """One value per analysis point (e.g. the auto-height Z), kept as a
        table; there is no spectrum in it."""
        p = ds.props
        idx = {t: i for i, t in enumerate(ds.axis_types())}
        first = ds.blocks[0] if ds.blocks else None
        vals = first["values"] if first else []
        rows = []
        for k, v in enumerate(vals):
            def lab(t):
                i = idx.get(t)
                if i is None:
                    return None
                a = ds.space_axes[i]
                if a.get("values") and k < len(a["values"]):
                    return a["values"][k]
                if a["linear"] != "LINEAR":
                    return None            # a text dump does not list them
                return a["start"] + k * a["width"]
            x, y = lab("X"), lab("Y")
            rows.append((f"Pt {k + 1}", None if x is None else x / 1000.0,
                         None if y is None else y / 1000.0, v))
        self.value_table = {
            "label": p.get("DS_GEPROPID_VALUE_LABEL") or "Value",
            "unit": p.get("DS_GEPROPID_VALUE_UNIT") or "", "rows": rows}
        self.regions = []


class ThermoAvgFile(ThermoDataSpaceFile):
    format_name = "Thermo Avantage (.avg)"

    def load(self, path: str):
        self.path = path
        raw = read_bytes(path)
        text = raw.decode("latin-1").replace("\r\n", "\n").replace("\r", "\n")
        ds = parse_avg(text)
        if ds.axis_types()[:1] != ["ENERGY"] and ds.blocks:
            packed = array("d", (0.0 if v is None else v
                                 for b in ds.blocks for v in b["values"]))
            ds.pixels = lambda: packed
        self._from_dataspace(ds)
        return self._finish()
