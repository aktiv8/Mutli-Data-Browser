"""Reader for Kratos ESCApe ``.experiment`` files (undocumented binary
container; reverse-engineered, best effort)."""

from __future__ import annotations

import os
import re
import struct
import datetime
from typing import Optional

from .base import Region, ImageBlob, TreeNode, SpectrumFile


class EscapeParser(SpectrumFile):
    format_name = "Kratos ESCApe (.experiment)"

    UTF8_REPL = b"\xef\xbf\xbd"
    SPECTRUM_MARKER = b"DataTypes.EscaSpectrum"
    RESULT_MARKER = b"ProcessData.ProcessResult"
    IMAGE_MARKER = b"DataTypes.HolderContentSnapshotData"
    SAMPLE_MARKER = b"ProcessData.SampleAnalysis"
    SETTINGS_MARKER = b"NICPU.Acquisition.Spectrum.SpectroscopySettings"
    LOCATION_MARKER = b"SampleHandling.InstrumentAnalysisLocation"
    PASS_ENERGIES = (2, 5, 10, 20, 40, 80, 160, 224, 280)

    def __init__(self):
        super().__init__()
        self.path = None
        self.raw = b""
        self.strings: list = []
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

    # -- public ---------------------------------------------------------
    def load(self, path: str):
        with open(path, "rb") as fh:
            self.raw = fh.read()
        self.path = path
        self._check_corruption()
        self._scan_strings()
        self._parse_samples()
        self._parse_instrument()
        self._parse_regions()
        for r in self.regions:
            r.source = os.path.basename(path)
        self._parse_positions()
        self._parse_depth_profile()
        self._parse_images()
        self._build_tree()
        self._build_summary()
        return self

    # -- corruption -----------------------------------------------------
    def _check_corruption(self):
        raw, n = self.raw, len(self.raw)
        repl = raw.count(self.UTF8_REPL)
        frac = (3 * repl) / n if n else 0.0
        no_ff = b"\xff" not in raw
        no_nul = b"\x00" not in raw
        corrupted = repl > 50 and (no_ff or no_nul)
        msg = ""
        if corrupted:
            msg = (
                "This file has been damaged by a UTF-8 text round-trip: "
                f"{repl:,} replacement characters cover about {frac * 100:.0f}% "
                "of the file. The numeric spectra and the camera image cannot "
                "be recovered from it — the original bytes are irreversibly "
                "lost. The experiment structure and acquisition settings are "
                "still readable.\n\nTo recover the data, re-export the "
                ".experiment file from ESCApe and transfer it in binary mode "
                "(for example, put it in a .zip first)."
            )
        self.corruption = {"corrupted": corrupted, "repl_count": repl,
                           "repl_fraction": frac, "message": msg}

    # -- strings --------------------------------------------------------
    def _scan_strings(self):
        raw, i, out, n = self.raw, 0, [], len(self.raw)
        while i < n - 1:
            ln = raw[i]
            if 4 <= ln <= 120:
                chunk = raw[i + 1: i + 1 + ln]
                if len(chunk) == ln and all(32 <= b < 127 for b in chunk):
                    out.append((i, chunk.decode("ascii")))
                    i += 1 + ln
                    continue
            i += 1
        self.strings = out

    def _strings_between(self, lo, hi):
        return [(o, s) for (o, s) in self.strings if lo <= o < hi]

    def _find_all(self, marker):
        offs, start = [], 0
        while True:
            p = self.raw.find(marker, start)
            if p == -1:
                break
            offs.append(p)
            start = p + 1
        return offs

    # -- regions --------------------------------------------------------
    def _parse_regions(self):
        spec = self._find_all(self.SPECTRUM_MARKER)
        res = self._find_all(self.RESULT_MARKER)
        regions = []
        for idx, off in enumerate(spec):
            nxt = min([o for o in spec + res if o > off] + [len(self.raw)])
            regions.append(self._build_region(idx, off, nxt, res))
        self.regions = regions

    def _parse_samples(self):
        """Find each SampleAnalysis block and its sample identifier."""
        samples = []
        host_like = re.compile(r"^[0-9A-Z]+(-[0-9A-Z]+)+$")
        ignore = {"Analysis", "Spectroscopy", "Slot", "Hybrid", "Tilt"}
        for k, off in enumerate(self._find_all(self.SAMPLE_MARKER)):
            near = self._strings_between(off, off + 220)
            name = None
            for _, s in near:
                if ("." in s or "\\" in s or s in ignore or len(s) > 16
                        or host_like.match(s) or not any(c.isalnum() for c in s)):
                    continue
                name = s
                break
            samples.append((off, name or f"Sample {k + 1}"))
        self.samples = samples

    def _sample_for(self, offset: int) -> str:
        owners = [(o, n) for (o, n) in self.samples if o < offset]
        return owners[-1][1] if owners else (self.samples[0][1]
                                             if self.samples else "Sample")

    def _date_for(self, offset: int) -> str:
        dates = getattr(self, "dates", [])
        if not dates:
            return ""
        return min(dates, key=lambda od: abs(od[0] - offset))[1]

    # -- instrument-level metadata --------------------------------------
    @staticmethod
    def _anode_from_hv(hv):
        if hv is None:
            return ""
        table = [(1486.6, "Al K-alpha (monochromated)"),
                 (1253.6, "Mg K-alpha"),
                 (2984.3, "Ag L-alpha"),
                 (1740.0, "Si K-alpha")]
        for e, n in table:
            if abs(hv - e) < 3:
                return n
        return f"{hv:.1f} eV source"

    def _parse_instrument(self):
        raw = self.raw
        instrument = next((m.group().decode() for m in
                           [re.search(rb"MI-[A-Z0-9\-]+", raw)] if m), "")
        host = next((s for _, s in self.strings
                     if re.match(r"^[A-Za-z0-9\-]+$", s) and "-" in s
                     and not s.startswith("MI-")
                     and len(s) <= 14), "")
        neutraliser = b"AxisChargeNeutraliser" in raw
        ion_gun = any(t in raw for t in
                      (b"Sputter", b"IonGun", b"Ion Gun", b"Minibeam",
                       b"MiniBeam", b"GasCluster", b"Etch"))
        # acquisition dates (dd/mm/yyyy) with their byte offsets
        self.dates = [(m.start(), m.group().decode())
                      for m in re.finditer(rb"[0-3]?\d/[01]?\d/20\d\d", raw)]
        # source / lens / aperture: read from the first settings block
        source = lens = aperture = ""
        ss = self._find_all(self.SETTINGS_MARKER)
        if ss:
            tokens = self._settings_tokens(ss[0])
            aperture = tokens[0] if len(tokens) > 0 else ""
            lens = tokens[1] if len(tokens) > 1 else ""
            source = next((s for _, s in self._strings_between(
                ss[0], ss[0] + 120) if "monochrom" in s.lower()
                or "achromat" in s.lower()), "")
        self.instrument = {
            "Instrument": instrument or "(unknown)",
            "Acquisition computer": host or "(unknown)",
            "X-ray source": source or "(unknown)",
            "Lens mode": lens,
            "Aperture": aperture,
            "Charge neutraliser": "Yes" if neutraliser else "No",
            "Ion gun / sputtering": "Used" if ion_gun else "Not used",
        }

    def _settings_tokens(self, ss_off, span=60):
        """Short strings right after a SpectroscopySettings marker."""
        e = ss_off + len(self.SETTINGS_MARKER)
        out, j = [], e
        while j < e + span:
            n = self.raw[j]
            if 3 <= n <= 24:
                c = self.raw[j + 1: j + 1 + n]
                if len(c) == n and all(32 <= b < 127 for b in c):
                    out.append(c.decode())
                    j += 1 + n
                    continue
            j += 1
        return out

    def _pass_energy_for(self, es_off):
        ss = [o for o in self._find_all(self.SETTINGS_MARKER) if o < es_off]
        if not ss:
            return None
        e = ss[-1] + len(self.SETTINGS_MARKER)
        for k in range(0, 56):
            try:
                v = struct.unpack_from("<d", self.raw, e + k)[0]
            except struct.error:
                break
            if v in self.PASS_ENERGIES:
                return v
        return None

    def _settings_for(self, es_off):
        ss = [o for o in self._find_all(self.SETTINGS_MARKER) if o < es_off]
        if not ss:
            return "", ""
        toks = self._settings_tokens(ss[-1])
        ap = toks[0] if len(toks) > 0 else ""
        lens = toks[1] if len(toks) > 1 else ""
        return ap, lens

    def _build_region(self, idx, off, end, result_offsets):
        starts = [o for o in result_offsets if o < off]
        block_start = starts[-1] if starts else max(0, off - 400)
        hs = self._strings_between(block_start, off)
        reg = Region(name=self._guess_region_name(hs), index=idx, offset=off,
                     conditions=self._extract_conditions(hs))
        reg.sample = self._sample_for(off)
        reg.pass_energy = self._pass_energy_for(off)
        reg.aperture, reg.lens_mode = self._settings_for(off)
        self._decode_spectrum(reg, off, end)
        if reg.pass_energy is not None:
            reg.conditions.setdefault("Pass energy", f"{reg.pass_energy:g} eV")
        if reg.dwell is not None:
            reg.conditions.setdefault("Dwell time", f"{reg.dwell:.3g} s")
        return reg

    @staticmethod
    def _guess_region_name(hs):
        cands = [s for _, s in hs]
        pat = re.compile(r"^[A-Z][a-z]?\s?\d[spdf]\d?$|^[A-Z][a-z]? [A-Z]{2,3}$")
        for s in cands:
            if pat.match(s):
                return s
        for s in cands:
            if s.lower() in ("wide", "survey"):
                return s
        ignore = {"Spectroscopy", "Analysis"}
        for s in reversed(cands):
            if s not in ignore and "." not in s and "\\" not in s and len(s) <= 12:
                return s
        return "Region"

    @staticmethod
    def _extract_conditions(hs):
        cond, texts = {}, [s for _, s in hs]
        for i, s in enumerate(texts):
            if s == "X-ray Power" and i + 1 < len(texts):
                cond["X-ray Power"] = texts[i + 1]
            if s == "Quality" and i + 1 < len(texts):
                cond["Quality"] = texts[i + 1]
        return cond

    def _decode_spectrum(self, reg, off, end):
        """Populate reg.energy / reg.counts in place.

        Uses the real EscaSpectrum layout (photon energy + kinetic-energy
        range, then an int32 point count followed by N float64 ordinates).
        Falls back to a heuristic float scan if the structure isn't found.
        """
        if self.corruption["corrupted"]:
            reg.decodable = False
            reg.note = ("Numeric data not available — the binary payload is "
                        "corrupted (UTF-8 round-trip damage).")
            return

        if self._decode_structured(reg, off, end):
            return

        # Fallback: heuristic scan (last resort; energy axis is just an index)
        payload = self.raw[off + len(self.SPECTRUM_MARKER): end]
        for fmt, size in (("<d", 8), ("<f", 4)):
            arr = self._scan_float_array(payload, fmt, size)
            if arr is not None:
                reg.energy = list(range(len(arr)))
                reg.counts = arr
                reg.energy_label, reg.energy_units = "Point", "index"
                reg.decodable = True
                reg.note = ("Structured header not found; spectrum recovered "
                            "heuristically with an index axis (no energy "
                            "calibration). Verify against a known-good export.")
                return
        reg.decodable = False
        reg.note = "Spectrum payload present but could not be decoded."

    def _decode_structured(self, reg, off, end):
        """Decode one EscaSpectrum block using the known layout. -> bool."""
        try:
            d = lambda o: struct.unpack_from("<d", self.raw, o)[0]
            i32 = lambda o: struct.unpack_from("<i", self.raw, o)[0]

            # Energy-axis doubles follow the "Uninitialized" tag.
            u = self.raw.find(b"Uninitialized", off, end)
            if u == -1:
                return False
            ue = u + len(b"Uninitialized")
            hv = d(ue)            # photon energy (e.g. 1486.69 eV, Al Ka)
            ke_a = d(ue + 8)      # kinetic-energy start
            ke_b = d(ue + 16)     # kinetic-energy end
            dwell = d(ue + 24)    # dwell time per step (seconds)
            if not (50.0 < hv < 6000.0 and 0.0 <= ke_a < hv + 50
                    and 0.0 <= ke_b < hv + 50):
                return False

            # Transmission function, then the point count + ordinates.
            tf = self.raw.find(self.TF_MARKER, off, end)
            if tf == -1:
                return False
            vend = tf + len(self.TF_MARKER)
            npairs = i32(vend + 4)
            if not (0 <= npairs < 100000):
                return False
            # Each pair is (kinetic energy, transmission), 2 x float64.
            tf_ke, tf_val = [], []
            for k in range(npairs):
                tf_ke.append(d(vend + 8 + k * 16))
                tf_val.append(d(vend + 8 + 8 + k * 16))
            tf_end = vend + 8 + npairs * 16
            n = i32(tf_end)
            if not (1 < n < 5_000_000):
                return False
            cstart = tf_end + 4
            avail = (end - cstart) // 8
            n = min(n, avail)
            if n < 2:
                return False
            counts = list(struct.unpack_from(f"<{n}d", self.raw, cstart))

            # Binding-energy axis: BE = photon energy - kinetic energy.
            ke = [ke_a + (ke_b - ke_a) * j / (n - 1) for j in range(n)]
            energy = [hv - k for k in ke]

            reg.energy = energy
            reg.counts = counts
            reg.energy_label, reg.energy_units = "Binding Energy", "eV"
            reg.count_label, reg.count_units = "Intensity", "counts"
            reg.decodable = True
            step = (ke_b - ke_a) / (n - 1)
            reg.photon_energy = hv
            reg.anode = self._anode_from_hv(hv)
            reg.dwell = dwell if (dwell == dwell and 0 < dwell < 1e4) else None
            reg.step = abs(step)
            reg.tf_ke = tf_ke
            reg.tf_values = tf_val
            reg.conditions.setdefault("Photon energy", f"{hv:.2f} eV")
            reg.conditions.setdefault("Anode", reg.anode)
            reg.conditions.setdefault(
                "BE range", f"{energy[0]:.1f} - {energy[-1]:.1f} eV")
            reg.conditions.setdefault("Step", f"{abs(step):.3f} eV")
            reg.conditions.setdefault("Points", str(n))
            reg.note = ("Decoded from the EscaSpectrum structure. Binding "
                        "energy = photon energy − kinetic energy; not "
                        "charge-corrected.")
            return True
        except (struct.error, IndexError, ZeroDivisionError):
            return False

    TF_MARKER = b"TransFunc.Core.VisionTf"

    @staticmethod
    def _scan_float_array(payload, fmt, size):
        n, best = len(payload), []
        for phase in range(size):
            cur = []
            for i in range(phase, n - size, size):
                try:
                    v = struct.unpack(fmt, payload[i: i + size])[0]
                except struct.error:
                    v = float("nan")
                if (v == v) and (0.0 <= v < 1e9):
                    cur.append(v)
                else:
                    if len(cur) > len(best):
                        best = cur
                    cur = []
            if len(cur) > len(best):
                best = cur
        if len(best) >= 64 and len(set(round(x, 3) for x in best)) > 10:
            return best
        return None

    # -- images ---------------------------------------------------------
    # -- depth profile --------------------------------------------------
    GRAPH_MARKER = b"DataTypes.NonUniformGraphData"

    def _decode_duration_graph(self, off):
        """Decode (etch number, duration) pairs from a NonUniformGraphData
        block. Returns the list of per-etch durations (best effort)."""
        e = off + len(self.GRAPH_MARKER)
        base = self.raw.find(struct.pack("<d", 1.0), e, e + 220)
        if base < 0:
            return []
        d = lambda o: struct.unpack_from("<d", self.raw, o)[0]
        result = []
        for stride in (17, 16):
            ys, k = [], 0
            while True:
                ox = base + k * stride
                if ox + 16 > len(self.raw):
                    break
                try:
                    x = d(ox); y = d(ox + 8)
                except struct.error:
                    break
                if x != x or abs(x - (k + 1)) > 0.01:
                    break
                ys.append(y)
                k += 1
            if len(ys) >= 2:
                result = ys
                break
        return result

    def _parse_depth_profile(self):
        raw = self.raw
        is_profile = (b"DepthProfileData" in raw or b"Depth Profile" in raw
                      or b"Mb6EtchSettings" in raw)
        if not is_profile or not self.regions:
            return

        names = [r.name for r in self.regions]
        rpl = next((i for i in range(1, len(names))
                    if names[i] == names[0]), len(names))
        if rpl < 1 or len(names) % rpl != 0:
            rpl = 1
        n_levels = len(self.regions) // rpl

        durs = []
        for off in self._find_all(self.GRAPH_MARKER):
            labels = [s for _, s in self._strings_between(off, off + 60)]
            if any("Duration" in s for s in labels):
                durs += self._decode_duration_graph(off)

        n_etches = max(0, n_levels - 1)
        per_etch, source = [], ""
        if durs:
            import statistics
            med = statistics.median(durs)
            constant = all(abs(x - med) <= 0.01 * med + 1e-9 for x in durs)
            if constant:
                per_etch = [med] * n_etches
                source = f"constant {med:g} s/etch (from instrument record)"
            else:
                per_etch = list(durs)
                if len(per_etch) < n_etches:
                    per_etch += [per_etch[-1]] * (n_etches - len(per_etch))
                per_etch = per_etch[:n_etches]
                source = "per-etch durations (from instrument record)"
        else:
            per_etch = [0.0] * n_etches
            source = "etch time not recorded in file"

        cumulative = [0.0]
        for dd in per_etch:
            cumulative.append(cumulative[-1] + dd)

        for idx, r in enumerate(self.regions):
            lvl = idx // rpl
            r.etch_level = lvl
            r.etch_time = cumulative[lvl] if lvl < len(cumulative) else None

        # the etch settings name the beam, e.g. "5 keV Ar+"
        import sputter
        m = re.search(rb"(\d+(?:\.\d+)?)\s?keV\s+([A-Za-z][A-Za-z0-9]*\+)",
                      raw)
        if m:
            self.sputter_hint = sputter.from_text(
                f"{m.group(1).decode()} keV {m.group(2).decode()}")

        self.depth_profile = {
            "is_profile": True,
            "n_levels": n_levels,
            "regions_per_level": rpl,
            "etch_per_level": (per_etch[0] if per_etch else 0.0),
            "total_etch_time": cumulative[-1] if cumulative else 0.0,
            "cumulative": cumulative,
            "etch_source": source,
            "n_etches": n_etches,
        }

    # -- analysis positions --------------------------------------------
    def _parse_positions(self):
        """Extract stage analysis positions (mm) from InstrumentAnalysisLocation
        blocks. Each stores two consecutive float64 (metres). The first block
        for each sample gives that sample's analysis position (later blocks are
        auto-Z / alignment points)."""
        d = lambda o: struct.unpack_from("<d", self.raw, o)[0]
        rep = {}
        loc = []
        if self.corruption["corrupted"]:
            self._locations, self._sample_pos = [], {}
            return
        for off in self._find_all(self.LOCATION_MARKER):
            e = off + len(self.LOCATION_MARKER)
            xy = None
            for k in range(40, 150):
                try:
                    x = d(e + k); y = d(e + k + 8)
                except struct.error:
                    break
                if (x == x and y == y and abs(x) < 0.06 and abs(y) < 0.06
                        and (abs(x) + abs(y)) > 1e-5):
                    xy = (x * 1000.0, y * 1000.0)
                    break
            if xy is None:
                continue
            owner = self._sample_for(off)
            loc.append((off, owner, xy[0], xy[1]))
            rep.setdefault(owner, xy)      # first block per sample wins
        self._locations = loc
        self._sample_pos = rep
        for r in self.regions:
            if r.sample in rep:
                r.pos_x, r.pos_y = rep[r.sample]


    def _parse_images(self):
        imgs = []
        for off in self._find_all(self.IMAGE_MARKER):
            blob = self.raw[off:]
            intact = (b"\xff\xd8" in blob) and not self.corruption["corrupted"]
            note = "" if intact else ("Camera image present but not recoverable "
                                      "from this file (JPEG markers destroyed).")
            imgs.append(ImageBlob("Holder snapshot", off, blob, intact, note))
        self.images = imgs


    def date_for_region(self, r):
        return self._date_for(r.offset)
