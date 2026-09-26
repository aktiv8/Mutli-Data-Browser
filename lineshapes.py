"""Line shapes and backgrounds for reconstructing CasaXPS fits.

All curves are computed on an **ascending kinetic-energy grid** (the frame in
which CasaXPS stores positions) and scaled to the stored *area* (intensity
integrated over energy).

* ``GL(m)``  product Gaussian/Lorentzian, ``m`` = % Lorentzian
* ``SGL(m)`` sum Gaussian/Lorentzian
* ``LA(a,b,m)`` (also ``LA(m)``) asymmetric Lorentzian, Gaussian-broadened
* ``LF(a,b,w,m)`` as LA with a finite tail of width ``w``

GL and SGL are exact. **LA and LF are reconstructions**: CasaXPS does not
publish their kernels, so they use the standard asymmetric-Lorentzian forms
(Major et al., *Surf. Interface Anal.* 53 (2021) 689, Eq. 6; the LA line
shape's own write-up by Major, Shah, Fernandez, Fairley (Casa Software Ltd.)
and Linford, *Vacuum Technology & Coating*, March 2020, Eq. 3 -- both give
``LA(a,b) = L(x)**a`` on the low-KE side and ``L(x)**b`` on the high-KE side
of one shared Lorentzian, matching this module's formula exactly), with a
Gaussian broadening whose scale was calibrated on real CasaXPS fits
(``tests/`` and the validation notes in the README give the residuals). The
stored areas, positions and widths are CasaXPS's own numbers.

**The shared Lorentzian width.** Raising a Lorentzian to a power ``p != 1``
shrinks its own half-max distance by ``sqrt(2**(1/p) - 1)`` relative to
``p = 1``, so using the file's ``fwhm`` unscaled as each side's own width (as
this module did before) makes a strongly asymmetric component (e.g.
``LA(1.2,5,8)``, CasaXPS's sharp metallic-tail cutoff) reconstruct far too
tall for its stored area -- confirmed on two independent real files
(titanium and vanadium metallic-tail examples in ``tests/``), the
reconstructed peak standing up to ~10-18 % of the peak height above the raw
data at the component's own maximum, hidden by ``residual_rms`` because that
metric averages over the whole curve. The fix (from KherveFitting's own
``LA``/``LAxG`` implementation, ``libraries/Peak_Functions.py``,
github.com/KherveFitting/KherveFitting, retrieved 2026-09-25) is **one
Lorentzian width shared by both sides**, chosen so the two sides' own
half-max distances add up to the stored ``fwhm`` (not each side independently
reproducing it, which was tried first and made CasaXPS's own worked LA
examples with mild asymmetry measurably worse while helping the severe
cases): ``F = 2*fwhm / (sqrt(2**(1/a)-1) + sqrt(2**(1/b)-1))``, which is
exactly ``fwhm`` for an unmodified Lorentzian (``a == b == 1``) -- the GL/SGL
shapes and the 2-argument ``LA(m)``/``LF(...)`` shorthand (which default
``a`` and ``b`` to 1) are unaffected; a symmetric but non-unity pair (e.g.
``LA(2,2,m)``) is rescaled too, since raising *either* side to a power other
than 1 narrows it the same way.
Checked against every real ``LA``/``LF``-fitted file available (titanium,
copper, both vanadium exports, MXene): titanium's worst-case overshoot fell
from 18.3 % to 8.7 %, this file's vanadium example from 9.85 % to 4.70 %, and
6 of MXene's 8 affected regions improved too (the other 2 regressed by under
one percentage point). ``TestLAAsymmetryAccuracy`` in ``tests/test_casafit.py``
is a canary against this getting worse.

A related lead was investigated and **not** adopted: two independent sources
(the papers above, and Fairley et al.'s supplementary information for
"Practical guide to understanding goodness-of-fit metrics ... using nylon as
an example," *J. Vac. Sci. Technol. A* 41(1) 2023) show CasaXPS's Gaussian-
character parameter (the ``m`` here) runs the *opposite* direction to
``GAUSS_K``'s formula below (larger ``m`` should mean *more* Gaussian
broadening, not less) -- but no exact conversion to an eV width is published,
and a corrected-direction model calibrated against the same real-file corpus
never beat the width fix above: it either left the worst cases unchanged
(negligible broadening at the small raw ``m`` values titanium/vanadium use)
or, pushed further, quadrupled the average residual across the corpus while
still not matching the width fix's improvement. Do not retune ``GAUSS_K``
without new evidence beyond what produced this conclusion.

**``GAUSS_K["LA"]`` cannot round out a symmetric ``LA(m)`` component's own
apex, at any value.** A real file (PET's ``D:\Temp\for claude files\PET\Fitted
PET Beamson and Briggs.vms``, every C 1s/O 1s component but one is the
symmetric ``LA(50)`` shorthand, i.e. ``a = b = 1``) looks visibly more
Lorentzian near its own peak than a real CasaXPS screenshot of the same fit
suggests it should. Sweeping ``GAUSS_K["LA"]`` from today's 0.20 up to 4.0
(20x) on an isolated ``LA(50)`` component changes its own apex shape by only
about one part in a hundred (``width at 90% of peak / width at 50%``: 0.333 at
``K = 0.20``, saturating at 0.337 by ``K = 1.0`` and no further at ``K = 4.0``
-- for comparison, ``GL(30)``'s own ratio is 0.370, ``GL(0)``'s [pure
Gaussian] is 0.389, and a pure Lorentzian is exactly 0.333). Convolving a
power-law Lorentzian with a Gaussian tightens its very top only slightly no
matter how wide the Gaussian is made, because the Lorentzian's own curvature
at ``t = 0`` already dominates -- this is a property of the Voigt-style
convolution this module uses, not a mistuned constant, so no value of
``GAUSS_K`` will make a symmetric ``LA(m)`` component look meaningfully less
Lorentzian near its apex. Reproducing a rounder apex (if CasaXPS's own kernel
really is rounder there) would need a structurally different mixing formula --
closer to ``GL``'s ``lor**mix * gau**(1-mix)`` product than a convolution --
which is a bigger, unvalidated change with no published reference for the
``LA`` family's true kernel; left for a future session with new real-file
evidence, not attempted here.

**A finite tail cutoff (generalising ``LF``'s ``w`` to plain ``LA``) does not
help either, and makes most real files worse.** The obvious-looking fix for a
tall, narrow component's tail visibly outrunning the real data (also seen on
the PET file: ``C 1s (Ring)``, ``LA(0.8,1.5,243)``, contributes 51.7 counts
~2.8 eV past its own peak where the real background-subtracted signal is only
~17) is to taper the raw shape to zero at some multiple of its width. Tried
and rejected: ``component_curve`` always rescales a component so its
*analytic* integral equals CasaXPS's stored area (this is what
``test_a_narrow_window_does_not_inflate_the_peak`` protects), so cutting the
tail removes area that the rescaling then has to put back into the peak,
making the peak itself taller. Swept against every real ``LA``/``LF`` file
this codebase has (titanium, vanadium, copper, HOPG, ``DS Variations``, PET --
18 fitted regions): every taper width tried (from 15 down to 3 times the
component's own FWHM) made more real regions' overshoot worse than it made
PET's better -- e.g. at a 3-FWHM cutoff, PET's own C 1s overshoot went from
7.6% to 26% (the inflated Ring peak now overshoots its neighbours instead).
The tail's visible extent is fixed in ``plots.draw_fit`` instead (a display
choice, not a change to the shape or its stored area -- see
``_COMPONENT_VISIBLE_FLOOR`` there).

**Tail suffix.** CasaXPS also lets a ``GL``/``SGL`` shape string carry a
trailing ``T(k)`` tail modifier (``GL(30)T(1.5)``), used for asymmetric
metallic peaks. ``parse_shape`` recognises and strips this suffix so the base
shape's own parameters parse correctly, but the tail itself is not
reconstructed: no real CasaXPS-fitted file using this syntax has been
available to validate a curve against, unlike LA/LF above. A tailed
component is therefore drawn as its plain ``GL``/``SGL`` base shape and
flagged ``approximate`` by ``is_exact`` (same signal as LA/LF and an
unreproduced background) rather than silently misread.

**Unrecognised shape names.** A shape name CasaXPS writes that this module
does not implement (``QF``, or CasaXPS's own undocumented ``H``/``F``
families -- seen, unreconstructed, on a real file with three refits of one
C 1s region: ``H(0.09,250)SGL(90)`` and ``F(0.09,32,150)SGL(90)`` alongside
the ``DS`` fit below) used to be silently coerced into an exact ``GL(mix)``
using its first numeric token as a 0-100 % mix -- for ``DS(0.09,500)`` (see
below) this drew an almost-pure Gaussian and reported it as *exact*, 12 % of
peak height off and 68 % over the real peak at its own maximum, with no
warning. ``parse_shape`` now keeps the real name (so ``is_exact`` correctly
reports it unreconstructed) and ``_raw_values`` draws it as a plain
unmodified Lorentzian of the component's own ``fwhm`` (the ``a = b = 1``,
``w = 0`` default of the LA/LF branch below, no Gaussian broadening) purely
so something renders -- not a guess at the real shape, just a placeholder
that is honestly flagged. A compound name CasaXPS writes as a base shape
followed by a second one in its own parentheses (``H(0.09,250)SGL(90)``, or
the documented ``DS(a,n)GL(m)``/``DS(a,n)SGL(m)`` blend) parses as the
leading shape with the remainder kept verbatim in ``parse_shape``'s
``suffix`` key rather than failing to parse at all; the blend itself is not
reconstructed (no real file with it has been available), so a ``DS`` with a
suffix draws as plain ``DS``, same precedent as the ``T(k)`` tail.

**DS(a, n): Doniach-Sunjic.** CasaXPS's asymmetric-tail shape for metallic /
graphitic peaks (e.g. HOPG's C 1s). Reconstructed from the published kernel
(Doniach & Sunjic 1970; the form here matches an independent reconstruction
retrieved 2026-09-26 from public papers, itself unvalidated) --
``t = 2(x-pos)/fwhm``, ``DS_raw(t; a) = cos(pi*a/2 + (1-a)*atan(t)) /
(1+4t^2)**((1-a)/2)`` -- convolved with a Gaussian through the same
``gauss_conv`` + area-normalisation pipeline LA/LF already use. This raw
kernel's own asymmetry direction is exact (a fast, power-law-t^-(2-a) decay
on the low-binding-energy side, KE > pos; the well-known long t^-(1-a) tail
on the high-BE side, KE < pos) -- only the Gaussian convolution width is a
calibration.

The convolution width uses the same ``GAUSS_K`` dial as LA/LF but, unlike
them, its own exponent on ``(25/n)`` (``GAUSS_P``, 1 for every other shape):
``gw = fwhm * GAUSS_K["DS"] * (25/n) ** GAUSS_P["DS"]``. First calibrated on
one ``DS(0.09,500)`` component (a plain ``K``, implicit exponent 1) it
overshot the real data specifically on the low-BE side once more real
``(a, n)`` variations of the *same* underlying spectrum became available
(``D:\Temp\for claude files\DS Variations.vms``: 7 CasaXPS refits of one C1s
scan, ``a`` in 0.05-0.10, ``n`` in 200/400/500) -- a symmetric Gaussian
widens a naturally sharp edge (the fast-decaying low-BE side) far more
visibly than it perturbs an already-broad tail, so too large a ``gw`` there
reads exactly as "the low-BE side extends past the data". A per-region
residual-minimising search over ``gw`` on those 7 regions showed the true
optimum scales more weakly with ``n`` than ``25/n`` (exponent 1): fitting
``gw* = fwhm * K' * (25/n)**p`` by ordinary least squares on
``log(gw*/fwhm)`` vs ``log(25/n)`` gives **``GAUSS_K["DS"] = 1.8445``,
``GAUSS_P["DS"] = 0.5737``** (R^2 = 0.886 over the 7 points -- real but
imperfect; ``a`` has a secondary effect on the true optimum, ~5.5 % relative
spread within one ``n`` group, not modelled -- a third parameter is not
worth fitting on 7 points). Against today's numbers (``K=5.6``, implicit
``p=1``) this drops the mean ``residual_rms`` across the 7 regions from
1.49 % to 1.30 % of peak height and the mean low-BE-side overshoot from
5.27 % to 3.83 % (worst case 6.68 % to 6.69 %; one region regresses
~0.03 pp, the rest improve, e.g. ``DS(0.05,200)``'s overshoot 5.68 % to
3.41 %). A ``gw`` with no ``n`` dependence at all was tried and rejected: it
removes the low-BE overshoot almost entirely but then under-broadens the
peak apex at ``n=200``, visibly worsening the whole-curve fit there --
``n`` has to stay in the formula, just with a weaker exponent. **This is
still one calibration spectrum** (now with rich ``(a, n)`` coverage rather
than one point, not an independent second measurement): retune again only
with a ``DS`` fit on genuinely different real data, not on general
principle.

numpy is needed for evaluation; everything else here is plain Python.
"""

