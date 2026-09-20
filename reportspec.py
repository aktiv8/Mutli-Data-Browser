"""What goes into a report, and in what order: one choice for the PDF, the
slides and the hand-over package.

Tk-free. A *spec* is a plain dict (so it is saved as JSON in the config, in the
workbook and in named presets)::

    {"version": 1,
     "sections": [{"id": "cover", "on": True}, ...],     # this order is the order
     "skip": {"figures": ["fig2"], "metadata": ["f3"]},  # children switched off
     "options": {"sha": "short", "dividers": "auto"},
     "cover": {"design": "ribbon", "image": "", "accent": ""}}   # see covers

Children that are not listed in ``skip`` are on, so a figure or file added
later appears in the report without the choice being redone. ``sanitise`` makes
any input a full, valid spec (unknown sections dropped, new ones added, bad
options reset), which is how a spec from an older or newer build, a preset or a
hand-edited file is read.

The builders (``report.build_report``, ``pptx_export.build_deck``) take the spec
through ``active``; the old ``sections=`` arguments still work and are turned
into a spec by ``spec_from_sections``.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field

import covers

VERSION = 1

# id, label, what it holds. Order here is the default report order: what the
# reader came for first, the audit trail (methods, metadata, checksums) after.
SECTION_DEFS = (
    ("cover", "Cover page", "Title, customer, date, logo"),
    ("contents", "Contents", "Sections and their pages"),
    ("summary", "Summary", "Your summary text"),
    ("figures", "Figures", "The saved figures"),
    ("images", "Camera pictures and SnapMaps", "Photos and map sites"),
    ("methods", "Methods", "How the data were acquired"),
    ("calibration", "Energy calibration", "Binding-energy statement"),
    ("metadata", "Acquisition metadata", "Instrument settings, per file"),
    ("files", "Data files", "Names, sizes and checksums"),
)
SECTION_IDS = tuple(s[0] for s in SECTION_DEFS)
SHORT = {"cover": "Cover", "contents": "Contents", "summary": "Summary", "figures": "Figures",
         "images": "Pictures", "methods": "Methods",
         "calibration": "Calibration", "metadata": "Metadata",
         "files": "Files"}
LABELS = {s[0]: s[1] for s in SECTION_DEFS}
HINTS = {s[0]: s[2] for s in SECTION_DEFS}
CHILD_KINDS = {"figures": "figure", "metadata": "file"}

# The order the reports had before there was a choice; used for ``sections=``.
LEGACY_ORDER = ("cover", "contents", "summary", "methods", "calibration", "files",
                "metadata", "images", "figures")
# What each old section name switched on, per output.
LEGACY_PDF = {"cover": ("cover", "summary", "methods", "calibration", "files"),
              "metadata": ("metadata",), "images": ("images",),
              "figures": ("figures",)}
LEGACY_DECK = {"title": ("cover", "summary", "methods", "calibration"),
               "files": ("files",), "metadata": ("metadata",),
               "images": ("images",), "figures": ("figures",)}

# option -> allowed values: the checksum column of the file list, and whether
# the slides get a divider slide before a long section ("auto": 5 slides or more)
OPTIONS = {"sha": ("short", "none"), "dividers": ("auto", "none")}
DEFAULT_OPTIONS = {"sha": "short", "dividers": "auto"}
# The cover picture (see ``covers``): a design id, the file for the 'image'
# design, and the accent colour ('' = the default one).
DEFAULT_COVER = {"design": "ribbon", "image": "", "accent": ""}


def default_spec():
    """Every section on, in the default (results-first) order."""
    return {"version": VERSION,
            "sections": [{"id": i, "on": True} for i in SECTION_IDS],
            "skip": {}, "options": dict(DEFAULT_OPTIONS),
            "cover": dict(DEFAULT_COVER)}


def sanitise(spec=None):
    """A full, valid copy of ``spec`` (anything else gives the default)."""
    out = default_spec()
    if not isinstance(spec, dict):
        return out
    seen, sections = set(), []
    raw = spec.get("sections")
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        sid = item.get("id")
        if sid in SECTION_IDS and sid not in seen:
            seen.add(sid)
            sections.append({"id": sid, "on": bool(item.get("on", True))})
    for k, sid in enumerate(SECTION_IDS):         # a section the spec predates:
        if sid not in seen:                       # after the one before it
            before = [x for x in SECTION_IDS[:k] if x in seen]
            at = 1 + next((i for i, s in enumerate(sections)
                           if s["id"] == before[-1]), -1) if before else 0
            sections.insert(at, {"id": sid, "on": True})
            seen.add(sid)
    out["sections"] = sections
    skip = spec.get("skip")
    if isinstance(skip, dict):
        for sid, ids in skip.items():
            if sid in CHILD_KINDS and isinstance(ids, list):
                kept = [str(i) for i in dict.fromkeys(ids)]
                if kept:
                    out["skip"][sid] = kept
    opts = spec.get("options")
    for key, allowed in OPTIONS.items():
        val = opts.get(key) if isinstance(opts, dict) else None
        out["options"][key] = val if val in allowed else DEFAULT_OPTIONS[key]
    cov = spec.get("cover")
    if isinstance(cov, dict):
        design = cov.get("design")
        if isinstance(design, str) and 0 < len(design) <= 300:
            out["cover"]["design"] = design
        image = cov.get("image")
        if isinstance(image, str) and len(image) <= 1000:
            out["cover"]["image"] = image
        out["cover"]["accent"] = covers.valid_accent(cov.get("accent"))
    return out


def copy_spec(spec):
    return sanitise(copy.deepcopy(spec))


def same(a, b):
    """True when two specs choose the same thing."""
    return sanitise(a) == sanitise(b)


# -- reading a spec ----------------------------------------------------------
def order(spec):
    return [s["id"] for s in sanitise(spec)["sections"]]


def is_on(spec, sid):
    return any(s["id"] == sid and s["on"] for s in sanitise(spec)["sections"])


def skipped(spec, sid):
    return set(sanitise(spec)["skip"].get(sid, ()))


def option(spec, key):
    return sanitise(spec)["options"][key]


def active(spec, present=None):
    """``[(section id, set of skipped child ids)]`` for the sections that are
    on, in order. ``present`` (a set of ids, e.g. ``Inventory.present_ids()``)
    drops sections that have nothing to show."""
    spec = sanitise(spec)
    out = []
    for s in spec["sections"]:
        if not s["on"] or (present is not None and s["id"] not in present):
            continue
        out.append((s["id"], set(spec["skip"].get(s["id"], ()))))
    return out


# -- changing a spec (each returns a new spec) --------------------------------
def with_on(spec, sid, on):
    out = sanitise(spec)
    for s in out["sections"]:
        if s["id"] == sid:
            s["on"] = bool(on)
    return out


def with_all(spec, on):
    out = sanitise(spec)
    for s in out["sections"]:
        s["on"] = bool(on)
    out["skip"] = {}
    return out


def moved(spec, sid, delta):
    """``sid`` moved ``delta`` places (negative: earlier), clamped."""
    out = sanitise(spec)
    ids = [s["id"] for s in out["sections"]]
    if sid not in ids:
        return out
    i = ids.index(sid)
    j = max(0, min(len(ids) - 1, i + delta))
    out["sections"].insert(j, out["sections"].pop(i))
    return out


def with_child(spec, sid, child, on):
    out = sanitise(spec)
    cur = [c for c in out["skip"].get(sid, []) if c != child]
    if not on:
        cur.append(str(child))
    if cur:
        out["skip"][sid] = cur
    else:
        out["skip"].pop(sid, None)
    return out


def cover_of(spec):
    """The cover choice: ``{"design", "image", "accent"}``."""
    return dict(sanitise(spec)["cover"])


def with_cover(spec, **changes):
    """``spec`` with the given cover fields changed (``design``, ``image``,
    ``accent``)."""
    out = sanitise(spec)
    out["cover"].update(changes)
    return sanitise(out)


def with_cover_of(spec, other):
    """``spec`` with the cover of ``other`` (a preset changes what goes in the
    report, not the look of its cover)."""
    return with_cover(spec, **cover_of(other))


def with_option(spec, key, value):
    out = sanitise(spec)
    out["options"][key] = value
    return sanitise(out)


def spec_from_sections(sections, kind="pdf"):
    """The spec that the old ``sections=`` argument meant: those sections on,
    in the order the reports used before (``kind``: "pdf" or "deck")."""
    table = LEGACY_DECK if kind == "deck" else LEGACY_PDF
    on = {sid for name in sections for sid in table.get(name, ())}
    spec = default_spec()
    spec["sections"] = [{"id": sid, "on": sid in on} for sid in LEGACY_ORDER]
    spec["cover"]["design"] = "none"          # the old reports had no picture
    spec["options"]["dividers"] = "none"      # ... and no divider slides
    return spec


# -- presets --------------------------------------------------------------------
def _preset(order, on):
    """A spec with ``on`` sections on, the rest off; ``order`` first."""
    rest = [i for i in SECTION_IDS if i not in order]
    spec = default_spec()
    spec["sections"] = [{"id": i, "on": i in on} for i in list(order) + rest]
    return spec


BUILTIN_PRESETS = {
    "Everything": default_spec(),
    "Customer report": _preset(
        ("cover", "contents", "summary", "figures", "images", "methods",
         "calibration"),
        {"cover", "contents", "summary", "figures", "images", "methods",
         "calibration"}),
    "Quick look": _preset(("cover", "figures"), {"cover", "figures"}),
    "Audit trail": _preset(
        ("cover", "contents", "methods", "calibration", "metadata", "files"),
        {"cover", "contents", "methods", "calibration", "metadata", "files"}),
}
MAX_PRESET_NAME = 60


def clean_presets(presets):
    """``{name: spec}`` with valid names and specs (built-in names are kept for
    the built-ins, so a saved preset cannot shadow one)."""
    out = {}
    if isinstance(presets, dict):
        for name, spec in presets.items():
            name = str(name).strip()[:MAX_PRESET_NAME]
            if name and name not in BUILTIN_PRESETS:
                out[name] = sanitise(spec)
    return out


def all_presets(user):
    """Built-in presets first, then the user's, as one ordered dict."""
    out = {k: copy_spec(v) for k, v in BUILTIN_PRESETS.items()}
    out.update(clean_presets(user))
    return out


