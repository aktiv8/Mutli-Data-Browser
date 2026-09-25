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

**Tail suffix.** CasaXPS also lets a ``GL``/``SGL`` shape string carry a
trailing ``T(k)`` tail modifier (``GL(30)T(1.5)``), used for asymmetric
metallic peaks. ``parse_shape`` recognises and strips this suffix so the base
shape's own parameters parse correctly, but the tail itself is not
reconstructed: no real CasaXPS-fitted file using this syntax has been
available to validate a curve against, unlike LA/LF above. A tailed
component is therefore drawn as its plain ``GL``/``SGL`` base shape and
flagged ``approximate`` by ``is_exact`` (same signal as LA/LF and an
unreproduced background) rather than silently misread.

numpy is needed for evaluation; everything else here is plain Python.
"""

from __future__ import annotations

import math
import re

GAUSS_K = {"LF": 0.60, "LA": 0.20}       # Gaussian FWHM / component FWHM
_LN2_4 = 2.772588722239781               # 4 ln 2


_TAIL_SUFFIX_RE = re.compile(r"^(.*\))\s*T\(\s*[^()]*\s*\)\s*$", re.IGNORECASE)
_SHAPE_RE = re.compile(r"^\s*([A-Za-z]+)\s*\(([^()]*)\)\s*$")


def parse_shape(text) -> dict:
    """``{"kind", "a", "b", "w", "m", "mix", "tail"}`` from a shape string
    such as ``GL(30)``, ``LA(1.1,1.9,7)``, ``LF(1.1,1.2,75,200)`` or a
    ``GL``/``SGL`` shape with a CasaXPS tail suffix (``GL(30)T(1.5)``, used
    for asymmetric metallic peaks). ``tail`` is True when that suffix was
    present -- the base shape's own parameters still parse correctly, but
    the tail itself is not reconstructed (see the module docstring). An
    unreadable string is a symmetric Lorentzian-Gaussian mix ("GL(30)")."""
    text = str(text or "")
    tail = False
    tm = _TAIL_SUFFIX_RE.match(text)
    if tm:
        text = tm.group(1)
        tail = True
    m = _SHAPE_RE.match(text)
    if not m:
        return {"kind": "GL", "mix": 30.0, "a": 1.0, "b": 1.0, "w": 0.0,
                "m": 0.0, "tail": tail}
    kind = m.group(1).upper()
    ps = []
    for tok in m.group(2).split(","):
        try:
            ps.append(float(tok))
        except ValueError:
            pass
    out = {"kind": kind, "a": 1.0, "b": 1.0, "w": 0.0, "m": 0.0, "mix": 0.0,
           "tail": tail}
    if kind == "LF":
        out.update(a=ps[0] if ps else 1.0, b=ps[1] if len(ps) > 1 else 1.0,
                   w=ps[2] if len(ps) > 2 else 0.0,
                   m=ps[3] if len(ps) > 3 else 0.0)
    elif kind == "LA":
        if len(ps) >= 3:
            out.update(a=ps[0], b=ps[1], m=ps[2])
        else:
            out.update(m=ps[0] if ps else 0.0)
    else:
        out["kind"] = kind if kind in ("GL", "SGL") else "GL"
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
            25.0 / sp["m"] if sp["m"] else 0.0)
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


_TOUGAARD_U2 = re.compile(r"^u\s*2\s*tougaard")


def background(kind, y, avg=1, x=None, params=()):
    """Background under ``y`` for a CasaXPS type name ('Shirley', 'Linear',
    'None', 'U 2 Tougaard' ...); None for a type this module cannot
    reproduce. ``x`` (ascending KE) and ``params`` (the region line's six
    numbers after the averaging width) are needed for Tougaard."""
    t = str(kind or "").strip().lower()
    if t.startswith("shirley"):
        return shirley(y, avg)
    if _TOUGAARD_U2.match(t):
        if x is None or len(params) < 4 or not params[2]:
            return None
        return tougaard_u2(x, y, params[2], abs(params[3]) or 1643.0, avg)
    if t.startswith("linear"):
        return linear_bg(y, avg)
    if t in ("none", "", "offset"):
        np = _np()
        return np.zeros(len(y))
    return None
