"""Kratos Vision ``.kal`` reader (ASCII "dump_dataset" text).

A ``.kal`` file holds one or more objects, each introduced by
``Object name = ...`` and made of numbered ``id Name = value`` fields
(``3 Spectrum scan start``, ``4 step size``, ``12 Ordinate values = {...}``,
``42 Pass energy``, ``3113/3114`` chemical symbol / transition, the
``Transmission Function (ke,t)`` lists, ...). The abscissa is kinetic energy;
binding energy = anode energy - KE.
"""

from __future__ import annotations

import re

from .base import (Region, SpectrumFile, canon_region_name, guess_region_name,
                   read_bytes)

# X-ray line energies (eV) by the anode named in Kratos flags
_ANODES = {"AL": 1486.6, "MG": 1253.6, "AG": 2984.2, "ZR": 2042.4,
           "TI": 4510.9, "CR": 5414.7}
_FIELD_RE = re.compile(r"^\s*(\d+)\s+(.+?)\s*=\s*(.*)$")


def sniff(head: bytes, ext: str) -> bool:
    return head.lstrip().startswith(b"Dataset filename") and b"Object name" in head


def _num(s, default=None):
    m = re.search(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?", s or "")
    return float(m.group(0)) if m else default


def _list(value):
    body = value.strip().lstrip("{").rstrip("}")
    return [float(t) for t in re.findall(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?", body)]


def _date(s):
    m = re.match(r"^(\d{2})/(\d{2})/(\d{2})\s+(\d{2}:\d{2}:\d{2})", s or "")
    if not m:
        return (s or "").strip()
    yy = int(m.group(1))
    return f"{1900 + yy if yy >= 70 else 2000 + yy}-{m.group(2)}-{m.group(3)} {m.group(4)}"


class KratosKalFile(SpectrumFile):
    format_name = "Kratos Vision (.kal)"

    def load(self, path: str):
        self.path = path
        text = read_bytes(path).decode("latin-1").replace("\r", "")
        objects, cur, pending = [], None, None
        for line in text.split("\n"):
            if pending is not None:                    # multi-line { ... } list
                pending[1].append(line)
                if "}" in line:
                    cur[pending[0]] = " ".join(pending[1])
                    pending = None
                continue
            if line.startswith("Dataset filename"):
                self._dataset = line.split("=", 1)[1].strip()
                continue
            if line.startswith("Object name"):
                cur = {"_object": line.split("=", 1)[1].strip()}
                objects.append(cur)
                continue
            m = _FIELD_RE.match(line)
            if not m or cur is None:
                continue
            key, val = m.group(2).strip(), m.group(3).strip()
            if val == "{":                             # container: ignore
                continue
            if val.startswith("{") and "}" not in val:
                pending = (key, [val])
                continue
            cur[key] = val
        if not objects:
            raise ValueError("no 'Object name' entries found")
        first = objects[0]
        for i, o in enumerate(objects):
            self._add_object(i, o)
        anode = self._anode(first)
        self.instrument = {k: v for k, v in {
            "Instrument": "Kratos (Vision)",
            "X-ray source": (f"{anode[0]} ({anode[1]:g} eV)" if anode else ""),
            "Lens mode": first.get("HSA Lens Mode", "").replace(
                "F_HSA_LENS_", "").title(),
        }.items() if v}
        return self._finish()

    @staticmethod
    def _anode(o):
        for key in ("Xray Reference Energy", "Xray Gun Anode"):
            v = o.get(key, "")
            for sym, e in _ANODES.items():
                if re.search(rf"(_|^){sym}(_|$)", v.upper()):
                    return f"{sym.title()} anode", e
        return None

    def _add_object(self, idx, o):
        vals = _list(o.get("Ordinate values", ""))
        start = _num(o.get("Spectrum scan start"))
        step = _num(o.get("Spectrum scan step size"))
        n = len(vals)
        if not vals or start is None or step is None:
            if "SPECTRUM" in o.get("Scan type", "").upper():
                self.warnings.append(
                    f"Object {o['_object']}: no spectrum data.")
            return                       # snapshots, counters, positions, ...
        native = [start + i * step for i in range(n)]
        anode = self._anode(o)
        hv = anode[1] if anode else None
        label = o.get("Abscissa label", "Kinetic Energy")
        if "kinetic" in label.lower() and hv:
            energy, e_label = [hv - ke for ke in native], "Binding Energy"
        else:
            energy, e_label = native, label
            if "kinetic" in label.lower():
                self.warnings.append(
                    f"{o['_object']}: X-ray energy unknown; kinetic-energy axis.")
        name = guess_region_name(canon_region_name(
            f"{o.get('Chemical symbol or formula', '')} "
            f"{o.get('Transition or charge state', '')}".strip()
            or o["_object"]), energy)
        reg = Region(
            name=name, index=idx, offset=idx, technique="XPS",
            energy=energy, counts=vals, energy_label=e_label, energy_units="eV",
            count_label="Intensity",
            count_units=o.get("Ordinate units", "counts").lower(),
            decodable=True, sample=o.get("Acquisition name", o["_object"]),
            photon_energy=hv, pass_energy=_num(o.get("Pass energy")),
            dwell=_num(o.get("Dwell time")), step=abs(step) or None,
            lens_mode=o.get("HSA Lens Mode", "").replace("F_HSA_LENS_",
                                                          "").title(),
            date=_date(o.get("Date Acquired", "")),
            anode=anode[0] if anode else "")
        cur, volt = _num(o.get("Xray Gun current")), _num(o.get("Xray Gun voltage"))
        if cur and volt:
            reg.conditions["X-ray Power"] = f"{cur * volt:g} W"
        tk_, tv = (_list(o.get("Transmission Function Kinetic Energy", "")),
                   _list(o.get("Transmission Function Value", "")))
        if tk_ and len(tk_) == len(tv):
            reg.tf_ke, reg.tf_values = tk_, tv
        sw = o.get("# Sweeps completed")
        if sw:
            reg.conditions["Sweeps"] = sw
        reg.extra["fields"] = o
        self.regions.append(reg)
