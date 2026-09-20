"""Thermo Scientific / VG Avantage ``.vgd`` (binary DataSpace) reader.

A ``.vgd`` is an OLE2 compound file (see ole2.py) holding the same DataSpace
that the ``.avg`` text dump describes:

* ``VGData``       raw little-endian float64 values (energy fastest)
* ``VGDataAxes``   ``(start, end, n_space_axes)`` per data axis
* ``VGSpaceAxes``  per space axis: item count, start, width (float64) and, for
                   non-linear axes, the explicit values
* property sets    numeric property ids (Thermo "GE" ids) holding hv, pass
                   energy, stage position, times, ...; per-point axis labels
                   ("Pt #001") live in a separate property set
* ``SummaryInformation``  standard title / author / created

The mapping of property ids to the ``DS_*`` names of the text dump was
established by comparing every ``.vgd`` with its sibling ``.avg``.
"""

from __future__ import annotations

import datetime
import math
import os
import struct

from .base import read_bytes
from .ole2 import OleFile, OleError, is_ole
from .thermo_avg import (AXIS_CODES, AXIS_DEFAULTS, DataSpace,
                         ThermoDataSpaceFile, dataspace_kind)

# property id -> DS_* name (verified against sibling .avg dumps)
PID_NAMES = {
    0x06: "DS_GEPROPID_INSTRUMENT",
    0x0C: "DS_GEPROPID_VALUE_TYPE", 0x0D: "DS_GEPROPID_VALUE_LABEL",
    0x0E: "DS_GEPROPID_VALUE_SYMBOL", 0x0F: "DS_GEPROPID_VALUE_UNIT",
    0x67: "DS_SOPROPID_STYPE", 0x68: "DS_SOPROPID_MONO",
    0x69: "DS_SOPROPID_ENERGY", 0x6A: "DS_SOPROPID_VOLTAGE",
    0x6B: "DS_SOPROPID_CURRENT", 0x6C: "DS_SOPROPID_WIDTH",
    0x6D: "DS_SOPROPID_LENGTH", 0x73: "DS_SOPROPID_GUN",
    0xCB: "DS_STPROPID_POS_X", 0xCC: "DS_STPROPID_POS_Y",
    0xCD: "DS_STPROPID_POS_Z", 0xCE: "DS_STPROPID_POS_TILT",
    0xCF: "DS_STPROPID_POS_AZIM",
    0x12F: "DS_ACPROPID_START_TIME", 0x130: "DS_ACPROPID_END_TIME",
    0x131: "DS_ACPROPID_ACQ_TIME", 0x137: "DS_ACPROPID_MODE",
    0x138: "DS_ACPROPID_DIRECTION", 0x13C: "DS_ACPROPID_EV_SCALE",
    0x148: "DS_ACPROPID_PERIODS",
    0x193: "DS_ANPROPID_MODE", 0x194: "DS_ANPROPID_PASS",
    0x196: "DS_ANPROPID_WORK_FTN", 0x19B: "DS_ANPROPID_LENS_MODE_NAME",
    0x19D: "DS_ANPROPID_TXFN_COEFFS",
    0x25B: "DS_SOURCE_FLOODGUNPROPID_CURRENT",
    0x25C: "DS_SOURCE_FLOODGUNPROPID_ENERGY",
    0x25D: "DS_SOURCE_FLOODGUNPROPID_DESCRIPTION",
    0x2BF: "DS_DEPTHPROFILE_IONGUNPROPID_CURRENT",
    0x2C0: "DS_DEPTHPROFILE_IONGUNPROPID_ENERGY",
    0x2C1: "DS_DEPTHPROFILE_IONGUNPROPID_RASTER_WIDTH",
    0x2C2: "DS_DEPTHPROFILE_IONGUNPROPID_RASTER_HEIGHT",
    0x2C3: "DS_DEPTHPROFILE_IONGUNPROPID_ANGLETOSURFACE",
    0x2C4: "DS_DEPTHPROFILE_IONGUNPROPID_IONTYPE",
    0x2C5: "DS_DEPTHPROFILE_IONGUNPROPID_DESCRIPTION",
    0x2C6: "DS_DEPTHPROFILE_PROPS_ROTATION",
    0x2C7: "DS_DEPTHPROFILE_IONGUNPROPID_SPUTTERRATE",
}
_TXFN_BASE = 100000