from __future__ import annotations

import math
import re

GAUSS_K = {"LF": 0.60, "LA": 0.20, "DS": 1.8445}  # Gaussian FWHM / component FWHM
GAUSS_P = {"DS": 0.5737}  # exponent on (25/m); every other shape is 1 (below)
_LN2_4 = 2.772588722239781               # 4 ln 2


_TAIL_SUFFIX_RE = re.compile(r"^(.*\))\s*T\(\s*[^()]*\s*\)\s*$", re.IGNORECASE)
_SHAPE_RE = re.compile(r"^\s*([A-Za-z]+)\s*\(([^()]*)\)\s*(.*)$")


def parse_shape(text) -> dict:
    """``{"kind", "a", "b", "w", "m", "mix", "tail", "suffix", "params"}``
    from a shape string such as ``GL(30)``, ``LA(1.1,1.9,7)``,
    ``LF(1.1,1.2,75,200)``, ``DS(0.09,500)``, a ``GL``/``SGL`` shape with a
    CasaXPS tail suffix (``GL(30)T(1.5)``, used for asymmetric metallic
    peaks) or a compound shape naming a second one in its own parentheses
    (``H(0.09,250)SGL(90)``, or the documented ``DS(a,n)GL(m)``/
    ``DS(a,n)SGL(m)`` blend). ``tail`` is True when the ``T(k)`` suffix was
    present -- the base shape's own parameters still parse correctly, but
    the tail itself is not reconstructed (see the module docstring).
    ``suffix`` holds a compound name's second shape verbatim, unparsed. A
    name this module does not implement (``QF``, CasaXPS's own ``H``/``F``
    families, ...) keeps its real ``kind`` and stores its raw numeric tokens
    in ``params`` rather than being coerced into a fabricated ``GL(mix)`` --
    see the module docstring. An unreadable string (no ``NAME(...)`` at all)
    is a symmetric Lorentzian-Gaussian mix ("GL(30)")."""
    text = str(text or "")
    tail = False
    tm = _TAIL_SUFFIX_RE.match(text)
    if tm:
        text = tm.group(1)
        tail = True
    m = _SHAPE_RE.match(text)
    if not m:
        return {"kind": "GL", "mix": 30.0, "a": 1.0, "b": 1.0, "w": 0.0,
                "m": 0.0, "tail": tail, "suffix": "", "params": []}
    kind = m.group(1).upper()
    ps = []
    for tok in m.group(2).split(","):
        try:
            ps.append(float(tok))
        except ValueError:
            pass
    suffix = m.group(3).strip()
    out = {"kind": kind, "a": 1.0, "b": 1.0, "w": 0.0, "m": 0.0, "mix": 0.0,
           "tail": tail, "suffix": suffix, "params": ps}
    if kind == "LF":
        out.update(a=ps[0] if ps else 1.0, b=ps[1] if len(ps) > 1 else 1.0,
                   w=ps[2] if len(ps) > 2 else 0.0,
                   m=ps[3] if len(ps) > 3 else 0.0)
    elif kind == "LA":
        if len(ps) >= 3:
            out.update(a=ps[0], b=ps[1], m=ps[2])
        else:
            out.update(m=ps[0] if ps else 0.0)
    elif kind == "DS":
        out.update(a=ps[0] if ps else 0.0, m=ps[1] if len(ps) > 1 else 0.0)
    elif kind in ("GL", "SGL"):
        out["mix"] = ps[0] if ps else 30.0
    return out


