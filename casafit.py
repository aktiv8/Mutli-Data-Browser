r"""CasaXPS fits carried in VAMAS block comments: reading them, reconstructing
the curves and writing them back.

CasaXPS stores a fit in the block comment as lines like::

    Calib M = 455.59 A = 458.6 BE ADD
    CASA region (*Ti 2p*) (*Shirley*) 1019.03 1034.88 2.001 1 ... (*Ti 2p*) 47.88
    8
    CASA comp (*Ti 2p3/2 Ti(IV)*) (*GL(30)*) Area 3394.1 0.001 1e7 -1 1 MFWHM 1.27 ...
        Position 1028.11 1014.59 1034.69 -1 1 RSF 2.001 MASS 47.88 INDEX -1 (*Ti 2p*)

Region limits and component positions are **kinetic energies**. Which frame
they are in depends on the ``Calib`` line that shifted the spectrum: the
spectrum's own abscissa is never shifted, the ``Calib`` lines (assigned -
measured, summed) give the offset. Without the ``Regions`` / ``Comps`` flags
the limits / positions are in the *calibrated* frame, so a component sits at
raw KE ``position + shift`` and at binding energy ``hv - position - shift``.
With ``Calib M = 281.88 A = 284.8 Regions Comps BE ADD`` CasaXPS moved the
regions and components together with the spectrum, so they are already raw
KE. Intensities are counts per second: the file's counts divided by
dwell x scans. (All checked against real CasaXPS files: see
``tests/test_casafit.py``.)

Because the positions are anchored in KE, moving a spectrum's binding-energy
axis (the app's calibration, which moves the photon energy with it) moves the
fit with it and needs no adjustment.

The dataclasses hold the parsed numbers and the original ``lines``, which are
what is written back to VAMAS (unchanged, so CasaXPS reopens its own fit).
numpy is needed for ``curves``; parsing is plain Python.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import lineshapes

_TAG = re.compile(r"\(\*(.*?)\*\)")
_NUM = re.compile(r"^-?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?$")
_CALIB = re.compile(
    r"^Calib\s+M\s*=\s*([-\d.eE+]+)\s+A\s*=\s*([-\d.eE+]+)(.*)$")


@dataclass
class FitRegion:
    name: str
    background: str = "Shirley"
    start_ke: float = 0.0            # KE as stored (see Fit.shift_of_regions)
    end_ke: float = 0.0
    rsf: float = 1.0
    avg: int = 1                     # end-point averaging width (points)
    mass: float = 0.0
    params: tuple = ()               # the six numbers after the averaging
                                     # width (background parameters)
    line: str = ""


@dataclass
class FitComponent:
    name: str
    shape: str = "GL(30)"
    area: float = 0.0                # counts/s x eV
    fwhm: float = 1.0                # eV
    pos_ke: float = 0.0              # KE as stored (see Fit.shift_of_comps)
    rsf: float = 1.0
    mass: float = 0.0
    index: int = -1                  # INDEX: chemical-state group (>= 0)
    group: str = ""                  # the group's tag, e.g. "Metal"
    region: str = ""                 # name of the region it belongs to
    line: str = ""


@dataclass
class Fit:
    regions: list = field(default_factory=list)
    components: list = field(default_factory=list)
    calib_shift: float = 0.0         # eV added to BE by the Calib lines
    region_shift: float | None = None   # part of it the region limits are
    comp_shift: float | None = None     # / component positions do NOT include
                                        # (None: all of calib_shift)
    lines: list = field(default_factory=list)   # the CASA/Calib lines, as read
    block: list = field(default_factory=list)   # the whole CasaXPS section of
                                                # the comment, verbatim

    def is_empty(self) -> bool:
        return not (self.regions or self.components)

    def shift_of_regions(self) -> float:
        """eV to add to a stored region limit to get the raw kinetic energy."""
        if self.region_shift is None:
            return self.calib_shift
        return self.region_shift

    def shift_of_comps(self) -> float:
        """eV to add to a stored component position to get the raw KE."""
        if self.comp_shift is None:
            return self.calib_shift
        return self.comp_shift

    def region_components(self, region):
        """Components of a region (all of them when the file has just one
        region or the comp lines name none)."""
        mine = [c for c in self.components if c.region == region.name]
        if mine or len(self.regions) != 1:
            return mine
        return list(self.components)

    def group_of(self, comp):
        """Colour/legend group key: components sharing an INDEX >= 0 are one
        chemical state; others stand alone."""
        return f"i{comp.index}" if comp.index >= 0 else f"c{id(comp)}"


def _floats(text):
    return [float(t) for t in text.split() if _NUM.match(t)]


def _region(line):
    m = re.match(r"^CASA region \(\*(.*?)\*\) \(\*(.*?)\*\)\s*(.*)$", line)
    if not m:
        return None
    body = m.group(3)
    nums = _floats(_TAG.sub(" ", body))
    if len(nums) < 2:
        return None
    tail = _floats(body.rsplit("*)", 1)[-1])        # after the last tag: mass
    return FitRegion(
        name=m.group(1), background=m.group(2),
        start_ke=min(nums[0], nums[1]), end_ke=max(nums[0], nums[1]),
        rsf=nums[2] if len(nums) > 2 else 1.0,
        avg=int(nums[3]) if len(nums) > 3 and 0 < nums[3] < 50 else 1,
        mass=tail[0] if tail else 0.0, params=tuple(nums[4:10]), line=line)


def _comp(line, region_name):
    m = re.match(r"^CASA comp \(\*(.*?)\*\) \(\*(.*?)\*\)\s*(.*)$", line)
    if not m:
        return None
    rest = m.group(3)

    def num(key, default=None):
        r = re.search(r"\b" + key + r"\s+(-?[\d.]+(?:[eE][-+]?\d+)?)", rest)
        return float(r.group(1)) if r else default
    area, fwhm, pos = num("Area"), num("MFWHM"), num("Position")
    if area is None or pos is None:
        return None
    idx = re.search(r"\bINDEX\s+(-?\d+)\s*(?:\(\*(.*?)\*\))?", rest)
    return FitComponent(
        name=m.group(1), shape=m.group(2), area=area,
        fwhm=fwhm if fwhm else 1.0, pos_ke=pos, rsf=num("RSF", 1.0),
        mass=num("MASS", 0.0), index=int(idx.group(1)) if idx else -1,
        group=(idx.group(2) or "") if idx else "", region=region_name,
        line=line)


@dataclass
class Calib:
    """The charge correction CasaXPS recorded in a block comment.

    ``shift`` (eV) is added to the binding energies (assigned - measured,
    summed over the block's ``Calib`` lines). A line that carries the
    ``Regions`` / ``Comps`` flags moved the fit regions / components together
    with the spectrum, so those are stored in the raw frame and that line
    does not count towards ``region_shift`` / ``comp_shift``."""
    measured: float
    assigned: float
    shift: float
    region_shift: float
    comp_shift: float
    lines: list = field(default_factory=list)


def calibration(comment_lines):
    """The :class:`Calib` in a block comment (fit or no fit), or None. Lines
    look like ``Calib M = 281.7289 A = 282 BE ADD`` (some files end in just
    ``BE`` or ``ADD``)."""
    first = None
    lines, total, reg, comp = [], 0.0, 0.0, 0.0
    for raw in comment_lines or ():
        line = str(raw).strip()
        cm = _CALIB.match(line)
        if not cm:
            continue
        m, a = float(cm.group(1)), float(cm.group(2))
        flags = {w.upper() for w in cm.group(3).split()}
        d = a - m
        total += d
        reg += 0.0 if "REGIONS" in flags else d
        comp += 0.0 if "COMPS" in flags else d
        first = m if first is None else first
        lines.append(line)
    if not lines:
        return None
    return Calib(measured=first, assigned=first + total, shift=total,
                 region_shift=reg, comp_shift=comp, lines=lines)


def calib_line(measured, assigned) -> str:
    """A ``Calib`` line for a shift the file did not carry itself; the
    ``Regions Comps`` flags say any fit in the block is already in the raw
    frame."""
    return (f"Calib M = {float(measured):.10g} A = {float(assigned):.10g} "
            "Regions Comps BE ADD")


def parse(comment_lines):
    """The fit held in a block comment, or None when it has none."""
    fit = Fit()
    cal = calibration(comment_lines)
    if cal is not None:
        fit.calib_shift = cal.shift
        fit.region_shift, fit.comp_shift = cal.region_shift, cal.comp_shift
    current = ""
    for raw in comment_lines or ():
        line = raw.strip()
        if _CALIB.match(line):
            fit.lines.append(line)
            continue
        if line.startswith("CASA region"):
            reg = _region(line)
            if reg:
                fit.regions.append(reg)
                fit.lines.append(line)
                current = reg.name
            continue
        if line.startswith("CASA comp"):
            comp = _comp(line, current)
            if comp:
                fit.components.append(comp)
                fit.lines.append(line)
            continue
        if fit.lines and fit.lines[-1].startswith("CASA region") \
                and re.fullmatch(r"\d+", line):
            fit.lines.append(line)                  # the comp count line
    if fit.is_empty():
        return None
    fit.block = _casa_block(comment_lines, fit.lines)
    return fit


def _casa_block(comment_lines, casa_lines):
    """The stretch of the comment from CasaXPS's "Casa Info Follows" header
    (or, without it, the first Calib/CASA line) to its last CASA line, exactly
    as read: CasaXPS's own count lines sit in it, and writing it back
    unchanged is what lets CasaXPS reopen its own fit."""
    lines = [str(l).rstrip("\r\n") for l in comment_lines]
    stripped = [l.strip() for l in lines]
    first_casa = next((i for i, l in enumerate(stripped)
                       if l in casa_lines), None)
    last_casa = max((i for i, l in enumerate(stripped) if l in casa_lines),
                    default=None)
    if first_casa is None:
        return list(casa_lines)
    start = first_casa
    for i in range(first_casa, -1, -1):
        if stripped[i].lower().startswith("casa info follows"):
            start = i
            break
    return lines[start:last_casa + 1]


def to_lines(fit) -> list:
    """The comment lines that carry ``fit`` (as read, ready to be written)."""
    if not fit:
        return []
    return list(fit.block or fit.lines)


# -- reconstruction ----------------------------------------------------------------
@dataclass
class Curves:
    """A region's reconstructed fit on the spectrum's own points (same order
    as the region's energies; NaN outside the fit region), in the units of
    the spectrum's counts."""
    region: str
    background_type: str
    background: list | None
    components: list                # [(FitComponent, values)]
    envelope: list | None           # None when the background is not known
    approximate: bool               # LA / LF shapes are reconstructions
    scale_known: bool               # False: dwell / scans unknown (CPS shown)
    residual_rms: float | None = None   # rms(data - envelope) / data range
    background_known: bool = True   # False: this background type is not
                                    # reproduced (components only)


def distinct_regions(regions):
    """The regions to draw: of several overlapping regions that share a name
    (CasaXPS keeps the earlier ones when a wider one is added, and the
    components name only the region's label) only the widest is kept."""
    keep = []
    for reg in sorted(regions, key=lambda g: g.start_ke - g.end_ke):
        if any(k.name == reg.name and reg.start_ke < k.end_ke
               and k.start_ke < reg.end_ke for k in keep):
            continue
        keep.append(reg)
    return [g for g in regions if any(g is k for k in keep)]


def curves(fit, energies, counts, hv, dwell=None, scans=1):
    """``[Curves]`` for every region of ``fit`` on a spectrum given by
    binding ``energies`` (native order), ``counts``, photon energy ``hv``,
    dwell and number of scans. [] when nothing can be reconstructed.

    Everything is worked out in the spectrum's raw kinetic-energy frame: the
    stored region limits and component positions are moved into it with the
    shifts the ``Calib`` line implies (see the module notes)."""
    if fit is None or not hv or not energies or not counts:
        return []
    import numpy as np
    be = np.asarray(energies, dtype=float)
    ke = hv - be                                        # raw kinetic energy
    scale = (dwell * (scans or 1)) if dwell else None
    cps = np.asarray(counts, dtype=float) / (scale or 1.0)
    order = np.argsort(ke)                              # ascending KE
    if fit.regions:
        regions = [(g, g.start_ke + fit.shift_of_regions(),
                    g.end_ke + fit.shift_of_regions())
                   for g in distinct_regions(fit.regions)]
    else:
        regions = [(FitRegion(name="", background="none"),
                    float(ke.min()), float(ke.max()))]
    cshift = fit.shift_of_comps()
    out = []
    for reg, lo, hi in regions:
        sel = order[(ke[order] >= lo) & (ke[order] <= hi)]
        if len(sel) < 3:
            continue
        kx, y = ke[sel], cps[sel]
        bg = lineshapes.background(reg.background, y, reg.avg, x=kx,
                                   params=reg.params)
        comps, total = [], (np.zeros(len(sel)) if bg is None else bg.copy())
        approx = False
        for c in fit.region_components(reg):
            v = lineshapes.component_curve(kx, c.shape, c.pos_ke + cshift,
                                           c.fwhm, c.area)
            comps.append((c, v))
            total = total + v
            approx = approx or not lineshapes.is_exact(c.shape)
        k = scale or 1.0

        def full(vals):
            arr = np.full(len(be), np.nan)
            arr[sel] = vals * k
            return arr.tolist()
        rms = None
        if comps and bg is not None and float(y.max() - y.min()) > 0:
            rms = float(np.sqrt(np.mean((y - total) ** 2))
                        / (y.max() - y.min()))
        out.append(Curves(
            region=reg.name, background_type=reg.background,
            background=None if bg is None else full(bg),
            components=[(c, full(v)) for c, v in comps],
            envelope=full(total) if comps and bg is not None else None,
            approximate=approx, scale_known=scale is not None,
            residual_rms=rms, background_known=bg is not None))
    return out


def component_be(comp, hv, fit=None):
    """Binding energy of a component in the calibrated frame: what CasaXPS
    shows (the spectrum's own axis lies ``fit.calib_shift`` below it)."""
    if fit is None:
        return hv - comp.pos_ke
    return hv - comp.pos_ke - fit.shift_of_comps() + fit.calib_shift
