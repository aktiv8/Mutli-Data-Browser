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
with a Gaussian broadening whose scale was calibrated on real CasaXPS fits
(``tests/`` and the validation notes in the README give the residuals). The
stored areas, positions and widths are CasaXPS's own numbers.

numpy is needed for evaluation; everything else here is plain Python.
"""

from __future__ import annotations

import re

GAUSS_K = {"LF": 0.60, "LA": 0.20}       # Gaussian FWHM / component FWHM
_LN2_4 = 2.772588722239781               # 4 ln 2


def parse_shape(text) -> dict:
    """``{"kind", "a", "b", "w", "m", "mix"}`` from a shape string such as
    ``GL(30)``, ``LA(1.1,1.9,7)`` or ``LF(1.1,1.2,75,200)``. An unreadable
    string is a symmetric Lorentzian-Gaussian mix ("GL(30)")."""
    m = re.match(r"^\s*([A-Za-z]+)\s*\((.*)\)\s*$", str(text or ""))
    if not m:
        return {"kind": "GL", "mix": 30.0, "a": 1.0, "b": 1.0, "w": 0.0,
                "m": 0.0}
    kind = m.group(1).upper()
    ps = []
    for tok in m.group(2).split(","):
        try:
            ps.append(float(tok))
        except ValueError:
            pass
    out = {"kind": kind, "a": 1.0, "b": 1.0, "w": 0.0, "m": 0.0, "mix": 0.0}
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
    return parse_shape(shape)["kind"] in ("GL", "SGL")


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


def component_curve(ke, shape, pos, fwhm, area):
    """The component on the ascending KE grid ``ke`` (numpy array), scaled so
    that its integral over the grid is ``area``."""
    np = _np()
    ke = np.asarray(ke, dtype=float)
    sp = parse_shape(shape)
    fwhm = fwhm if fwhm and fwhm > 0 else 1.0
    t = (ke - pos) / fwhm
    lor = 1.0 / (1.0 + 4.0 * t * t)
    if sp["kind"] in ("GL", "SGL"):
        mix = min(max(sp["mix"], 0.0), 100.0) / 100.0
        gau = np.exp(-_LN2_4 * t * t)
        v = (lor ** mix) * (gau ** (1.0 - mix)) if sp["kind"] == "GL" \
            else mix * lor + (1.0 - mix) * gau
        conv = v
    else:
        v = np.where(t < 0, lor ** sp["a"], lor ** sp["b"])
        if sp["w"] > 0:                          # finite tail (LF)
            r = np.abs(t) / sp["w"]
            v = np.where(r < 1, v * (1 - r * r) ** 2, 0.0)
        gw = fwhm * GAUSS_K.get(sp["kind"], 0.0) * (
            25.0 / sp["m"] if sp["m"] else 0.0)
        conv = gauss_conv(ke, v, gw)
    step = abs(ke[1] - ke[0]) if len(ke) > 1 else 1.0
    s = float(conv.sum()) * step
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