def is_exact(shape) -> bool:
    """True for shapes that are exact rather than reconstructed."""
    ps = parse_shape(shape)
    return ps["kind"] in ("GL", "SGL") and not ps["tail"]


def _np():
    import numpy
    return numpy


def gauss_conv(x, y, gfwhm):
    """``y`` convolved with a Gaussian of FWHM ``gfwhm`` (same units as
    ``x``, a uniform grid); edges are extended flat."""
    np = _np()
    if not gfwhm > 0 or len(x) < 3:
        return y
    dx = abs(x[1] - x[0])
    sig = gfwhm / 2.3548200450309493
    n = int(min(200, max(1, round(4 * sig / dx))))
    k = np.exp(-0.5 * (np.arange(-n, n + 1) * dx / sig) ** 2)
    k /= k.sum()
    pad = np.concatenate([np.full(n, y[0]), y, np.full(n, y[-1])])
    return np.convolve(pad, k, mode="valid")


def _half_width_term(p):
    """``sqrt(2**(1/p) - 1)``: how far (in units of the shared Lorentzian
    width ``F``) ``1/(1+4t^2)**p`` must go to reach half its maximum. ``1``
    at ``p = 1``, so a symmetric shape's ``F`` below is exactly ``fwhm``."""
    if p <= 0:
        return 1.0
    return math.sqrt(max(1e-12, 2.0 ** (1.0 / p) - 1.0))


