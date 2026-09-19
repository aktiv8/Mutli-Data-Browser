"""VAMAS / ISO 14976 reader (any instrument or vendor).

The file is a strict sequence of one-item-per-line fields whose layout depends
on the experiment mode and technique, so it is parsed field by field in the
order the standard defines (not by fixed line offsets). Vendor extras are
mined from the comment lines: PHI ``SOFH`` headers, CasaXPS ``Casa Info``
blocks, SPECS "Created with: MATRIX", Kratos strings, etc.
"""

from __future__ import annotations

import os
import re

from .base import (Region, SpectrumFile, clean, clean_text, canon_region_name,
                   guess_region_name, unset, kv_from_lines,
                   read_bytes)

HEADER_ID = b"VAMAS Surface Chemical Analysis Standard Data Transfer Format"


class VamasError(Exception):
    pass


class _Lines:
    """Sequential one-item-per-line reader."""

    def __init__(self, lines):
        self.lines = lines
        self.i = 0

    def s(self) -> str:
        if self.i >= len(self.lines):
            raise VamasError("unexpected end of file")
        v = self.lines[self.i]
        self.i += 1
        return v.strip()

    def f(self) -> float:
        ln = self.i + 1
        t = self.s()
        try:
            return float(t)
        except ValueError:
            try:
                return float(t.replace("D", "E").replace("d", "e"))
            except ValueError:
                raise VamasError(f"line {ln}: expected a number, got {t!r}")

    def n(self) -> int:
        return int(round(self.f()))

    def peek_number(self) -> bool:
        """True if the next line parses as a number."""
        if self.i >= len(self.lines):
            return False
        t = self.lines[self.i].strip()
        try:
            float(t.replace("D", "E").replace("d", "e"))
            return True
        except ValueError:
            return False

    def numbers(self, count):
        """``count`` numeric tokens (normally one per line, but tolerate
        several per line)."""
        out = []
        while len(out) < count:
            if self.i >= len(self.lines):
                raise VamasError("data ends early")
            for tok in self.lines[self.i].split():
                try:
                    out.append(float(tok))
                except ValueError:
                    out.append(float(tok.replace("D", "E").replace("d", "e")))
            self.i += 1
        if len(out) > count:
            raise VamasError("more values than declared on the last data line")
        return out


def sniff(head: bytes, ext: str) -> bool:
    return HEADER_ID in head[:400]


