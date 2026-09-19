"""PHI / ULVAC-PHI MultiPak ``.spe`` reader.

Layout (verified against PHI's own VAMAS exports of the same data): an ASCII
header ``SOFH ... EOFH`` of ``Key: value`` lines, then a binary section: a
16-byte preamble (version, n regions, total block-header bytes, preamble size),
one 96-byte block header per region, then each region's ``npts`` little-endian
float64 intensities back to back. Values are counts per second (PHI's VAMAS
export multiplies them by the time per step).
``SpectralRegDef: idx area name Z npts step start end start end time PE ...``
gives the binding-energy axis (start, negative step).
"""

from __future__ import annotations

import os
import re
import struct

from .base import Region, SpectrumFile, canon_region_name, kv_from_lines, read_bytes

PREAMBLE = 16
BLOCK_HEADER = 96            # bytes per region, all stored before the data


def sniff(head: bytes, ext: str) -> bool:
    return head[:4] == b"SOFH"


def _num(s, default=None):
    m = re.search(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?", s or "")
    return float(m.group(0)) if m else default


class PhiSpeFile(SpectrumFile):
    format_name = "PHI MultiPak (.spe)"

    def load(self, path: str):
        self.path = path
        data = read_bytes(path)
        end = data.find(b"EOFH")
        if end < 0:
            raise ValueError("PHI .spe header terminator (EOFH) not found")
        header = data[:end].decode("latin-1").replace("\r", "").split("\n")
        pos = end + 4
        while data[pos:pos + 1] in (b"\r", b"\n"):
            pos += 1
        kv = kv_from_lines([l for l in header if ":" in l])
        # keep original-case keys for a few multi-word values
        defs = []
        for line in header:
            if line.startswith("SpectralRegDef"):
                defs.append(line.split(":", 1)[1].split())
        if not defs:
            raise ValueError("no SpectralRegDef entries in the .spe header")
        n_areas = int(_num(kv.get("nospatialarea"), 1) or 1)
        n_regs = int(_num(kv.get("nospectralreg"), len(defs)) or len(defs))
        defs = defs[:n_regs]
        npts_all = [int(d[4]) for d in defs]
        tail = len(data) - pos
        expect = (PREAMBLE + BLOCK_HEADER * len(defs)
                  + sum(n * 8 for n in npts_all))
        if tail < expect:
            raise ValueError(f"binary section is {tail} bytes; expected "
                             f"{expect} for {len(defs)} region(s)")
        if tail > expect:
            self.warnings.append(
                f"{tail - expect} unexpected extra byte(s) after the spectra "
                f"(file has {n_areas} spatial area(s); only the first is read).")

        hv = _num(kv.get("xraysource"))
        power = _num(kv.get("xraypower"))
        wf = _num(kv.get("analyserworkfcn"))
        sample = ""
        if n_areas > 1:
            self.warnings.append("Several spatial areas: showing area 1 only.")
        date = kv.get("acqfiledate") or kv.get("filedate") or ""
        date = re.sub(r"^(\d{4}) (\d{2}) (\d{2})", r"\1-\2-\3", date)
        desc = kv.get("filedesc", "")

        cursor = pos + PREAMBLE + BLOCK_HEADER * len(defs)
        for idx, d in enumerate(defs):
            name, npts = d[2], int(d[4])
            step, start = float(d[5]), float(d[6])
            dwell = _num(d[10] if len(d) > 10 else None)
            pe = _num(d[11] if len(d) > 11 else None)
            counts = list(struct.unpack_from(f"<{npts}d", data, cursor))
            cursor += npts * 8
            energy = [start + i * step for i in range(npts)]
            reg = Region(
                name=canon_region_name(name), index=idx, offset=idx,
                technique=kv.get("technique", "XPS") or "XPS",
                energy=energy, counts=counts, energy_label="Binding Energy",
                energy_units="eV", count_label="Intensity",
                count_units="counts/s",
                decodable=True, sample=sample, photon_energy=hv,
                pass_energy=pe, dwell=dwell, step=abs(step) or None,
                date=date, anode=kv.get("xraysource", ""))
            if power:
                reg.conditions["X-ray Power"] = f"{power:g} W"
            reg.extra["header"] = kv
            self.regions.append(reg)

        instr = {"Instrument": kv.get("instrumentmodel", ""),
                 "Operator": kv.get("operator", ""),
                 "Institution": kv.get("institution", ""),
                 "X-ray source": kv.get("xraysource", "")}
        if wf:
            instr["Work function"] = f"{wf:g} eV"
        ne = _num(kv.get("neutralizerenergy"))
        if ne:
            instr["Charge neutraliser"] = (
                f"on, {kv.get('neutralizerenergy', '')}, "
                f"{kv.get('neutralizercurrent', '')}").strip(", ")
        sc = _num(kv.get("sputtercurrent"), 0)
        if sc:
            instr["Ion gun / sputtering"] = (
                f"{kv.get('sputterion', '')} {kv.get('sputterenergy', '')} "
                f"{kv.get('sputtercurrent', '')}").strip()
        if desc:
            instr["Sample description"] = desc
        self.instrument = {k: v for k, v in instr.items() if v}
        return self._finish()
