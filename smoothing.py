"""Spectrum smoothing for display only (never applied to the data a reader
returns, an export, or a fit). Tk-free; numpy is imported inside the
functions so importing this module costs nothing extra.

Three methods, all numpy-only (no scipy dependency):

* ``savitzky_golay`` — local least-squares polynomial smoothing, the
  standard method in the field.
* ``fourier_lowpass`` — a simple smooth (super-Gaussian) roll-off applied to
  the real FFT, with ``auto_cutoff`` finding the knee between signal and
  noise floor in the log-magnitude spectrum.
* ``gauss_hermite_smooth`` — the actual order-4 Gauss-Hermite filter (a
  faithful port of "Gauss Hermite filter code 2024 Jan.pdf": originally
  written by Long Le Van and David Apsnes, edited by BYU students Kristopher
  Wright and Alvaro J. Lizarbe). Unlike ``fourier_lowpass``, its transfer
  function really is built from a truncated Hermite/Gaussian series, and it
  first removes a line + parabola trend (fitted from the high-frequency,
  noise-only Fourier coefficients) before filtering, so a sloping background
  doesn't ring at the ends of the window the way a bare FFT low-pass can.

``smooth(y, method, strength)`` maps one 0-1 knob onto whichever method's own
parameter, for a single UI control.
"""

from __future__ import annotations

METHODS = ("None", "Savitzky-Golay", "Fourier low-pass", "Gauss-Hermite Smooth")

_GH_X0 = None    # lazily-solved half-power point of the M=4 GH base shape


def savitzky_golay(y, window, order=2):
    """Smooth ``y`` with a local polynomial of the given ``order`` fit over a
    sliding window of ``window`` points (forced odd, clamped to ``len(y)``).

    The filter kernel is the row of ``pinv(A)`` that evaluates the fitted
    polynomial at the window's centre, where ``A`` is the window's Vandermonde
    matrix; convolving it with the (edge-reflected) data reproduces any
    polynomial of degree <= ``order`` exactly away from the edges."""
    import numpy as np
    y = np.asarray(y, dtype=float)
    n = y.size
    if n < 3:
        return y.copy()
    window = int(window)
    if window % 2 == 0:
        window += 1
    max_window = n if n % 2 == 1 else n - 1
    window = max(3, min(window, max_window))
    order = max(0, min(int(order), window - 1))
    half = window // 2
    idx = np.arange(-half, half + 1, dtype=float)
    a = np.vstack([idx ** k for k in range(order + 1)]).T
    kernel = np.linalg.pinv(a)[0]
    padded = np.pad(y, half, mode="reflect")
    return np.correlate(padded, kernel, mode="valid")


def auto_cutoff(y):
    """The Fourier coefficient index where the log-magnitude spectrum bends
    from signal to noise floor: the index that minimises the combined
    residual of two independent straight-line fits before and after it."""
    import numpy as np
    y = np.asarray(y, dtype=float)
    coeffs = np.fft.rfft(y)
    mag = np.abs(coeffs)
    mag[mag == 0] = 1e-300
    log_mag = np.log(mag)
    m = log_mag.size
    if m < 8:
        return max(1, m - 1)
    best_knee, min_err = m // 4, float("inf")
    for knee in range(3, m - 3):
        x1, x2 = np.arange(knee), np.arange(knee, m)
        p1 = np.polyfit(x1, log_mag[:knee], 1)
        p2 = np.polyfit(x2, log_mag[knee:], 1)
        err = (np.sum((log_mag[:knee] - np.polyval(p1, x1)) ** 2)
               + np.sum((log_mag[knee:] - np.polyval(p2, x2)) ** 2))
        if err < min_err:
            min_err, best_knee = err, knee
    return max(1, best_knee)


def fourier_lowpass(y, cutoff=None, order=2):
    """Low-pass ``y`` in the Fourier domain with transfer function
    ``exp(-(k/cutoff)**(2*order))`` (flat near k=0, falling smoothly to zero
    past ``cutoff``). ``cutoff=None`` picks it with :func:`auto_cutoff`."""
    import numpy as np
    y = np.asarray(y, dtype=float)
    n = y.size
    if n < 4:
        return y.copy()
    coeffs = np.fft.rfft(y)
    if cutoff is None:
        cutoff = auto_cutoff(y)
    cutoff = max(1e-6, float(cutoff))
    k = np.arange(coeffs.size, dtype=float)
    transfer = np.exp(-(k / cutoff) ** (2 * order))
    return np.fft.irfft(coeffs * transfer, n=n)