def _shared_width(fwhm, a, b):
    """The one Lorentzian width shared by both sides of an ``LA``/``LF``
    shape, chosen so the two sides' own half-max distances add up to the
    file's stated ``fwhm`` (KherveFitting's ``LA`` formula; see the module
    docstring). Reduces to ``fwhm`` only for an unmodified Lorentzian
    (``a == b == 1``); a symmetric but non-unity pair is rescaled too."""
    denom = _half_width_term(a) + _half_width_term(b)
    return 2.0 * fwhm / denom if denom > 0 else fwhm


def _raw_values(x, sp, pos, fwhm):
    """The lineshape before any LA/LF Gaussian broadening (GL/SGL have none):
    the GL product, the SGL sum, or the raw asymmetric Lorentzian (with its
    LF finite-tail taper) on grid ``x``. Used both for the values a caller
    asked for and, on a separate wide grid, for area normalisation."""
    np = _np()
    if sp["kind"] in ("GL", "SGL"):
        t = (x - pos) / fwhm
        lor = 1.0 / (1.0 + 4.0 * t * t)
        mix = min(max(sp["mix"], 0.0), 100.0) / 100.0
        gau = np.exp(-_LN2_4 * t * t)
        if sp["kind"] == "GL":
            return (lor ** mix) * (gau ** (1.0 - mix))
        return mix * lor + (1.0 - mix) * gau
    if sp["kind"] == "DS":
        t = 2.0 * (x - pos) / fwhm
        a = sp["a"]
        return np.cos(np.pi * a / 2.0 + (1.0 - a) * np.arctan(t)) \
            / (1.0 + 4.0 * t * t) ** ((1.0 - a) / 2.0)
    F = _shared_width(fwhm, sp["a"], sp["b"])
    t = (x - pos) / F
    lor = 1.0 / (1.0 + 4.0 * t * t)
    v = np.where(t < 0, lor ** sp["a"], lor ** sp["b"])
    if sp["w"] > 0:                              # finite tail (LF): the
        r = np.abs((x - pos) / fwhm) / sp["w"]    # taper stays on the
        v = np.where(r < 1, v * (1 - r * r) ** 2, 0.0)  # nominal fwhm
    return v