# -- what there is to put in ---------------------------------------------------
def figure_id(fig, index):
    """A stable id for a saved figure (its workbook id, else its position)."""
    return str((fig or {}).get("id") or f"fig{index}")


def doc_key(doc):
    """A stable id for a loaded file (its workbook file id, else its name)."""
    return str(getattr(doc, "file_id", "") or
               os.path.basename((getattr(doc, "path", "") or "").rstrip("\\/")))


@dataclass
class Inventory:
    """What the loaded data can fill: which sections have content, why not if
    they do not, and the children of the sections that have them."""
    present: dict = field(default_factory=dict)       # id -> bool
    reasons: dict = field(default_factory=dict)       # id -> why it is empty
    children: dict = field(default_factory=dict)      # id -> [(child id, label)]
    counts: dict = field(default_factory=dict)        # id -> number, for display

    def present_ids(self):
        return {sid for sid, ok in self.present.items() if ok}

    def summary(self, sid):
        """'6 figures', '3 files' or the reason a section is empty."""
        if not self.present.get(sid, False):
            return self.reasons.get(sid, "nothing to show")
        n = self.counts.get(sid)
        if sid == "figures":
            return f"{n} figure{'s' if n != 1 else ''}"
        if sid == "metadata":
            return f"{n} file{'s' if n != 1 else ''}"
        if sid == "files":
            return f"{n} file{'s' if n != 1 else ''}"
        return ""


