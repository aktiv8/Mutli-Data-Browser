"""The offline HTML data browser: one self-contained ``.html`` file that opens
in any modern browser with no server, no network and no libraries.

The page (``viewer/``: template, CSS and JavaScript) is inlined together with
the data. The data are one JSON document, gzip-compressed and base64-encoded
(the page decodes it with the browser's ``DecompressionStream``):

* every sample and spectrum (energy as start/step/count when the grid is
  regular, intensity to seven significant digits, per-spectrum metadata, notes
  and peak markers),
* the saved figures as pre-rendered PNGs with their captions,
* the methods text, the calibration statement and the workbook details,
* the holder photo with the analysis positions already placed on it,
* the sample-view camera pictures (shrunk to JPEG) with the analysis points and
  SnapMap outlines that fall in each already placed, and
* every SnapMap as its pixels (16-bit counts in steps of 1/8, deflated) so the
  page can redraw the map for any energy window and area.

Display names and binding-energy shifts are applied (``display``), exactly as
in the app's own exports. No Tk and no matplotlib here.
"""

from __future__ import annotations

import base64
import datetime
import gzip
import html
import io
import json
import os
import re
import zlib

import annotations as an
import appinfo
import holder
import quant
import snapshot
import themes
import viewdata
import xpslines

FORMAT_VERSION = 1
VIEWER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "viewer")
DETAIL_KEYS = ("title", "customer", "reference", "operator", "date",
               "summary")
MAX_PHOTO_BYTES = 6 * 1024 * 1024        # a bigger photo is left out
CAMERA_MAX_PX = 800                      # longest side of an embedded camera picture
CAMERA_QUALITY = 78                      # JPEG quality
CAMERA_BUDGET = 40 * 1024 * 1024         # pictures beyond this are left out
MAP_STEP = 0.125                         # counts per step of a stored map value
MAP_BUDGET = 40 * 1024 * 1024            # compressed SnapMap bytes; see pack_maps
SURVEY_SPAN = 250.0                      # eV: wider than this is a survey
FIT_DIGITS = 6                          # significant figures of a fit curve
FIT_BUDGET = 600_000                     # curve values in all; see _fit_block


class ViewerError(Exception):
    """The browser could not be built (message is user-facing)."""


# -- numbers ------------------------------------------------------------------
def round_sig(v, digits=7):
    """``v`` to ``digits`` significant figures (as a float; 0 stays 0)."""
    if v == 0 or v != v or v in (float("inf"), float("-inf")):
        return v if v == v else None
    return float(f"{v:.{digits - 1}e}")


def pack_axis(xs):
    """An energy axis as ``{"x0", "dx", "n"}`` when it is a regular grid (the
    usual case; saves most of the size), else the list rounded to 1e-4 eV."""
    n = len(xs)
    if n >= 3:
        dx = (xs[-1] - xs[0]) / (n - 1)
        tol = max(abs(dx), 1e-12) * 1e-6
        if dx and all(abs(xs[i] - (xs[0] + dx * i)) <= tol for i in range(n)):
            return {"x0": round(xs[0], 6), "dx": float(f"{dx:.9g}"), "n": n}
    return [round(x, 4) for x in xs]


def pack_counts(ys):
    return [round_sig(y) for y in ys]


# -- images -----------------------------------------------------------------------
def jpeg_size(data):
    """``(width, height)`` of a JPEG from its header, or None."""
    if data[:2] != b"\xff\xd8":
        return None
    i, n = 2, len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if marker == 0xFF:
            i += 1
            continue
        length = int.from_bytes(data[i + 2:i + 4], "big")
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h = int.from_bytes(data[i + 5:i + 7], "big")
            w = int.from_bytes(data[i + 7:i + 9], "big")
            return (w, h) if w and h else None
        i += 2 + max(length, 2)
    return None