# How far a component's own area is measured, in FWHM either side of its
# position: independent of the (possibly narrower) CasaXPS fit-region window
# it is drawn on, so a tail cut off by a tight region box is not mistaken for
# missing area and used to inflate the visible peak.
_NORM_HALF_WIDTH = 100.0
_NORM_POINTS = 4001


def component_curve(ke, shape, pos, fwhm, area):
    """The component on the ascending KE grid ``ke`` (numpy array), scaled so
    that its integral over its own full extent — not just over ``ke``, which
    may be a CasaXPS region window narrower than the shape's tail — is
    ``area``. A component whose tail runs past the displayed window is
    therefore not inflated to make up area that simply isn't in the window."""
    np = _np()
    ke = np.asarray(ke, dtype=float)
    sp = parse_shape(shape)
    fwhm = fwhm if fwhm and fwhm > 0 else 1.0
    v = _raw_values(ke, sp, pos, fwhm)
    if sp["kind"] in ("GL", "SGL"):
        conv = v
    else:
        gw = fwhm * GAUSS_K.get(sp["kind"], 0.0) * (
            (25.0 / sp["m"]) ** GAUSS_P.get(sp["kind"], 1.0)
            if sp["m"] else 0.0)
        conv = gauss_conv(ke, v, gw)
    span = _NORM_HALF_WIDTH * fwhm
    wide = np.linspace(pos - span, pos + span, _NORM_POINTS)
    wstep = wide[1] - wide[0]
    s = float(_raw_values(wide, sp, pos, fwhm).sum()) * wstep
    return conv * (area / s if s > 0 else 0.0)