def inventory(details, methods_text, calibration, file_rows, docs, figures,
              has_images, have_mpl=True):
    """Build the ``Inventory`` from what the workspace holds. ``figures`` are
    the saved figures (or the single 'current view' the reports fall back to)."""
    inv = Inventory()

    def put(sid, ok, why="", n=None):
        inv.present[sid] = bool(ok)
        if not ok:
            inv.reasons[sid] = why
        if n is not None:
            inv.counts[sid] = n

    put("cover", True)
    put("contents", True)
    put("summary", (details.get("summary") or "").strip(),
        "no summary written (Details ▸ Summary)")
    put("methods", (methods_text or "").strip(), "no methods text")
    put("calibration", (calibration or "").strip(),
        "no energy calibration recorded")
    put("files", file_rows, "no files loaded", len(file_rows or ()))
    put("metadata", docs, "no files loaded", len(docs or ()))
    put("images", has_images, "no pictures or maps in these files")
    put("figures", figures and have_mpl,
        "matplotlib is not installed" if figures and not have_mpl
        else "no saved figures (Workbook ▸ Figures)", len(figures or ()))
    inv.children["figures"] = [
        (figure_id(f, i), f.get("name") or f"Figure {i}")
        for i, f in enumerate(figures or (), 1)]
    inv.children["metadata"] = [
        (doc_key(d), os.path.basename((d.path or "").rstrip("\\/")) or "file")
        for d in docs or ()]
    return inv


def describe(spec, inv=None):
    """'Cover, Summary, Figures (2 of 3), Data files' — for a status line."""
    spec = sanitise(spec)
    parts = []
    for sid, skip in active(spec, inv.present_ids() if inv else None):
        text = LABELS[sid]
        kids = inv.children.get(sid) if inv else None
        if kids and skip:
            text += f" ({len(kids) - len([k for k, _ in kids if k in skip])}" \
                    f" of {len(kids)})"
        parts.append(text)
    return ", ".join(parts) or "nothing selected"