def _gh_half_power_x():
    """The (universal, nc-independent) root x>0 of
    ``exp(-x^2)(1+x^2+x^4/2!+x^6/3!+x^8/4!) = 0.5``: the point on the base
    M=4 shape that :func:`gauss_hermite_transfer` scales to sit at ``nc``."""
    import numpy as np

    def f(x):
        u2 = x * x
        return (np.exp(-u2) * (1 + u2 + u2 ** 2 / 2 + u2 ** 3 / 6
                               + u2 ** 4 / 24) - 0.5)
    lo, hi = 0.0, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def gauss_hermite_transfer(nmax, nc):
    """The order-4 Gauss-Hermite transfer function for harmonic orders
    ``0..nmax-1``, scaled so it crosses 0.5 exactly at harmonic ``nc``."""
    import numpy as np
    global _GH_X0
    if _GH_X0 is None:
        _GH_X0 = _gh_half_power_x()
    n = np.arange(nmax, dtype=float)
    u2 = (n * _GH_X0 / nc) ** 2
    return np.exp(-u2) * (1 + u2 + u2 ** 2 / 2 + u2 ** 3 / 6 + u2 ** 4 / 24)


def gauss_hermite_smooth(y, nc):
    """The order-4 Gauss-Hermite filter: fit and remove a line + parabola
    trend (estimated from the Fourier coefficients above ``nc``, i.e. from
    the noise floor, by least squares), apply :func:`gauss_hermite_transfer`
    to the detrended coefficients, then add the trend back. ``nc`` is the
    harmonic order kept as signal — a smaller ``nc`` smooths more."""
    import numpy as np
    y = np.asarray(y, dtype=float)
    n_pts = y.size
    if n_pts < 8:
        return y.copy()
    nmax = n_pts // 2 + 1
    nc = max(1, min(int(round(nc)), nmax - 2))
    j0 = (n_pts - 1) / 2.0
    dj = np.arange(n_pts, dtype=float) - j0
    n = np.arange(nmax, dtype=float)
    angle = 2.0 * np.pi * np.outer(n, dj) / n_pts        # (nmax, n_pts)
    cos_a, sin_a = np.cos(angle), np.sin(angle)

    def coeffs(values):
        a = (2.0 / n_pts) * (cos_a @ values)
        b = (2.0 / n_pts) * (sin_a @ values)
        a[0] /= 2.0
        if n_pts % 2 == 0:
            a[-1] = 0.0
            b[-1] /= 2.0
        return a, b

    a_coef, b_coef = coeffs(y)
    line = dj / n_pts
    parabola = dj ** 2 / (2.0 * n_pts ** 2)
    ap_coef, _ = coeffs(parabola)
    _, bl_coef = coeffs(line)

    tail = slice(nc, nmax)
    cl2 = float(np.sum(bl_coef[tail] ** 2))
    cp2 = float(np.sum(ap_coef[tail] ** 2))
    c1 = float(np.sum(b_coef[tail] * bl_coef[tail]) / cl2) if cl2 else 0.0
    c2 = float(np.sum(a_coef[tail] * ap_coef[tail]) / cp2) if cp2 else 0.0

    an = a_coef - c2 * ap_coef
    bn = b_coef - c1 * bl_coef
    tf = gauss_hermite_transfer(nmax, nc)
    smoothed = (an * tf) @ cos_a + (bn * tf) @ sin_a
    return smoothed + c1 * line + c2 * parabola


def smooth(y, method, strength=0.5):
    """Apply ``method`` (one of :data:`METHODS`) to ``y``, with ``strength``
    in [0, 1] standing in for each method's own parameter: window length 5-31
    for Savitzky-Golay, and a multiplier on :func:`auto_cutoff` (2x at 0,
    1x — the plain auto cutoff — at 0.5, 0.3x at 1) for the two Fourier-based
    filters (used directly as the cutoff for the low-pass, and as ``nc`` for
    the Gauss-Hermite filter). ``"None"`` and inputs too short to smooth are
    returned unchanged."""
    import numpy as np
    y = np.asarray(y, dtype=float)
    if method not in METHODS:
        raise ValueError(f"unknown smoothing method: {method!r}")
    if method == "None" or y.size < 3:
        return y.copy()
    strength = min(1.0, max(0.0, float(strength)))
    if method == "Savitzky-Golay":
        window = int(round(np.interp(strength, [0.0, 1.0], [5, 31])))
        return savitzky_golay(y, window, order=2)
    base = auto_cutoff(y)
    mult = float(np.interp(strength, [0.0, 0.5, 1.0], [2.0, 1.0, 0.3]))
    if method == "Fourier low-pass":
        return fourier_lowpass(y, cutoff=max(1.0, base * mult), order=2)
    return gauss_hermite_smooth(y, nc=max(1, int(round(base * mult))))
