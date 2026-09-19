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
* the holder photo with the analysis positions already placed on it.

Display names and binding-energy shifts are applied (``display``), exactly as
in the app's own exports. No Tk and no matplotlib here.
"""

from __future__ import annotations

import base64
import datetime
import gzip
import html
import json
import os
import re

import annotations as an
import holder
import themes
import viewdata

FORMAT_VERSION = 1
VIEWER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "viewer")
DETAIL_KEYS = ("title", "customer", "reference", "operator", "date",
               "summary")
MAX_PHOTO_BYTES = 6 * 1024 * 1024        # a bigger photo is left out


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


# -- the payload --------------------------------------------------------------------
def _meta(md):
    """Non-empty metadata values as strings, order kept."""
    return {k: str(v) for k, v in md.items() if str(v or "").strip()}


def build_payload(docs, display=None, details=None, methods_text="",
                  calibration="", figures=(), calib=None, generated=None):
    """The data of the browser as a JSON-able dict.

    ``figures`` is ``[{"name", "caption", "pages": [png bytes]}]``; ``calib``
    the holder calibration (or None). ``display(region)`` gives a region as
    exported (renamed, shifted)."""
    details = details or {}
    samples, files = [], []
    n_regions = 0
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
                shift = ann.shift_for(fid, r.sample, r.name)
                marks = [{"be": round(m["be"] + shift, 3),
                          "label": str(m.get("label", ""))}
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
            entry["regions"].append(reg)
            n_regions += 1
        samples += [by_sample[k] for k in order]
    if not n_regions:
        raise ViewerError("There are no spectra with data to put in the "
                          "browser.")
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
    holders = _holder_views(
        docs, calib, lambda p, s: label_map.get((id(p), s), s))
    light, dark = themes.PALETTES["Light"], themes.PALETTES["Dark"]
    return {
        "v": FORMAT_VERSION,
        "generated": (generated or datetime.datetime.now()
                      ).replace(microsecond=0).isoformat(),
        "tool": "ESCApe Explorer",
        "details": {k: str(details.get(k, "") or "") for k in DETAIL_KEYS},
        "methods": methods_text or "", "calibration": calibration or "",
        "files": files, "samples": samples, "figures": figs,
        "holders": holders,
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