def shirley(y, avg=1, iters=100):
    """Iterative Shirley background of ``y`` on an ascending-KE slice (the
    low-KE end is the high-binding-energy side, which sits higher). ``avg``
    points are averaged at each end for the end levels."""
    np = _np()
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 3:
        return y.copy()
    k = max(1, min(int(avg), n // 2 or 1))
    lo, hi = float(y[:k].mean()), float(y[-k:].mean())
    b = np.full(n, lo)
    for _ in range(iters):
        cum = np.cumsum(np.maximum(y - b, 0.0))
        tot = cum[-1] if cum[-1] > 0 else 1.0
        nb = lo + (hi - lo) * cum / tot
        done = float(np.abs(nb - b).max()) < 1e-9 * max(1.0, abs(hi - lo))
        b = nb
        if done:
            break
    return b


def linear_bg(y, avg=1):
    np = _np()
    y = np.asarray(y, dtype=float)
    n = len(y)
    k = max(1, min(int(avg), n // 2 or 1))
    return float(y[:k].mean()) + (float(y[-k:].mean()) - float(y[:k].mean())) \
        * np.linspace(0.0, 1.0, n)


def tougaard_u2(x, y, b, c, avg=1):
    """The two-parameter universal Tougaard background of ``y`` on the
    ascending-KE grid ``x``: the level at the high-KE end (mean of ``avg``
    points) plus the inelastic tail of everything above each point,
    ``sum K(T) (y - end) dE`` over ``T = x' - x``, with the cross-section
    ``K(T) = B T / (C + T^2)^2``. CasaXPS stores C with a minus sign (its
    general form is ``B T / ((C - T^2)^2 + D T^2)`` and the two-parameter
    version has D = 0). ``b`` is B (eV^2), ``c`` the positive C (eV^2).
    Checked on real CasaXPS fits (see ``tests/test_casafit.py``)."""
    np = _np()
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 3:
        return y.copy()
    k = max(1, min(int(avg), n // 2 or 1))
    base = float(y[-k:].mean())
    dx = float(np.abs(np.diff(x)).mean())
    yb = y - base
    bg = np.empty(n)
    for i in range(n):
        t = x[i + 1:] - x[i]
        bg[i] = float(np.sum(b * t / ((c + t * t) ** 2) * yb[i + 1:]))
    return base + bg * dx


def tougaard_3param(x, y, b, c, d, avg=1):
    """The three-parameter universal Tougaard background of ``y`` on the
    ascending-KE grid ``x``: same construction as :func:`tougaard_u2` (the
    level at the high-KE end plus the inelastic tail of everything above each
    point) but with the three-parameter cross section
    ``K(T) = B T / ((C - T^2)^2 + D T^2)`` (Tougaard, *Surf. Interface Anal.*
    25, 137 (1997); CasaXPS's own "Peak Fitting in XPS" names this the
    ``U 4 Tougaard`` cross section, with ``U Poly``/``U Si``/``U SiO2``/
    ``U Ge``/``U Al`` as its built-in material presets). Unlike
    :func:`tougaard_u2`, CasaXPS stores ``B``, ``C`` and ``D`` here with their
    natural sign (no minus on ``C``). Checked against a real CasaXPS
    ``U Poly Tougaard`` fit (``D:\\Temp\\for claude files\\PET``): the file's
    own ``params[2:5]`` for both its C 1s and O 1s regions are ``396, 551,
    436`` -- an exact match to Tougaard's published Polymers row -- and
    reconstructing background + the file's own components against its own raw
    data with these values gives residuals in the same few-percent range as
    this module's pre-existing ``LA``-shape reconstruction noise, not a
    background-shape mismatch. CasaXPS's region line for this cross-section
    family carries two further numbers ahead of ``B`` (``params[0]``,
    ``params[1]``) that are **not reconstructed here**: CasaXPS's docs
    describe both a per-cross-section T0 energy-loss cutoff and, separately,
    generic per-region St/End Offset percentages, either of which could
    explain them, and treating ``params[1]`` as a literal T0 cutoff on the
    real file above collapses the entire C 1s background to flat (19.6 eV
    exceeds the whole 15 eV fit window) -- evidence against that reading
    without enough real files to confirm the right one, so, as with
    :func:`tougaard_u2`'s own unused slots, they are left alone rather than
    guessed."""
    np = _np()
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 3:
        return y.copy()
    k = max(1, min(int(avg), n // 2 or 1))
    base = float(y[-k:].mean())
    dx = float(np.abs(np.diff(x)).mean())
    yb = y - base
    bg = np.empty(n)
    for i in range(n):
        t = x[i + 1:] - x[i]
        bg[i] = float(np.sum(b * t / ((c - t * t) ** 2 + d * t * t) * yb[i + 1:]))
    return base + bg * dx


_TOUGAARD_U2 = re.compile(r"^u\s*2\s*tougaard")
_TOUGAARD_3P = re.compile(r"^u\s*(poly|sio2|si|ge|al|4)\s*tougaard\b")


def background(kind, y, avg=1, x=None, params=()):
    """Background under ``y`` for a CasaXPS type name ('Shirley', 'Linear',
    'None', 'U 2 Tougaard', 'U Poly Tougaard', 'U Si Tougaard', 'U SiO2
    Tougaard', 'U Ge Tougaard', 'U Al Tougaard', 'U 4 Tougaard' ...); None for
    a type this module cannot reproduce (e.g. plain 'Tougaard', 'W Tougaard',
    'E Tougaard', a Spline background). ``x`` (ascending KE) and ``params``
    (the region line's six numbers after the averaging width) are needed for
    every Tougaard variant."""
    t = str(kind or "").strip().lower()
    if t.startswith("shirley"):
        return shirley(y, avg)
    if _TOUGAARD_U2.match(t):
        if x is None or len(params) < 4 or not params[2]:
            return None
        return tougaard_u2(x, y, params[2], abs(params[3]) or 1643.0, avg)
    if _TOUGAARD_3P.match(t):
        if x is None or len(params) < 5 or not params[2] or not params[3]:
            return None
        return tougaard_3param(x, y, params[2], params[3], params[4], avg)
    if t.startswith("linear"):
        return linear_bg(y, avg)
    if t in ("none", "", "offset"):
        np = _np()
        return np.zeros(len(y))
    return None
