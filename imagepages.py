"""Camera pictures and SnapMaps as pages, for the PDF report and the slides.

Tk-free; matplotlib, numpy and Pillow are imported only when a page is drawn.
:func:`plan` says which pages there are (cheap, geometry only); each
:class:`Page` draws itself onto a matplotlib ``Figure`` given a rectangle, so the
report (an A4 PDF page) and the deck (a picture sized for a slide) share one
drawing:

* **camera sheets**: the calibrated camera pictures, several to a page, each
  with the analysis points that fall in it (its own point highlighted), the
  outline of any SnapMap taken there and a scale bar;
* **SnapMap pages**: one per map site: the camera picture taken there (with the
  map's footprint) beside a grid of element maps, each the counts in the window
  round that element's strongest peak, with its own colour bar.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from types import SimpleNamespace

import mosaic
import reportspec
import snapmap
import snapshot

PICTURE_PX = 640                 # pictures are drawn from a copy this wide at most


@dataclass
class Picture:
    name: str
    sample: str
    parser: object
    blob: object
    points: dict                 # label -> (column, row) in the full-size picture
    outlines: dict               # label -> (left, top, width, height) in pixels
    _array: object = field(default=None, repr=False)
    key: str = ""                # what a report choice calls it (``item_key``)
    _sizes: dict = field(default_factory=dict, repr=False)

    @property
    def calib(self):
        return self.blob.calib

    def array(self, max_px=PICTURE_PX):
        """The picture as an RGB array, shrunk to at most ``max_px`` wide
        (default ``PICTURE_PX``: a PDF page or slide gains nothing from more;
        the mosaic asks for more). Each size is read once."""
        if self._array is not None and max_px == PICTURE_PX:
            return self._array
        if max_px not in self._sizes:
            import numpy as np
            from PIL import Image
            data = self.parser.extract_jpeg(self.blob)
            im = Image.open(io.BytesIO(data)).convert("RGB")
            if im.width > max_px:
                im = im.resize((max_px, round(im.height * max_px
                                              / im.width)), Image.LANCZOS)
            self._sizes[max_px] = np.asarray(im)
        return self._sizes[max_px]


@dataclass
class Site:
    title: str
    maps: list                   # [(shown region, cube)]
    camera: Picture | None = None
    key: str = ""


@dataclass
class Page:
    kind: str                    # "camera" or "maps"
    title: str
    n_items: int
    _draw: object = field(default=None, repr=False)
    _notes: object = field(default=None, repr=False)

    def draw(self, fig, rect=(0.0, 0.0, 1.0, 1.0), cmap=None):
        """Draw onto ``fig`` inside ``rect`` = (left, bottom, right, top) in
        figure fractions. ``cmap`` is the colour map for SnapMaps."""
        self._draw(fig, rect, cmap)

    def notes(self):
        return self._notes() if self._notes else ""


# -- planning ------------------------------------------------------------------------
def item_key(kind, doc, name):
    """The stable id of one camera picture (``kind`` "cam", ``name`` the
    picture's) or SnapMap site ("map", the sample's own name) of a file: what
    a report choice lists as a child of the pictures section."""
    return f"{kind}:{reportspec.doc_key(doc)}/{name}"


def items(docs, label_of=None):
    """``[(key, label)]`` of every calibrated camera picture and SnapMap site
    the files hold, for the Report generator (cheap: no picture is read)."""
    label_of = label_of or (lambda p, s: s)
    out = []
    for p in docs:
        for blob in p.images:
            if snapshot.has_calibration(blob.calib):
                sample = label_of(p, blob.sample) if blob.sample else ""
                # the picture's own name usually says the sample already
                out.append((item_key("cam", p, blob.name), blob.name + (
                    f" – {sample}" if sample and sample not in blob.name
                    else "")))
        seen = []
        for r in p.regions:
            if r.extra.get("cube") is not None and r.sample not in seen:
                seen.append(r.sample)
                out.append((item_key("map", p, r.sample),
                            f"SnapMap – {label_of(p, r.sample)}"))
    return out


def plan(docs, label_of=None, display=None, per_sheet=6, columns=3, skip=(),
         mosaics=False):
    """The pages for ``docs``: camera sheets first, then (with ``mosaics``) one
    page for each set of overlapping pictures stitched together (``mosaic``),
    then one page per SnapMap site. ``label_of(parser, sample)`` gives a
    sample's shown name and ``display(region)`` a region as it should appear
    (names, energy shift); ``skip`` holds the keys (``items``) of pictures and
    sites left out (a picture left out is not drawn beside its map either, nor
    stitched)."""
    label_of = label_of or (lambda p, s: s)
    display = display or (lambda r: r)
    skip = set(skip)
    pictures, sites, sets = [], [], []
    for p in docs:
        positions = {label_of(p, k): xy
                     for k, xy in p.sample_positions().items()}
        cubes = {}                                  # sample -> its map regions
        for r in p.regions:
            if r.extra.get("cube") is not None:
                cubes.setdefault(r.sample, []).append(r)
        first = {label_of(p, s): rs[0].extra["cube"] for s, rs in cubes.items()}
        mine = []
        for blob in p.images:
            if not snapshot.has_calibration(blob.calib):
                continue
            points, outlines = snapshot.view_of(blob.calib, positions, first)
            mine.append(Picture(blob.name, label_of(p, blob.sample)
                                if blob.sample else "", p, blob, points,
                                outlines, key=item_key("cam", p, blob.name)))
        pictures += [m for m in mine if m.key not in skip]
        if mosaics:                       # per file: another holder, another frame
            sets += [(c, positions, first) for c in mosaic.clusters(
                [m for m in mine if m.key not in skip])]
        for sample, rs in cubes.items():
            if item_key("map", p, sample) in skip:
                continue
            cube = rs[0].extra["cube"]
            near = None
            if cube.stage_x_mm is not None:
                b = snapshot.nearest_image([m.blob for m in mine],
                                           cube.stage_x_mm, cube.stage_y_mm)
                near = next((m for m in mine if m.blob is b), None)
                if near is not None and near.key in skip:
                    near = None
            sites.append(Site(label_of(p, sample),
                              [(display(r), r.extra["cube"]) for r in rs],
                              near, item_key("map", p, sample)))
    pages = []
    slots = -(-per_sheet // columns) * columns
    chunks = [pictures[i:i + per_sheet] for i in range(0, len(pictures),
                                                       per_sheet)]
    for n, chunk in enumerate(chunks, 1):
        title = "Camera pictures" + (f" ({n} of {len(chunks)})"
                                     if len(chunks) > 1 else "")
        pages.append(Page(
            "camera", title, len(chunk),
            lambda fig, rect, cmap, c=chunk: draw_sheet(fig, rect, c, columns,
                                                        slots),
            lambda c=chunk: _sheet_notes(c)))
    for n, (cluster, positions, first) in enumerate(sets, 1):
        title = "Camera mosaic" + (f" ({n} of {len(sets)})"
                                   if len(sets) > 1 else "")
        pages.append(Page(
            "mosaic", title, len(cluster),
            lambda fig, rect, cmap, c=cluster, ps=positions, fs=first:
                draw_mosaic(fig, rect, c, ps, fs),
            lambda c=cluster: _mosaic_notes(c)))
    for site in sites:
        pages.append(Page(
            "maps", f"SnapMap – {site.title}", len(site.maps),
            lambda fig, rect, cmap, s=site: draw_site(fig, rect, s, cmap),
            lambda s=site: _site_notes(s)))
    return pages


def mosaic_picture(cluster, positions, sites):
    """``(Mosaic, Picture)``: the stitched pictures as one picture with its
    own calibration, so the analysis points and map outlines on it come from
    ``snapshot.view_of`` like on any camera picture."""
    m = mosaic.build(cluster)
    points, outlines = snapshot.view_of(m.calib, positions, sites)
    pic = Picture(f"Mosaic of {len(cluster)} pictures", "", None,
                  SimpleNamespace(calib=m.calib), points, outlines,
                  _array=m.array)
    return m, pic


def draw_mosaic(fig, rect, cluster, positions, sites):
    """One stitched mosaic filling ``rect``."""
    _m, pic = mosaic_picture(cluster, positions, sites)
    draw_sheet(fig, rect, [pic], 1, 1)


def _mosaic_notes(cluster):
    m = mosaic.build(cluster)
    return "\n".join([f"Mosaic: {m.description()}",
                      "Pictures: " + ", ".join(m.names) + "."] + m.notes)


def available(docs) -> bool:
    """True when ``docs`` hold a calibrated camera picture or a SnapMap."""
    for p in docs:
        if any(snapshot.has_calibration(b.calib) for b in p.images):
            return True
        if any(r.extra.get("cube") is not None for r in p.regions):
            return True
    return False


def window_of(region, cube):
    """The energy window a map is drawn for, in the region's shown energies
    (the first-choice window of ``snapmap.default_window`` plus any shift the
    shown region carries)."""
    lo, hi = snapmap.default_window(cube)
    shift = region.energy[0] - cube.energy[0] if region.energy else 0.0
    return lo + shift, hi + shift


def _sheet_notes(pictures):
    rows = []
    for pic in pictures:
        c = pic.calib
        rows.append(f"{pic.name}: stage {c['x_mm']:.3f}, {c['y_mm']:.3f} mm; "
                    f"field of view "
                    f"{c['width'] * c['um_per_px_x'] / 1000:.1f} x "
                    f"{c['height'] * c['um_per_px_y'] / 1000:.1f} mm.")
    return "\n".join(rows)


def _site_notes(site):
    rows = []
    for region, cube in site.maps:
        try:
            lo, hi = window_of(region, cube)
            rows.append(f"{region.name}: counts summed over {lo:.1f}–"
                        f"{hi:.1f} {region.energy_units or 'eV'}")
        except ImportError:
            rows.append(region.name)
    cube = site.maps[0][1]
    text = (f"SnapMap of {site.title}: {cube.nx} x {cube.ny} pixels of "
            f"{abs(cube.dx):g} µm. Each map has its own colour scale "
            "(1st to 99th percentile of its pixels).\n") + "\n".join(rows)
    if site.camera is not None:
        text += f"\nCamera picture: {site.camera.name}."
    return text


# -- drawing -------------------------------------------------------------------------
def _draw_picture(ax, pic, title_size=7):
    """One camera picture with its markers, map outlines and scale bar."""
    import matplotlib.patheffects as pe
    from matplotlib.patches import Rectangle
    import plots
    c = pic.calib
    w, h = c["width"], c["height"]
    ax.imshow(pic.array(), extent=(0, w, h, 0))
    halo = [pe.withStroke(linewidth=2.5, foreground="#0B1116")]
    for label, (left, top, mw, mh) in pic.outlines.items():
        ax.add_patch(Rectangle((left, top), mw, mh, fill=False, lw=1.0,
                               ls="--", ec="#FFD23F", zorder=2))
        ax.text(max(left, 0) + 4, max(top, 0) + 4, label, color="#FFD23F",
                fontsize=5.5,
                va="top", ha="left", path_effects=halo, zorder=6)
    hot = {pic.sample} if pic.sample else set()
    # a map site is already shown by its outline: no second marker on top
    points = {k: v for k, v in pic.points.items() if k not in pic.outlines}
    marks = plots.draw_holder_markers(ax, points, hot, size=6)
    ax.set_xlim(0, w)
    ax.set_ylim(h, 0)
    ax.set_axis_off()
    ax.set_title(pic.name, fontsize=title_size, pad=2)
    fov = w * c["um_per_px_x"] / 1000.0
    bar_mm = 1.0 if fov >= 4 else 0.5
    bar = bar_mm * 1000.0 / c["um_per_px_x"]
    ax.plot([w * 0.04, w * 0.04 + bar], [h * 0.94] * 2, color="white", lw=2,
            solid_capstyle="butt", path_effects=halo, zorder=6)
    ax.text(w * 0.04 + bar / 2, h * 0.91, f"{bar_mm:g} mm", color="white",
            ha="center", va="bottom", fontsize=6, path_effects=halo, zorder=6)
    ax.apply_aspect()
    try:
        plots.place_marker_labels(ax, marks, hot)
    except Exception:                          # noqa: BLE001 - labels are a nicety
        pass


def draw_sheet(fig, rect, pictures, columns, slots):
    """``pictures`` in a grid ``columns`` wide with ``slots`` cells (so a
    part-filled last sheet keeps the picture size of the others)."""
    left, bottom, right, top = rect
    rows = -(-slots // columns)
    gs = fig.add_gridspec(rows, columns, left=left + 0.01, right=right - 0.01,
                          bottom=bottom, top=top, wspace=0.06, hspace=0.16)
    for i, pic in enumerate(pictures):
        _draw_picture(fig.add_subplot(gs[i // columns, i % columns]), pic)


def draw_site(fig, rect, site, cmap=None):
    """A SnapMap site: the camera picture (if any) and a grid of element maps."""
    import matplotlib
    left, bottom, right, top = rect
    cmap = cmap or matplotlib.colormaps["viridis"]
    n = len(site.maps)
    cols = min(4, n)
    rows = -(-n // cols)
    has_cam = site.camera is not None
    # the grid is as tall as its maps need (about 2 in a row), from the top
    height = min(top - bottom - 0.07, rows * 2.05 / fig.get_figheight())
    gs = fig.add_gridspec(
        rows, cols + (1 if has_cam else 0), left=left + 0.04, right=right - 0.02,
        top=top - 0.03, bottom=top - 0.03 - height, wspace=0.42, hspace=0.42,
        width_ratios=([1.9] if has_cam else []) + [1.0] * cols)
    if has_cam:
        cam_ax = fig.add_subplot(gs[:, 0])
        cam_ax.set_anchor("N")                # top-aligned with the first row
        _draw_picture(cam_ax, site.camera)
    for i, (region, cube) in enumerate(site.maps):
        ax = fig.add_subplot(gs[i // cols, i % cols + (1 if has_cam else 0)])
        lo, hi = snapmap.default_window(cube)
        img = cube.image(lo, hi)
        vmin, vmax = snapmap.colour_range(img)
        im = ax.imshow(img, extent=cube.extent(), cmap=cmap, vmin=vmin,
                       vmax=vmax, interpolation="nearest")
        shift = region.energy[0] - cube.energy[0] if region.energy else 0.0
        ax.set_title(f"{region.name}   {lo + shift:.1f}–{hi + shift:.1f} eV",
                     fontsize=7, pad=3)
        ax.tick_params(labelsize=5.5, length=2, pad=1)
        if i // cols == rows - 1 or i + cols >= n:
            ax.set_xlabel("X (µm)", fontsize=6, labelpad=1)
        if i % cols == 0:
            ax.set_ylabel("Y (µm)", fontsize=6, labelpad=1)
        cb = fig.colorbar(im, ax=ax, fraction=0.05, pad=0.03)
        cb.ax.tick_params(labelsize=5.5, length=2, pad=1)