class VamasFile(SpectrumFile):
    format_name = "VAMAS (ISO 14976)"

    # -- public ---------------------------------------------------------
    def load(self, path: str):
        self.path = path
        raw = read_bytes(path)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")
        first_line = next((l for l in lines if l.strip()), "")
        if not first_line.strip().upper().startswith("VAMAS"):
            raise VamasError("not a VAMAS file")
        # Some experiment modes (e.g. SDPSV) omit "number of spectral
        # regions": try the expected layout first, then the alternatives.
        best, first_exc = None, None
        for has_regions in (None, True, False):
            try:
                rd = _Lines(lines)
                hdr = self._read_header(rd, has_regions)
            except VamasError as exc:
                first_exc = first_exc or exc
                continue
            blocks, err = [], None
            for k in range(hdr["n_blocks"]):
                try:
                    blocks.append(self._read_block(rd, hdr))
                except VamasError as exc:
                    err = (k, exc)
                    break
            if best is None or len(blocks) > len(best[1]):
                best = (hdr, blocks, err, rd.i)
            if err is None:
                break
        if best is None or not best[1]:
            raise first_exc or (best[2][1] if best and best[2] else
                                VamasError("no blocks could be read"))
        hdr, blocks, err, end_i = best
        if err is not None:
            self.warnings.append(
                f"Read {len(blocks)} of {hdr['n_blocks']} blocks; stopped at "
                f"block {err[0] + 1}: {err[1]}")
        left = [l.strip() for l in lines[end_i:] if l.strip()]
        if err is None and left and not all(
                l.lower().startswith("end of") for l in left):
            self.warnings.append(f"{len(left)} unread line(s) after the last "
                                 "block.")
        self.hdr = hdr
        self._file_kv = kv_from_lines(hdr["comments"])
        self._build_from_blocks(hdr, blocks)
        return self._finish()

    # -- header ---------------------------------------------------------
    def _read_header(self, rd, has_regions=None):
        ident = rd.s()
        if not ident.upper().startswith("VAMAS"):
            raise VamasError("not a VAMAS file")
        h = {"format": ident, "institution": rd.s(), "instrument": rd.s(),
             "operator": rd.s(), "experiment_id": rd.s()}
        ncom = rd.n()
        h["comments"] = [rd.s() for _ in range(ncom)]
        h["mode"] = rd.s().upper()
        h["scan"] = rd.s().upper()
        if has_regions is None:
            has_regions = h["mode"] in ("NORM", "SDP", "MAP", "MAPDP")
        h["has_regions"] = has_regions
        h["n_regions"] = rd.n() if has_regions else 0
        if h["mode"] in ("MAP", "MAPDP"):
            h["n_positions"] = rd.n()
            h["n_x"] = rd.n()
            h["n_y"] = rd.n()
        nv = rd.n()
        h["expvars"] = [(rd.s(), rd.s()) for _ in range(nv)]
        h["incl"] = [rd.s() for _ in range(abs(rd.n()))]
        h["manual"] = [rd.s() for _ in range(abs(rd.n()))]
        h["future_exp"] = [rd.s() for _ in range(rd.n())]
        h["n_future_block"] = rd.n()
        h["n_blocks"] = rd.n()
        return h

    # -- one block ------------------------------------------------------
    def _read_block(self, rd, h):
        b = {}
        mode = h["mode"]
        b["id"] = rd.s()
        b["sample"] = rd.s()
        y, mo, d, hh, mi, ss = (rd.n() for _ in range(6))
        b["gmt"] = rd.n()
        b["date"] = (f"{y:04d}-{mo:02d}-{d:02d} {hh:02d}:{mi:02d}:{ss:02d}"
                     if y else "")
        b["comments"] = [rd.s() for _ in range(rd.n())]
        b["technique"] = rd.s()
        tech = b["technique"].upper()
        if mode in ("MAP", "MAPDP"):
            b["x"], b["y"] = rd.f(), rd.f()
        b["expvals"] = [rd.f() for _ in h["expvars"]]
        b["source_label"] = rd.s()
        # hv, strength, beam width x/y, [mode-specific extras], polar, azimuth:
        # the count of extras varies by experiment mode, but the analyser
        # mode that follows is always text, so read numbers until it appears.
        nums = []
        while rd.peek_number():
            nums.append(rd.f())
        if len(nums) < 6:
            raise VamasError("source/geometry fields are shorter than expected")
        b["hv"], b["source_strength"] = nums[0], nums[1]
        b["beam_x"], b["beam_y"] = nums[2], nums[3]
        b["polar"], b["azimuth"] = nums[-2], nums[-1]
        b["analyser_mode"] = rd.s()
        b["pass"] = rd.f()
        if tech.startswith("AES DIFF"):
            b["diff_width"] = rd.f()
        b["magnification"] = rd.f()
        b["work_function"] = rd.f()
        b["bias"] = rd.f()
        b["an_width_x"], b["an_width_y"] = rd.f(), rd.f()
        b["takeoff_polar"], b["takeoff_az"] = rd.f(), rd.f()
        b["species"] = rd.s()
        b["transition"] = rd.s()
        b["charge"] = rd.n()
        if h["scan"] == "IRREGULAR":
            # no start/step: the first corresponding variable is the abscissa
            b["abs_label"] = b["abs_units"] = ""
            b["start"] = b["step"] = 0.0
        else:
            b["abs_label"] = rd.s()
            b["abs_units"] = rd.s()
            b["start"] = rd.f()
            b["step"] = rd.f()
        ncv = rd.n()
        if ncv < 1:
            raise VamasError("block declares no corresponding variables")
        b["cvars"] = [(rd.s(), rd.s()) for _ in range(ncv)]
        b["signal_mode"] = rd.s()
        b["collect_time"] = rd.f()
        b["n_scans"] = rd.n()
        b["time_corr"] = rd.f()
        if mode in ("SDP", "SDPSV", "MAPDP", "MAPSVDP"):
            b["sputter"] = [rd.f() for _ in range(6)] + [rd.s()]
        b["tilt"], b["tilt_az"], b["rotation"] = rd.f(), rd.f(), rd.f()
        b["extra_params"] = [(rd.s(), rd.s(), rd.f())
                             for _ in range(rd.n())]
        b["future"] = [rd.s() for _ in range(h["n_future_block"])]
        nord = rd.n()
        b["minmax"] = [(rd.f(), rd.f()) for _ in range(ncv)]
        b["values"] = rd.numbers(nord)
        b["nord"] = nord
        return b

    # -- blocks -> regions ---------------------------------------------
    def _build_from_blocks(self, h, blocks):
        instr = {
            "Instrument": clean_text(h["instrument"]),
            "Operator": clean_text(h["operator"]),
            "Institution": clean_text(h["institution"]),
            "Experiment ID": clean_text(h["experiment_id"]),
        }
        if not self.regions:
            self.regions = []
        counts = {}
        for i, b in enumerate(blocks):
            r = self._region_from_block(i, b, h)
            if r is not None:
                self.regions.append(r)
                counts[(r.sample, r.name)] = counts.get((r.sample, r.name), 0) + 1
        first = next((b for b in blocks if not unset(b["hv"])), None)
        if first is not None:
            instr["X-ray source"] = self._source_text(first)
        for k in ("Lens mode", "Aperture", "Charge neutraliser",
                  "Ion gun / sputtering"):
            v = self._lookup(k)
            if v:
                instr[k] = v
        self.instrument = {k: v for k, v in instr.items() if v}
        self._detect_profile(h, blocks, counts)
        self._positions_from_comments(blocks)

    @staticmethod
    def _source_text(b):
        lab = clean_text(b["source_label"])
        hv = clean(b["hv"])
        if lab and hv:
            return f"{lab} ({hv:g} eV)"
        return lab or (f"{hv:g} eV" if hv else "")

    def _region_from_block(self, idx, b, h):
        ncv = len(b["cvars"])
        vals = b["values"]
        if len(vals) % ncv:
            raise VamasError(f"block {idx + 1}: {len(vals)} values do not "
                             f"divide into {ncv} columns")
        npts = len(vals) // ncv
        cols = [vals[k::ncv] for k in range(ncv)]
        cvars = list(b["cvars"])
        if h["scan"] == "IRREGULAR":
            # the first corresponding variable is the abscissa
            native = cols[0]
            b = dict(b, abs_label=cvars[0][0], abs_units=cvars[0][1])
            cols, cvars = cols[1:], cvars[1:]
            ncv -= 1
            if ncv < 1:
                raise VamasError(f"block {idx + 1}: irregular block has no "
                                 "ordinate variable")
        else:
            step = b["step"] if not unset(b["step"]) else 0.0
            native = [b["start"] + i * step for i in range(npts)]
        label = clean_text(b["abs_label"])
        units = clean_text(b["abs_units"]) or "eV"
        hv = clean(b["hv"])
        tech = (clean_text(b["technique"]) or "XPS")
        is_ke = "kinetic" in label.lower()
        r_label, r_units, tf_ke = label or "Energy", units, None
        energy = native
        if is_ke:
            tf_ke = native
            if hv and tech.upper() in ("XPS", "UPS") and units.lower() == "ev":
                energy = [hv - ke for ke in native]
                r_label = "Binding Energy"
        elif "binding" in label.lower():
            r_label = "Binding Energy"
        elif label.lower() in ("", "energy") and native and max(native) <= 0:
            # text-imported spectra: unlabelled axis holding negative values
            # with hv = 0 (CasaXPS convention: BE = hv - x = -x)
            energy = [-x for x in native]
            r_label, r_units = "Binding Energy", "eV"
        # corresponding variables: first = intensity; "transmission" kept
        c_label, c_unit = cvars[0]
        counts = cols[0]
        tf_vals = None
        for k in range(1, ncv):
            if "transmission" in cvars[k][0].lower():
                tf_vals = cols[k]
        name = guess_region_name(self._region_name(b), energy)
        if "energy" not in r_label.lower():
            name = f"{name} vs {r_label}"      # e.g. quantification vs etch time
        r = Region(
            name=name, index=idx, offset=idx, technique=tech,
            energy=energy if npts else None, counts=counts if npts else None,
            energy_label=r_label, energy_units=r_units,
            count_label=clean_text(c_label) or "Intensity",
            count_units=self._count_units(c_label, c_unit),
            decodable=npts > 0,
            note="" if npts else "Block contains no data points.",
            sample=clean_text(b["sample"]),
            photon_energy=hv,
            pass_energy=clean(b["pass"]),
            dwell=clean(b["collect_time"]),
            step=abs(b["step"]) if not unset(b["step"]) and b["step"] else None,
            date=b["date"], anode=clean_text(b["source_label"]),
        )
        st = clean(b["source_strength"])
        if st:
            r.conditions["X-ray Power"] = f"{st:g} W"
        if tf_vals and tf_ke and len(tf_vals) == len(tf_ke):
            r.tf_ke, r.tf_values = list(tf_ke), list(tf_vals)
        # vendor extras from the block comments
        kv = kv_from_lines(b["comments"])
        r.extra["comments"] = kv
        r.lens_mode = self._lookup("Lens mode", kv)
        r.aperture = self._lookup("Aperture", kv)
        r.extra["expvals"] = list(zip([v[0] for v in h["expvars"]],
                                      b["expvals"]))
        return r

    @staticmethod
    def _count_units(label, unit):
        u = clean_text(unit)
        if u and u.lower() not in ("d", "dimensionless"):
            return u
        return "counts" if "count" in (label or "").lower() else "arb."

    @staticmethod
    def _region_name(b):
        sp = clean_text(b["species"])
        tr = clean_text(b["transition"])
        if sp and tr and tr.lower() not in sp.lower():
            return canon_region_name(f"{sp} {tr}")
        if sp:
            return canon_region_name(sp)
        return canon_region_name(clean_text(b["id"])) or "Region"

    # -- comment mining --------------------------------------------------
    _KEYS = {
        "Lens mode": ("lens mode", "lensmode", "lens"),
        "Aperture": ("aperture", "aperture slot", "entrance slit", "slit"),
        "Charge neutraliser": ("c/n", "charge neutraliser", "charge neutralizer",
                               "neutralizerenergy", "neutralizer", "flood gun"),
        "Ion gun / sputtering": ("sputterion", "ion gun", "sputter"),
    }

    def _lookup(self, key, kv=None):
        src = kv if kv is not None else self._file_kv
        for alias in self._KEYS.get(key, (key.lower(),)):
            if alias in src and src[alias]:
                val = src[alias]
                if key == "Charge neutraliser" and alias == "neutralizerenergy":
                    cur = src.get("neutralizercurrent", "")
                    return f"on, {val}" + (f", {cur}" if cur else "")
                if key == "Ion gun / sputtering" and alias == "sputterion":
                    en = src.get("sputterenergy", "")
                    return f"{val}" + (f" {en}" if en else "")
                return val
        return ""

    def _positions_from_comments(self, blocks):
        """PHI-style ``StagePosition: x y z ...`` (mm) per sample."""
        pos = {}
        kvs = [self._file_kv] + [r.extra.get("comments", {})
                                 for r in self.regions]
        for kv in kvs:
            nums = re.findall(r"-?\d+\.?\d*", kv.get("stageposition", ""))
            if len(nums) >= 2:
                for r in self.regions:
                    if r.sample:
                        pos.setdefault(r.sample,
                                       (float(nums[0]), float(nums[1])))
                break
        self._sample_pos = pos
        for r in self.regions:
            if r.sample in pos:
                r.pos_x, r.pos_y = pos[r.sample]

    # -- depth profile ---------------------------------------------------
    def _detect_profile(self, h, blocks, counts):
        if not counts or max(counts.values()) < 3:
            return
        names, levels = [], {}
        for r in self.regions:
            if r.name not in names:
                names.append(r.name)
            k = (r.sample, r.name)
            levels[k] = levels.get(k, -1) + 1
            r.etch_level = levels[k]
        ev_label = ""
        for r in self.regions:
            for lab, val in r.extra.get("expvals", []):
                if re.search(r"etch|sputter|time|depth", lab, re.I) \
                        and not unset(val):
                    ev_label = lab
                    unit = next((u for (n, u) in h["expvars"] if n == lab), "")
                    scale = 60.0 if unit.lower().startswith("min") else 1.0
                    r.etch_time = val * scale
        n_levels = max(levels.values()) + 1
        times = sorted({r.etch_time for r in self.regions
                        if r.etch_time is not None})
        self.depth_profile = {
            "is_profile": True, "n_levels": n_levels,
            "regions_per_level": len(names),
            "etch_per_level": (times[1] - times[0]) if len(times) > 1 else 0.0,
            "total_etch_time": times[-1] if times else 0.0,
            "cumulative": times,
            "etch_source": (f"experimental variable '{ev_label}'" if ev_label
                            else "repeated blocks (no etch time in file)"),
        }
