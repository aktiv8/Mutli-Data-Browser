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

from .base import Region, SpectrumFile, canon_region_name, read_bytes

_PROP_RE = re.compile(r"^(DS_\w+(?:\[\d+\])?)\s*:\s*(VT_\w+)\s*=\s*(.*)$")
_AXISVALUE_RE = re.compile(
    r"SPACEAXIS=(\d+)\s+LABEL='([^']*)'\s+POINT=(\d+)\s+VALUE=(?:'([^']*)'|([^;\s]+))")
_INT_TYPES = ("VT_I1", "VT_I2", "VT_I4", "VT_I8", "VT_UI1", "VT_UI2", "VT_UI4",
              "VT_UI8", "VT_INT", "VT_UINT")
K_ENERGY = "DS_SOPROPID_ENERGY"


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

    @property
    def n_energy(self):
        return self.space_axes[0]["n"] if self.space_axes else 0


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


def region_name_from_title(title: str) -> str:
    t = (title or "").strip()
    m = re.match(r"^([A-Z][a-z]?\s*\d[spdf](?:\d/\d)?)\b", t)
    if m:
        return canon_region_name(m.group(1))
    if re.search(r"survey|wide", t, re.I):
        return "Survey"
    return t or "Region"


class ThermoDataSpaceFile(SpectrumFile):
    """Shared logic: DataSpace -> Regions + metadata."""

    def _from_dataspace(self, ds: DataSpace):
        p = ds.props
        hv = p.get(K_ENERGY)
        hv = round(float(hv), 3) if hv else None    # stored as float32
        title = p.get("DS_EXT_SUPROPID_TITLE") or os.path.splitext(
            os.path.basename(self.path or ""))[0]
        name = region_name_from_title(title)
        if not ds.space_axes:
            raise ValueError("no space axes found in this DataSpace")
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

        # classify the extra (non-energy) data axes
        extra_kind, extra_space = "none", []
        if len(ds.data_axes) > 1:
            first = ds.data_axes[0][2]
            for (start, end, nsp) in ds.data_axes[1:]:
                extra_space += list(range(first, first + nsp))
                first += nsp
            types = [ds.space_axes[i]["type"].upper() for i in extra_space
                     if i < len(ds.space_axes)]
            if "POSITION" in types:
                extra_kind = "position"
            elif types and all(t in ("X", "Y") for t in types):
                extra_kind = "map"
            else:
                extra_kind = "levels"

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
            if pos:
                r.pos_x, r.pos_y = pos
            r.extra["props"] = p
            regions.append(r)

        blocks = ds.blocks or [{"index": (), "labels": {}, "values": []}]
        if extra_kind == "none" or len(blocks) == 1 and extra_kind != "position":
            make(0, blocks[0]["values"])
        elif extra_kind == "map":
            n = ds.n_energy
            tot = [0.0] * n
            seen = False
            for b in blocks:
                for i, v in enumerate(b["values"]):
                    if v is not None:
                        tot[i] += v
                        seen = True
            make(0, tot if seen else None,
                 note=f"Map/image data ({len(blocks)} pixels): shown as the "
                      "summed spectrum.")
        else:
            for k, b in enumerate(blocks):
                labels = b["labels"]
                sample, pos, etch = "", None, None
                if extra_kind == "position":
                    lab = next((labels[i] for i in extra_space
                                if i in labels and isinstance(labels[i], str)),
                               f"Pt {k + 1}")
                    sample = str(lab)
                    xy = []
                    for i in extra_space:
                        t = ds.space_axes[i]["type"].upper()
                        if t in ("X", "Y") and isinstance(labels.get(i), float):
                            xy.append((t, labels[i] / 1000.0))    # µm -> mm
                    d = dict(xy)
                    if "X" in d and "Y" in d:
                        pos = (d["X"], d["Y"])
                else:
                    for i in extra_space:
                        lab = ds.space_axes[i]["label"].lower()
                        if isinstance(labels.get(i), float) and re.search(
                                r"time|etch", lab):
                            etch = labels[i]
                make(k, b["values"], sample=sample, pos=pos,
                     level=k if extra_kind == "levels" else None,
                     etch_time=etch)
                if pos and sample:
                    self._sample_pos[sample] = pos

        self.regions = regions
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
        if extra_kind == "levels":
            times = sorted({r.etch_time for r in regions
                            if r.etch_time is not None})
            self.depth_profile = {
                "is_profile": True, "n_levels": len(regions),
                "regions_per_level": 1, "etch_per_level": 0.0,
                "total_etch_time": times[-1] if times else 0.0,
                "cumulative": times, "etch_source": "data axis"}


class ThermoAvgFile(ThermoDataSpaceFile):
    format_name = "Thermo Avantage (.avg)"

    def load(self, path: str):
        self.path = path
        raw = read_bytes(path)
        text = raw.decode("latin-1").replace("\r\n", "\n").replace("\r", "\n")
        ds = parse_avg(text)
        self._from_dataspace(ds)
        return self._finish()