def sniff(head: bytes, ext: str) -> bool:
    return is_ole(head) and (ext in (".vgd", ".avx") or
                             "VGData".encode("utf-16le") in head)


def _filetime(v: int) -> str:
    try:
        dt = datetime.datetime(1601, 1, 1) + datetime.timedelta(
            microseconds=v // 10)
        return dt.strftime("%d/%m/%Y   %H:%M:%S")      # same D/M/Y form as .avg
    except (OverflowError, ValueError):
        return ""


def _read_doubles(path):
    """The VGData stream of a ``.vgd`` as an array of doubles."""
    from array import array
    out = array("d")
    out.frombytes(OleFile(read_bytes(path)).read("VGData"))
    return out


def parse_property_set(b: bytes):
    """[(property id, vt, value)] of the first section of an OLE property set."""
    if len(b) < 48:
        return []
    nsets = struct.unpack_from("<I", b, 24)[0]
    if nsets < 1:
        return []
    off = struct.unpack_from("<I", b, 44)[0]
    nprops = struct.unpack_from("<I", b, off + 4)[0]
    out = []
    for i in range(nprops):
        pid, poff = struct.unpack_from("<II", b, off + 8 + 8 * i)
        p = off + poff
        vt = struct.unpack_from("<I", b, p)[0] & 0xFFFF
        q = p + 4
        try:
            if vt in (2, 11):
                v = struct.unpack_from("<h", b, q)[0]
                if vt == 11:
                    v = bool(v)
            elif vt in (3, 19, 22, 23):
                v = struct.unpack_from("<i", b, q)[0]
            elif vt == 4:
                v = struct.unpack_from("<f", b, q)[0]
            elif vt in (5, 7):
                v = struct.unpack_from("<d", b, q)[0]
            elif vt == 64:
                v = struct.unpack_from("<Q", b, q)[0]
            elif vt in (30, 8):
                ln = struct.unpack_from("<I", b, q)[0]
                raw = b[q + 4:q + 4 + ln]
                v = (raw.decode("utf-16le", "replace") if raw[1:2] == b"\0"
                     and vt == 8 else raw.decode("latin-1")).rstrip("\0")
            elif vt == 31:
                ln = struct.unpack_from("<I", b, q)[0]
                v = b[q + 4:q + 4 + 2 * ln].decode("utf-16le",
                                                   "replace").rstrip("\0")
            else:
                continue
        except struct.error:
            continue
        out.append((pid, vt, v))
    return out


def _plausible(x: float) -> bool:
    return math.isfinite(x) and (x == 0.0 or 1e-12 < abs(x) < 1e15)


def parse_space_axes(b: bytes, counts):
    """Decode ``VGSpaceAxes`` given the expected item count of each axis."""
    n_axes = struct.unpack_from("<i", b, 4)[0]
    axes, pos = [], 8
    for k in range(n_axes):
        want = counts[k] if k < len(counts) else None
        hit = None
        start_from = pos + 4                     # skip the axis type field
        for p in range(start_from, len(b) - 21):
            n = struct.unpack_from("<i", b, p)[0]
            if want is not None and n != want:
                continue
            if n < 1:
                continue
            start, width = struct.unpack_from("<2d", b, p + 4)
            if not (_plausible(start) and _plausible(width)):
                continue
            flag = b[p + 20]
            if flag > 1:
                continue
            hit = (p, n, start, width, flag)
            break
        if hit is None:
            raise OleError("could not decode the axis definitions")
        p, n, start, width, flag = hit
        end = p + 21
        values = None
        if flag == 0:                            # non-linear: explicit values
            values = list(struct.unpack_from(f"<{n}d", b, end))
            end += 8 * n
        code = 0
        if end + 4 <= len(b):                    # the axis type follows the axis
            code = struct.unpack_from("<i", b, end)[0]
            end += 4
        axes.append({"n": n, "start": start, "width": width,
                     "linear": flag == 1, "values": values, "code": code})
        pos = end
    return axes


class ThermoVgdFile(ThermoDataSpaceFile):
    format_name = "Thermo Avantage (.vgd)"

    def load(self, path: str):
        self.path = path
        ole = OleFile(read_bytes(path))
        ds = DataSpace()
        self._read_props(ole, ds)
        dax = ole.read("VGDataAxes")
        nd = struct.unpack_from("<i", dax, 4)[0]
        ds.data_axes = [struct.unpack_from("<3i", dax, 8 + 16 * i)
                        for i in range(nd)]
        counts = []
        for (s, e, nsp) in ds.data_axes:
            counts += [e - s + 1] * nsp
        axes = parse_space_axes(ole.read("VGSpaceAxes"), counts)
        for i, a in enumerate(axes):
            typ = AXIS_CODES.get(a["code"]) or (
                "ENERGY" if i == 0 else f"AXIS{a['code']}")
            sym, unit, label = AXIS_DEFAULTS.get(typ, ("?", "", f"Axis {i}"))
            ds.space_axes.append({
                "start": a["start"], "width": a["width"], "n": a["n"],
                "type": typ, "linear": "LINEAR" if a["linear"] else "NON-LINEAR",
                "symbol": sym, "unit": unit, "label": label,
                "values": a["values"]})
        if not ds.space_axes:
            raise ValueError("this DataSpace is empty (no axes or data)")
        if dataspace_kind(ds) == "image":          # decoded when it is shown
            ds.pixels = lambda: _read_doubles(path)
            self._from_dataspace(ds)
            return self._finish()
        raw = ole.read("VGData")
        n_e = ds.space_axes[0]["n"]
        total = len(raw) // 8
        vals = struct.unpack(f"<{total}d", raw[:total * 8])
        n_blocks = max(1, total // n_e)
        extra_ns = [e - s + 1 for (s, e, _n) in ds.data_axes[1:]]
        dax = ds.space_of_data_axis()
        labels = self._point_labels(ole)
        for k in range(n_blocks):
            idx = self._unravel(k, extra_ns)
            lab = {}
            for d, spaces in enumerate(dax[1:]):
                i = idx[d] if d < len(idx) else 0
                for si in spaces:
                    a = ds.space_axes[si]
                    if a["type"] == "POSITION":
                        lab[si] = labels.get(i, f"Pt #{i + 1:03d}")
                    elif a["values"] and i < len(a["values"]):
                        lab[si] = a["values"][i]
                    else:
                        lab[si] = a["start"] + i * a["width"]
            ds.blocks.append({"index": tuple(idx), "labels": lab,
                              "values": list(vals[k * n_e:(k + 1) * n_e])})
        self._from_dataspace(ds)
        return self._finish()

    @staticmethod
    def _unravel(k, dims):
        idx = []
        for d in dims:
            idx.append(k % d)
            k //= d
        return idx

    # -- properties ----------------------------------------------------------
    def _read_props(self, ole, ds):
        p = ds.props
        for name in ole.listdir():
            if not name.startswith("\x05"):
                continue
            try:
                props = parse_property_set(ole.read(name))
            except (struct.error, OleError):
                continue
            if name == "\x05SummaryInformation":
                for pid, vt, v in props:
                    if pid == 2:
                        p["DS_EXT_SUPROPID_TITLE"] = v
                    elif pid == 4:
                        p["DS_EXT_SUPROPID_AUTHOR"] = v
                    elif pid == 12 and vt == 64:
                        p["DS_EXT_SUPROPID_CREATED"] = _filetime(v)
                continue
            for pid, vt, v in props:
                if pid in PID_NAMES:
                    key = PID_NAMES[pid]
                    if vt == 64:
                        v = _filetime(v)
                    p[key] = v
                elif _TXFN_BASE <= pid < _TXFN_BASE + 16:
                    p[f"DS_ANPROPID_TXFN_COEFF[{pid - _TXFN_BASE}]"] = v
                elif pid == 0x11 and isinstance(v, str):
                    p.setdefault("DS_GEPROPID_AUTHOR_NOTE", v)
        if "DS_ACPROPID_PERIODS" not in p and "DS_ACPROPID_ACQ_TIME" in p:
            pass

    @staticmethod
    def _point_labels(ole):
        """Per-point axis labels ('Pt #001'): property ids (axis<<24)+10*point."""
        out = {}
        for name in ole.listdir():
            if not name.startswith("\x05"):
                continue
            try:
                props = parse_property_set(ole.read(name))
            except (struct.error, OleError):
                continue
            for pid, vt, v in props:
                if vt == 8 and pid >= 0x01000000 and isinstance(v, str):
                    out[(pid & 0xFFFFFF) // 10] = v
        return out
