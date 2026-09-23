"""Spectrum smoothing for display only (never applied to the data a reader
returns, an export, or a fit). Tk-free; numpy is imported inside the
functions so importing this module costs nothing extra.

Two methods, both numpy-only (no scipy dependency):

* ``savitzky_golay`` — local least-squares polynomial smoothing, the
  standard method in the field.
* ``fourier_lowpass`` — a smooth (super-Gaussian) roll-off applied to the
  real FFT, with ``auto_cutoff`` finding the knee between signal and noise
  floor in the log-magnitude spectrum. (Marketed elsewhere as a
  "Gauss-Hermite filter"; the transfer function has nothing to do with
  Hermite polynomials or Gauss-Hermite quadrature — it is an ordinary
  frequency-domain low-pass filter.)

``smooth(y, method, strength)`` maps one 0-1 knob onto either method's own
parameter, for a single UI control.
"""

from __future__ import annotations

METHODS = ("None", "Savitzky-Golay", "Fourier low-pass")


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


def smooth(y, method, strength=0.5):
    """Apply ``method`` (one of :data:`METHODS`) to ``y``, with ``strength``
    in [0, 1] standing in for each method's own parameter: window length 5-31
    for Savitzky-Golay, and a multiplier on :func:`auto_cutoff` (2x at 0,
    1x — the plain auto cutoff — at 0.5, 0.3x at 1) for the Fourier filter.
    ``"None"`` and inputs too short to smooth are returned unchanged."""
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
    return fourier_lowpass(y, cutoff=max(1.0, base * mult), order=2)
