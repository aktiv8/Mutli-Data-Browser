"""Scienta Omicron SES ``.txt`` reader (INI-style text export).

Sections: ``[Info]`` (region count), then per region ``[Region n]`` (name,
``Dimension 1 name/size/scale``), ``[Info n]`` (excitation energy, pass energy,
step, step time, sweeps, lens mode, instrument, date/time, ...) and
``[Data n]`` (rows of ``x  y``; extra columns from angle-resolved / multi-slice
detector data are summed into one spectrum).
"""

from __future__ import annotations

import re

from .base import Region, SpectrumFile, canon_region_name, clean_text, read_bytes


def sniff(head: bytes, ext: str) -> bool:
    h = head[:400]
    return h.lstrip().startswith(b"[Info]") and b"Number of Regions" in h


def _float(s, default=None):
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return default


class ScientaTxtFile(SpectrumFile):
    format_name = "Scienta SES (.txt)"

    def load(self, path: str):
        self.path = path
        text = read_bytes(path).decode("latin-1")
        sections, order, cur = {}, [], None
        for raw in text.replace("\r", "").split("\n"):
            line = raw.strip()
            if not line:
                continue
            m = re.match(r"^\[(.+)\]$", line)
            if m:
                cur = m.group(1)
                sections[cur] = {"kv": {}, "rows": []}
                order.append(cur)
                continue
            if cur is None:
                continue
            if cur.startswith("Data"):
                try:
                    sections[cur]["rows"].append(
                        [float(t) for t in line.split()])
                except ValueError:
                    pass
            elif "=" in line:
                k, v = line.split("=", 1)
                sections[cur]["kv"][k.strip()] = v.strip()

        n_declared = int(_float(sections.get("Info", {}).get("kv", {})
                                .get("Number of Regions"), 0) or 0)
        idxs = sorted(int(m.group(1)) for k in sections
                      for m in [re.match(r"^Region (\d+)$", k)] if m)
        if not idxs:
            raise ValueError("no [Region n] sections found")
        if n_declared and n_declared != len(idxs):
            self.warnings.append(f"Header declares {n_declared} regions but "
                                 f"{len(idxs)} were found.")
        first_info = {}
        for n in idxs:
            reg_kv = sections[f"Region {n}"]["kv"]
            info = sections.get(f"Info {n}", {}).get("kv", {})
            rows = sections.get(f"Data {n}", {}).get("rows", [])
            first_info = first_info or info
            self._add_region(n, reg_kv, info, rows)
        self.instrument = {k: v for k, v in {
            "Instrument": clean_text(first_info.get("Instrument", "")),
            "Operator": clean_text(first_info.get("User", "")),
            "Institution": clean_text(first_info.get("Location", "")),
            "Lens mode": clean_text(first_info.get("Lens Mode", "")),
            "X-ray source": (f"{_float(first_info.get('Excitation Energy')):g} eV"
                             if _float(first_info.get("Excitation Energy"))
                             else ""),
        }.items() if v}
        return self._finish()

    def _add_region(self, n, reg_kv, info, rows):
        name = canon_region_name(reg_kv.get("Region Name") or info.get(
            "Region Name") or f"Region {n}")
        dim_name = reg_kv.get("Dimension 1 name", "")
        size = int(_float(reg_kv.get("Dimension 1 size"), 0) or 0)
        scale = [float(t) for t in reg_kv.get("Dimension 1 scale", "").split()
                 if _float(t) is not None]
        hv = _float(info.get("Excitation Energy"))
        note = ""
        cols = max((len(r) for r in rows), default=0)
        if cols >= 2:
            xs = [r[0] for r in rows]
            ys = [r[1] if cols == 2 else sum(r[1:]) for r in rows]
            if cols > 2:
                note = f"Detector data ({cols - 1} channels) summed to a spectrum."
        else:
            xs, ys = scale, []
        native = scale if len(scale) == len(xs) and scale else xs
        ok = bool(ys) and len(ys) == len(native)
        if "kinetic" in dim_name.lower() and hv:
            energy, label = [hv - x for x in native], "Binding Energy"
        elif "kinetic" in dim_name.lower():
            energy, label = native, "Kinetic Energy"
        else:
            energy, label = native, ("Binding Energy"
                                     if "binding" in dim_name.lower()
                                     else (dim_name.split("[")[0].strip()
                                           or "Energy"))
        step = _float(info.get("Energy Step"))
        step_ms = _float(info.get("Step Time"))
        date = " ".join(x for x in (info.get("Date", ""), info.get("Time", ""))
                        if x)
        reg = Region(
            name=name, index=n - 1, offset=n, technique="XPS",
            energy=energy if ok else None, counts=ys if ok else None,
            energy_label=label, energy_units="eV", count_label="Intensity",
            count_units="counts/s" if False else "counts",
            decodable=ok, note=note or ("" if ok else "No data rows."),
            sample=clean_text(info.get("Sample", "")), photon_energy=hv,
            pass_energy=_float(info.get("Pass Energy")),
            dwell=(step_ms / 1000.0) if step_ms else None, step=step,
            lens_mode=clean_text(info.get("Lens Mode", "")), date=date)
        sweeps = info.get("Number of Sweeps")
        if sweeps:
            reg.conditions["Sweeps"] = sweeps
        reg.extra["info"] = info
        self.regions.append(reg)
