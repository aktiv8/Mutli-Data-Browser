"""SnapMap data: an image with a whole spectrum behind every pixel.

Tk-free. A :class:`MapCube` is what a reader hands over in
``Region.extra["cube"]``; the summed spectrum is the ordinary ``Region`` that
the rest of the app plots, and this holds the pixels for the map viewer.

The pixels are kept as one float32 ``array`` (``[iy][ix][channel]``, about 5 MB
for a 100 x 100 x 128 map) so a session with a dozen maps stays light. numpy is
imported only by the functions that make images or masks (matplotlib brings it
in), so the readers still load without it.
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass, field


@dataclass
class MapCube:
    energy: list                 # one value per channel, the axis of Region.energy
    nx: int
    ny: int
    x0: float                    # µm: centre of pixel (0, 0) from the map centre
    dx: float                    # µm per pixel
    y0: float
    dy: float
    data: array = field(repr=False, default=None)   # float32 [iy][ix][channel]
    label: str = "Counts"
    stage_x_mm: float | None = None      # where the map is centred on the stage
    stage_y_mm: float | None = None

    @property
    def n_energy(self) -> int:
        return len(self.energy)

    # -- geometry -----------------------------------------------------------
    def x_of(self, ix) -> float:
        return self.x0 + ix * self.dx

    def y_of(self, iy) -> float:
        return self.y0 + iy * self.dy

    def extent(self):
        """``(left, right, bottom, top)`` of the pixel edges in µm, for
        ``imshow(origin='upper')`` (row 0 at the top)."""
        return (self.x0 - self.dx / 2, self.x0 + (self.nx - 0.5) * self.dx,
                self.y0 + (self.ny - 0.5) * self.dy, self.y0 - self.dy / 2)

    def pixel_at(self, x_um, y_um):
        """``(ix, iy)`` of the pixel containing a point, or None outside."""
        ix = int(round((x_um - self.x0) / self.dx)) if self.dx else -1
        iy = int(round((y_um - self.y0) / self.dy)) if self.dy else -1
        if 0 <= ix < self.nx and 0 <= iy < self.ny:
            return ix, iy
        return None

    # -- spectra ------------------------------------------------------------
    def spectrum_at(self, ix, iy) -> list:
        ne = self.n_energy
        o = (iy * self.nx + ix) * ne
        return list(self.data[o:o + ne])

    def total(self) -> list:
        """The spectrum summed over every pixel."""
        ne = self.n_energy
        return [sum(self.data[c::ne]) for c in range(ne)]

    # -- numpy views --------------------------------------------------------
    def array3d(self):
        """``(ny, nx, channels)`` float32 view of the pixels (no copy)."""
        import numpy as np
        return np.frombuffer(self.data, dtype=np.float32).reshape(
            self.ny, self.nx, self.n_energy)

    def channels(self, lo, hi):
        """Indices of the channels whose energy lies in ``[lo, hi]`` (either
        order), as a ``slice``-compatible boolean numpy mask."""
        import numpy as np
        e = np.asarray(self.energy, dtype=float)
        lo, hi = min(lo, hi), max(lo, hi)
        return (e >= lo) & (e <= hi)

    def image(self, lo=None, hi=None, background=False):
        """``(ny, nx)`` intensity map: the counts summed over an energy window
        (the whole range by default). With ``background`` a straight line
        through the mean of the first and last channel of the window is taken
        off before summing, so a sloping baseline does not show as contrast."""
        import numpy as np
        cube = self.array3d()
        if lo is None or hi is None:
            sel = np.ones(self.n_energy, dtype=bool)
        else:
            sel = self.channels(lo, hi)
        idx = np.flatnonzero(sel)
        if idx.size == 0:
            return np.zeros((self.ny, self.nx))
        part = cube[:, :, idx].astype(np.float64)
        if background and idx.size >= 4:
            k = max(1, idx.size // 8)
            a = part[:, :, :k].mean(axis=2)
            b = part[:, :, -k:].mean(axis=2)
            ramp = np.linspace(0.0, 1.0, idx.size)
            part = part - (a[:, :, None] + (b - a)[:, :, None] * ramp)
        return part.sum(axis=2)

    def roi_spectrum(self, mask) -> list:
        """The spectrum summed over the pixels where the boolean ``(ny, nx)``
        ``mask`` is true."""
        import numpy as np
        mask = np.asarray(mask, dtype=bool)
        if mask.shape != (self.ny, self.nx):
            raise ValueError("mask does not match the map size")
        return self.array3d()[mask].sum(axis=0, dtype=np.float64).tolist()

    def rect_mask(self, x_a, y_a, x_b, y_b):
        """Boolean mask of the pixels whose centres lie in the rectangle with
        corners ``(x_a, y_a)`` and ``(x_b, y_b)`` (µm)."""
        import numpy as np
        xs = self.x0 + np.arange(self.nx) * self.dx
        ys = self.y0 + np.arange(self.ny) * self.dy
        inx = (xs >= min(x_a, x_b)) & (xs <= max(x_a, x_b))
        iny = (ys >= min(y_a, y_b)) & (ys <= max(y_a, y_b))
        return iny[:, None] & inx[None, :]


def build(energy, nx, ny, x0, dx, y0, dy, blocks, label="Counts") -> MapCube:
    """A :class:`MapCube` from ``blocks``: an iterable of
    ``((ix, iy), values)`` with ``values`` one number (or None) per channel.
    Pixels that never arrive stay zero."""
    ne = len(energy)
    data = array("f", bytes(4 * nx * ny * ne))
    for (ix, iy), values in blocks:
        if not (0 <= ix < nx and 0 <= iy < ny):
            continue
        o = (iy * nx + ix) * ne
        data[o:o + ne] = array("f", [0.0 if v is None else v
                                      for v in values[:ne]])
    return MapCube(list(energy), nx, ny, x0, dx, y0, dy, data, label)


# -- helpers for the map viewer ------------------------------------------------
def default_window(cube: MapCube, fraction: float = 0.3,
                   min_width: float = 2.0):
    """``(lo, hi)`` energy window round the strongest feature of the summed
    spectrum, or the whole range when nothing stands above the baseline.

    The straight line between the two ends is taken off first, so a sloping
    background is not mistaken for the peak; the outer tenth of the scan is not
    searched (those channels anchor the line) and a peak nearer the middle wins
    over an equal one at the edge, since a scan is normally set up round the line
    it is after. The window is the contiguous channels above ``fraction`` of the
    peak's height, plus one channel each side, and never narrower than
    ``min_width`` (a real line is not; a noisy top would otherwise leave a sliver).
    (Checked on 24 real SnapMaps:
    the peak is found in every one that has a peak.)"""
    import numpy as np
    y = np.asarray(cube.total(), dtype=float)
    e = np.asarray(cube.energy, dtype=float)
    whole = (float(e.min()), float(e.max()))
    n = y.size
    if n < 10:
        return whole
    ys = np.convolve(np.pad(y, 1, mode="edge"), np.ones(3) / 3, mode="valid")
    k = max(2, n // 20)
    a0, b0 = ys[:k].mean(), ys[-k:].mean()
    res = ys - (a0 + (b0 - a0) * np.linspace(0.0, 1.0, n))
    x = np.linspace(-1.0, 1.0, n)
    score = res * np.exp(-(x / 0.6) ** 2)
    score[:n // 10] = -np.inf
    score[n - n // 10:] = -np.inf
    i = int(np.argmax(score))
    if res[i] <= 0:
        return whole
    thr = fraction * res[i]
    a = b = i
    while a > 0 and res[a - 1] >= thr:
        a -= 1
    while b < n - 1 and res[b + 1] >= thr:
        b += 1
    a, b = max(0, a - 1), min(n - 1, b + 1)
    step = abs(float(e[-1] - e[0])) / (n - 1)
    want = int(round(min_width / step)) if step > 0 else 0
    while b - a < want and (a > 0 or b < n - 1):    # noise can leave it too narrow
        a, b = max(0, a - 1), min(n - 1, b + 1)
    return tuple(sorted((float(e[a]), float(e[b]))))


def colour_range(image, low: float = 1.0, high: float = 99.0):
    """``(vmin, vmax)`` for showing a map: the ``low`` / ``high`` percentiles,
    so one hot pixel does not flatten the rest. Never an empty range."""
    import numpy as np
    a = np.asarray(image, dtype=float)
    a = a[np.isfinite(a)]
    if a.size == 0:
        return 0.0, 1.0
    lo, hi = np.percentile(a, [low, high])
    if hi <= lo:
        lo, hi = float(a.min()), float(a.max())
    if hi <= lo:
        hi = lo + 1.0
    return float(lo), float(hi)


def to_csv_grid(cube: MapCube, image) -> str:
    """A map image as CSV text: a header row of X (µm), then one row per Y
    (µm) whose first field is that Y."""
    import numpy as np
    img = np.asarray(image)
    rows = ["Y/X (um)," + ",".join(f"{cube.x_of(i):g}" for i in range(cube.nx))]
    for iy in range(cube.ny):
        rows.append(f"{cube.y_of(iy):g}," + ",".join(f"{v:.7g}" for v in img[iy]))
    return "\n".join(rows) + "\n"