def data_uri(mime, data):
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def _holder_views(docs, calib, label_of):
    """One entry per file that has a usable holder photo: the photo, its size
    and, with a calibration, the pixel position of every sample."""
    out = []
    for p in docs:
        for blob in getattr(p, "images", []) or []:
            if blob.fmt != "jpeg" or blob.calib:      # camera pictures: not a holder
                continue                              # photo, and slow to decode
            jpeg = p.extract_jpeg(blob)
            size = jpeg_size(jpeg) if jpeg else None
            if not jpeg or not size or len(jpeg) > MAX_PHOTO_BYTES:
                continue
            w, h = size
            points = {}
            if calib:
                pts = holder.marker_points(p.sample_positions(), w, h, calib)
                points = {label_of(p, s): [round(x, 1), round(y, 1)]
                          for s, (x, y) in pts.items()}
            out.append({"file": os.path.basename(p.path or ""),
                        "photo": data_uri("image/jpeg", jpeg), "w": w, "h": h,
                        "points": points})
            break                                    # one photo per file
    return out


# -- camera pictures --------------------------------------------------------------
def shrink_picture(data, max_px=CAMERA_MAX_PX, quality=CAMERA_QUALITY):
    """``(jpeg bytes, width, height)`` of an image, no side longer than
    ``max_px``; needs Pillow."""
    from PIL import Image
    im = Image.open(io.BytesIO(data)).convert("RGB")
    k = min(1.0, max_px / max(im.size))
    if k < 1.0:
        im = im.resize((max(1, round(im.width * k)),
                        max(1, round(im.height * k))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue(), im.width, im.height


def _camera_views(docs, label_of, notes):
    """One entry per calibrated camera picture: the shrunk JPEG, the analysis
    points inside it and the outline of each SnapMap taken on it (all in the
    shrunk picture's pixels). Returns ``(views, {id(blob): view id})``."""
    views, ids = [], {}
    try:
        import PIL  # noqa: F401
    except ImportError:
        if any(snapshot.has_calibration(b.calib) for p in docs
               for b in p.images):
            notes.append("Camera pictures were left out: Pillow is not "
                         "installed.")
        return views, ids
    used, left_out = 0, 0
    for fi, p in enumerate(docs):
        positions = {label_of(p, k): xy
                     for k, xy in p.sample_positions().items()}
        sites = {}                                # one map per site
        for r in p.regions:
            if r.extra.get("cube") is not None:
                sites.setdefault(label_of(p, r.sample), r.extra["cube"])
        for blob in p.images:
            if not snapshot.has_calibration(blob.calib):
                continue
            png = p.extract_jpeg(blob)
            if not png:
                continue
            try:
                jpeg, w, h = shrink_picture(png)
            except Exception:                           # noqa: BLE001
                left_out += 1
                continue
            if used + len(jpeg) > CAMERA_BUDGET:
                left_out += 1
                continue
            used += len(jpeg)
            cal = blob.calib
            k = w / cal["width"]
            found, boxes = snapshot.view_of(cal, positions, sites)
            pts = {n: [round(c * k, 1), round(r * k, 1)]
                   for n, (c, r) in found.items()}
            outlines = [{"sample": n, "rect": [round(v * k, 1) for v in box]}
                        for n, box in boxes.items()]
            fov = snapshot.field_of_view_mm(cal)
            view = {"id": f"c{len(views)}", "name": blob.name,
                    "sample": label_of(p, blob.sample) if blob.sample else "",
                    "file": fi, "w": w, "h": h,
                    "img": data_uri("image/jpeg", jpeg),
                    "fov": [round(fov[0], 3), round(fov[1], 3)],
                    "stage": [round(cal["x_mm"], 4), round(cal["y_mm"], 4)],
                    "points": pts, "maps": outlines,
                    "bar_px": round(1000.0 / cal["um_per_px_x"] * k, 2)}
            views.append(view)
            ids[id(blob)] = view["id"]
    if left_out:
        notes.append(f"{left_out} camera picture(s) were left out (size limit "
                     f"or unreadable).")
    return views, ids


# -- SnapMaps ---------------------------------------------------------------------
def pack_cube(cube, energy, rebin=1, step=MAP_STEP):
    """A SnapMap's pixels for the page: counts as 16-bit steps of ``step`` (or
    coarser when the map is very bright), deflated. ``rebin`` sums that many
    neighbouring energy channels. Returns ``(entry, compressed bytes)``;
    needs numpy."""
    import numpy as np
    a = cube.array3d().astype(np.float64)
    e = np.asarray(energy, dtype=float)
    if rebin > 1:
        n = a.shape[2] // rebin * rebin
        a = a[:, :, :n].reshape(cube.ny, cube.nx, n // rebin,
                                rebin).sum(axis=3)
        e = e[:n].reshape(-1, rebin).mean(axis=1)
    q = max(step, float(a.max()) / 65535.0)
    z = zlib.compress(
        np.clip(np.rint(a / q), 0, 65535).astype("<u2").tobytes(), 6)
    return ({"nx": cube.nx, "ny": cube.ny, "x0": cube.x0, "dx": cube.dx,
             "y0": cube.y0, "dy": cube.dy, "n": int(a.shape[2]),
             "e": pack_axis(list(e)), "q": q,
             "z": base64.b64encode(z).decode("ascii")}, len(z))


def pack_maps(items, budget=MAP_BUDGET):
    """Pack ``items`` (``[(cube, energy)]``) within ``budget`` compressed bytes:
    at full energy resolution if that fits, else summing 2, then 4 channels,
    else leaving out the last maps. Returns ``(entries, rebin, n_left_out)``
    with ``entries`` aligned to the maps kept (a prefix of ``items``)."""
    for rebin in (1, 2, 4):
        packed = [pack_cube(c, e, rebin) for c, e in items]
        if sum(n for _e, n in packed) <= budget:
            return [e for e, _n in packed], rebin, 0
    kept, total = [], 0
    for entry, n in packed:
        if total + n > budget:
            break
        kept.append(entry)
        total += n
    return kept, 4, len(items) - len(kept)


def _map_entries(src, cam_ids, label_of, notes):
    """The page's SnapMap list; also sets ``reg["map"]`` on each map's
    spectrum so the tree can offer to open it."""
    if not src:
        return []
    try:
        import numpy  # noqa: F401
    except ImportError:
        notes.append("SnapMaps were left out: numpy is not installed.")
        return []
    packed, rebin, dropped = pack_maps(
        [(r.extra["cube"], d.energy) for _p, r, d, _reg in src],
        budget=MAP_BUDGET)
    if rebin > 1:
        notes.append(f"SnapMaps are stored with {rebin} energy channels summed "
                     f"into one (size limit).")
    if dropped:
        notes.append(f"{dropped} SnapMap(s) were left out (size limit).")
    out = []
    for (p, r, d, reg), entry in zip(src, packed):
        cube = r.extra["cube"]
        mid = f"m{len(out)}"
        entry.update(id=mid, region=reg["id"], sample=label_of(p, r.sample),
                     name=d.name, stage=None, cam=None)
        if cube.stage_x_mm is not None:
            entry["stage"] = [round(cube.stage_x_mm, 4),
                              round(cube.stage_y_mm, 4)]
            near = snapshot.nearest_image(
                [b for b in p.images if id(b) in cam_ids],
                cube.stage_x_mm, cube.stage_y_mm)
            if near is not None:
                cal = near.calib
                cx, cy = snapshot.stage_to_pixel(cal, cube.stage_x_mm,
                                                 cube.stage_y_mm)
                ux, uy = cal["um_per_px_x"], cal["um_per_px_y"]
                # the picture's edges in the map's own micrometres
                entry["cam"] = {"id": cam_ids[id(near)], "ext": [
                    round(v, 2) for v in (-cx * ux, (cal["width"] - cx) * ux,
                                          (cal["height"] - cy) * uy,
                                          -cy * uy)]}
        reg["map"] = mid
        out.append(entry)
    return out


# -- CasaXPS fits ------------------------------------------------------------------
def fit_notes(rows):
    """The caveats of a fit, as the app's plots state them."""
    out = []
    if any(r["approximate"] for r in rows):
        out.append("LA / LF line shapes are reconstructed")
    unknown = sorted({r["background"] for r in rows
                      if not r["background_known"]})
    if unknown:
        out.append(", ".join(unknown) + " background not reproduced, "
                   "components only")
    if not all(r["scale_known"] for r in rows):
        out.append("dwell time unknown, curves in counts/s")
    return out


def _round_curve(values):
    return None if values is None else [
        None if v is None else round_sig(v, FIT_DIGITS) for v in values]


def _fit_block(d, budget):
    """The CasaXPS fit of a (display) region for the page, or None: for every
    fit region its numbers (``quant.fit_rows``: RSF, area, limits, components
    with their positions) and the curves that draw it (background, envelope,
    components from the region's first point on, so ``y - env`` is the
    residual). ``budget`` is a one-item list counting the curve values left;
    curves that would not fit are left out and the table stays."""
    rows = quant.fit_rows(d, curves=True)
    if not rows:
        return None
    out, dropped = [], False
    for row in rows:
        cur = row.pop("curves", None)
        if cur:
            n = sum(len(c) for c in [cur["bg"], cur["env"]] + cur["comps"]
                    if c)
            if n > budget[0]:
                cur, dropped = None, True
            else:
                budget[0] -= n
                cur = {"i0": cur["i0"], "bg": _round_curve(cur["bg"]),
                       "env": _round_curve(cur["env"]),
                       "comps": [_round_curve(c) for c in cur["comps"]]}
        row["curve"] = cur
        for k in ("area", "area_t", "be_lo", "be_hi", "rms"):
            if row.get(k) is not None:
                row[k] = round_sig(row[k], 7)
        for c in row["components"]:
            c["be"] = round(c["be"], 4)
        out.append(row)
    return {"rows": out, "notes": fit_notes(rows), "dropped": dropped}


# -- element identification ----------------------------------------------------------
def element_table(lines):
    """The line table for the page's candidate lookup (what ``xpslines`` uses):
    ``lines`` as ``[element, line, be, ke, rank]`` (one of be / ke is null;
    Auger lines give a kinetic energy), the elements that win close calls, and
    the defaults."""
    return {"lines": [[e["el"], e["line"], e.get("be"), e.get("ke"),
                       e.get("rank", 1)] for e in lines],
            "common": sorted(xpslines.COMMON),
            "bonus": xpslines.COMMON_BONUS, "hv": xpslines.DEFAULT_HV}


def auto_labels(d, lines):
    """Automatic element labels for a survey (a binding-energy spectrum wider
    than ``SURVEY_SPAN``), as ``xpslines.auto_label`` gives them on the
    spectrum as shown; [] for anything else."""
    if (not lines or not d.photon_energy or not viewdata.is_binding(d)
            or not d.energy
            or max(d.energy) - min(d.energy) <= SURVEY_SPAN):
        return []
    found = xpslines.auto_label(d.energy, d.counts, lines, hv=d.photon_energy)
    return [{"be": round(be, 2), "label": label} for be, label in found]


# -- the payload --------------------------------------------------------------------
_PATH = re.compile(r"(?<![\w:/.])(?:[A-Za-z]:[\\/]|\\\\[^\s\\/]+[\\/]"
                   r"|/(?:Users|home|mnt|media|Volumes|tmp|var)/)"
                   r"[^\s\"'<>|*?]*")


def scrub_paths(text):
    """``text`` with every absolute file path (``C:\\lab\\run\\a.vms``, a network
    share, ``/home/x/a.vms``) cut down to its file or folder name: a page that
    is sent to a customer must not tell them where the data lived."""
    def base(m):
        parts = re.split(r"[\\/]+", m.group(0).rstrip("\\/"))
        return parts[-1] if parts and parts[-1] else ""
    return _PATH.sub(base, text)


def _meta(md):
    """Non-empty metadata values as strings, order kept; paths cut to names."""
    return {k: scrub_paths(str(v)) for k, v in md.items()
            if str(v or "").strip()}


def build_payload(docs, display=None, details=None, methods_text="",
                  calibration="", figures=(), calib=None, generated=None,
                  cameras=True, snapmaps=True, lines=None):
    """The data of the browser as a JSON-able dict.

    ``figures`` is ``[{"name", "caption", "pages": [png bytes]}]``; ``calib``
    the holder calibration (or None). ``display(region)`` gives a region as
    exported (renamed, shifted). ``cameras`` / ``snapmaps`` switch the camera
    pictures and the SnapMap pixels off; anything left out or thinned to fit
    the size limits is said in ``build_notes``. ``lines`` is the element-line
    table (default: ``xpslines.load_lines()``); it feeds the page's peak
    identification and the automatic labels of surveys."""
    details = details or {}
    element_lines = xpslines.load_lines() if lines is None else lines
    samples, files, notes = [], [], []
    map_src = []                     # (parser, region, shown region, its dict)
    n_regions = 0
    fit_budget, fit_dropped = [FIT_BUDGET], 0
    label_map = {}                       # (id(parser), original sample) -> label
    for fi, p in enumerate(docs):
        ann = getattr(p, "annotations", None)
        fid = getattr(p, "file_id", "")
        files.append({"name": os.path.basename(p.path or ""),
                      "format": p.format_name})
        order, by_sample = [], {}
        for pos, r in enumerate(p.regions):
            if not (r.decodable and r.counts and r.energy):
                continue
            d = display(r) if display else r
            entry = by_sample.get(r.sample)
            if entry is None:
                note = ""
                if ann is not None:
                    note = ann.sample_notes.get(an.sample_key(fid, r.sample),
                                                "")
                entry = by_sample[r.sample] = {
                    "name": d.sample, "file": fi, "note": note,
                    "regions": []}
                order.append(r.sample)
                label_map[(id(p), r.sample)] = d.sample
            rnote, marks = "", []
            if ann is not None:
                rnote = ann.region_notes.get(
                    an.region_key(fid, r.sample, r.name), "")
                shift = ann.shift_for(fid, r.sample, r.name,
                                      r.calibration_shift)
                marks = [{"be": round(m["be"] + (0.0 if m.get("kin") else shift),
                                      3),
                          "label": str(m.get("label", "")),
                          **({"kin": True} if m.get("kin") else {})}
                         for m in ann.markers_for(fid, r.sample, r.name)]
            reg = {
                "name": d.name, "e": pack_axis(list(d.energy)),
                "y": pack_counts(list(d.counts)),
                "binding": bool(viewdata.is_binding(d)),
                "elabel": d.energy_label, "eunits": d.energy_units,
                "ylabel": d.count_label, "yunits": d.count_units,
                "hv": d.photon_energy,
                "level": d.etch_level, "etch": d.etch_time,
                "meta": _meta(p.region_metadata(r)), "note": rnote,
                "markers": marks,
            }
            auto = auto_labels(d, element_lines)
            if auto:
                reg["auto"] = auto
            fit = _fit_block(d, fit_budget) if getattr(d, "fit", None) else None
            if fit:
                reg["fit"] = fit
                fit_dropped += bool(fit.pop("dropped"))
            entry["regions"].append(reg)
            if snapmaps and r.extra.get("cube") is not None:
                map_src.append((p, r, d, reg))
            n_regions += 1
        samples += [by_sample[k] for k in order]
    if not n_regions:
        raise ViewerError("There are no spectra with data to put in the "
                          "browser.")
    if fit_dropped:
        notes.append(f"Fit curves were left out of {fit_dropped} "
                     f"spectr{'um' if fit_dropped == 1 else 'a'} to keep the "
                     "file small; their fit tables are still there.")
    for i, s in enumerate(samples):
        s["id"] = f"s{i}"
        for j, r in enumerate(s["regions"]):
            r["id"] = f"s{i}r{j}"

    figs = []
    for f in figures:
        pages = [data_uri("image/png", b) for b in f.get("pages", []) if b]
        if pages:
            figs.append({"name": f.get("name", ""),
                         "caption": f.get("caption", ""), "pages": pages})
    calib = holder.sanitise(calib) if calib else None
    label_of = lambda p, s: label_map.get((id(p), s), s)       # noqa: E731
    holders = _holder_views(docs, calib, label_of)
    cams, cam_ids = (_camera_views(docs, label_of, notes) if cameras
                     else ([], {}))
    maps = _map_entries(map_src, cam_ids, label_of, notes)
    light, dark = themes.PALETTES["Light"], themes.PALETTES["Dark"]
    return {
        "v": FORMAT_VERSION,
        "generated": (generated or datetime.datetime.now()
                      ).replace(microsecond=0).isoformat(),
        "tool": appinfo.NAME,
        "details": {k: str(details.get(k, "") or "") for k in DETAIL_KEYS},
        "methods": methods_text or "", "calibration": calibration or "",
        "files": files, "samples": samples, "figures": figs,
        "holders": holders, "cameras": cams, "maps": maps,
        "elements": element_table(element_lines),
        "build_notes": notes,
        "palette": {"light": list(light["cycle"]), "dark": list(dark["cycle"]),
                    "bg": {"light": light["plot_bg"], "dark": dark["plot_bg"]}},
    }


# -- encoding and the page ---------------------------------------------------------------
def encode_payload(payload) -> str:
    """gzip + base64 of the JSON (what the page decodes)."""
    raw = json.dumps(payload, ensure_ascii=False,
                     separators=(",", ":")).encode("utf-8")
    return base64.b64encode(gzip.compress(raw, 9, mtime=0)).decode("ascii")


def decode_payload(text) -> dict:
    """Inverse of ``encode_payload`` (used by the tests)."""
    return json.loads(gzip.decompress(base64.b64decode(text)).decode("utf-8"))


def _read(name):
    path = os.path.join(VIEWER_DIR, name)
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        raise ViewerError(f"The viewer file {name} is missing "
                          f"(expected in {VIEWER_DIR}).")


def _script_safe(js):
    """JavaScript that cannot close the surrounding <script> element."""
    return js.replace("</script", "<\\/script")


def build_html(payload) -> str:
    """The complete page as text."""
    title = (payload.get("details", {}).get("title") or "").strip() \
        or "Experiment data browser"
    page = _read("template.html")
    for key, value in (("__TITLE__", html.escape(title)),
                       ("/*__CSS__*/", _read("viewer.css")),
                       ("/*__JS__*/", _script_safe(_read("viewer.js"))),
                       ("__DATA__", encode_payload(payload))):
        if key not in page:
            raise ViewerError(f"viewer/template.html lacks {key}.")
        page = page.replace(key, value, 1)
    return page


def write_html(path, payload) -> int:
    """Write the browser to ``path`` (atomically). Returns its size in bytes."""
    text = build_html(payload)
    data = text.encode("utf-8")
    folder = os.path.dirname(os.path.abspath(path))
    tmp = os.path.join(folder, f".{os.path.basename(path)}.tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return len(data)


def default_name(details) -> str:
    stem = re.sub(r"[^\w.\- ]+", "_",
                  (details or {}).get("title") or "experiment").strip()
    return (stem or "experiment") + " - data browser.html"
