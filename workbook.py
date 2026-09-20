"""Experiment workbooks: the ``.xpscontainer`` file.

A workbook is a ZIP archive holding the original instrument files (verbatim),
the looks the user created, free-text notes and a metadata snapshot, so an
experiment can be recalled later and reported on. Everything except the data
files is JSON: opening a workbook never executes anything from it.

::

    manifest.json   format, format_version, created / modified, files[]
    workbook.json   title, customer, reference, operator, date, summary
    state.json      the current look (view, colours, ticks, ...)
    figures.json    named looks with captions
    metadata.json   read-only snapshot of the acquisition metadata
    annotations.json  renames, notes, edited metadata, BE shifts, markers
    holder.json     holder-photo calibration (stage mm -> photo pixels)
    data/<id>/<original file name>      the instrument files, byte-for-byte
    data/<id>/<name>/<folders>/<file>   an experiment folder (a session of many
                                        files, e.g. Avantage): same, keeping the
                                        layout the reader needs
    assets/logo.<ext>                   optional letterhead image
    preview.png                         thumbnail of the plot

No Tk and no matplotlib here, so it is unit-testable on its own.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field

import appinfo

FORMAT = "xpscontainer"
FORMAT_VERSION = 2             # 2 adds sessions (a FileEntry with members); a
                               # workbook without one is still written as 1
EXT = ".xpscontainer"

DETAIL_FIELDS = ("title", "customer", "reference", "operator", "date",
                 "summary", "methods")      # methods: the user's own text, or ""
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_LOGO_EXTS = {".png", ".jpg", ".jpeg"}


class WorkbookError(Exception):
    """A workbook could not be read or written (message is user-facing)."""


@dataclass
class FileEntry:
    """One embedded instrument file."""
    id: str
    name: str                    # original file name
    path: str = ""               # local file: the source when saving, the
                                 # extracted copy after loading
    original_path: str = ""      # where it lived when it was added
    size: int = 0
    sha256: str = ""
    # a session (an experiment folder): every file in it as
    # (absolute path, path below the session folder); ``path`` is then the
    # folder the reader opens (the extracted copy after loading)
    members: list = field(default_factory=list)


@dataclass
class Workbook:
    details: dict = field(default_factory=lambda: {k: ""
                                                   for k in DETAIL_FIELDS})
    state: dict = field(default_factory=dict)
    figures: list = field(default_factory=list)     # [{id,name,caption,state}]
    files: list = field(default_factory=list)       # [FileEntry]
    logo: str = ""               # local path of the letterhead image
    metadata: dict = field(default_factory=dict)
    annotations: dict = field(default_factory=dict)  # annotations.to_json()
    holder: dict = field(default_factory=dict)      # {"calibration": {...}}
    created: str = ""
    modified: str = ""
    extra: dict = field(default_factory=dict)       # unknown manifest keys
    warnings: list = field(default_factory=list)    # problems found on load

    def title(self) -> str:
        return (self.details.get("title") or "").strip()


def _now() -> str:
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_name(name: str) -> str:
    """A file name that cannot escape its folder."""
    base = (name or "").replace("\\", "/").split("/")[-1] or "file"
    return re.sub(r"[\x00-\x1f<>:\"|?*]", "_", base).lstrip(".") or "file"


def safe_rel(rel: str) -> str:
    """A relative path (``a/b/c``) whose every part is a safe name: no ``..``,
    no drive letters, no leading slash."""
    parts = [safe_name(x) for x in (rel or "").replace("\\", "/").split("/")
             if x not in ("", ".", "..")]
    return "/".join(parts) or "file"


def sha256_members(members) -> str:
    """One hash for a session: the hashes of its files, by relative path."""
    h = hashlib.sha256()
    # the path as stored in the workbook, whichever separator it came with
    for rel, path in sorted((safe_rel(rel), path) for path, rel in members):
        h.update(f"{rel}:{sha256_file(path)}\n".encode("utf-8"))
    return h.hexdigest()


def new_id(existing, prefix) -> str:
    """'f1', 'f2', ... not already in ``existing``."""
    used = set(existing)
    n = 1
    while f"{prefix}{n}" in used:
        n += 1
    return f"{prefix}{n}"


# -- region references -------------------------------------------------------------
def region_ref(file_id, pos, region) -> dict:
    """A stable reference to a spectrum: ``id(region)`` changes every run, so
    store the file, the position in its region list and what it should be."""
    return {"file": file_id, "pos": pos, "name": region.name,
            "sample": region.sample, "etch_level": region.etch_level}


def resolve_refs(refs, regions_by_file):
    """``(regions, n_missing)`` for saved references.

    ``regions_by_file`` maps file id -> that file's region list. A reference
    is matched by position when the region there is the one expected;
    otherwise by (name, sample, etch level) among regions not yet taken, in
    case a reader's ordering changed."""
    out, used, missing = [], set(), 0
    for ref in refs:
        regs = regions_by_file.get(ref.get("file"), [])
        pos = ref.get("pos")
        want = (ref.get("name"), ref.get("sample"), ref.get("etch_level"))

        def key(r):
            return (r.name, r.sample, r.etch_level)

        hit = None
        if isinstance(pos, int) and 0 <= pos < len(regs) \
                and key(regs[pos]) == want and id(regs[pos]) not in used:
            hit = regs[pos]
        else:
            for r in regs:
                if key(r) == want and id(r) not in used:
                    hit = r
                    break
        if hit is None:
            missing += 1
        else:
            used.add(id(hit))
            out.append(hit)
    return out, missing


# -- writing -----------------------------------------------------------------------
def save(path, wb: Workbook, preview_png: bytes | None = None) -> None:
    """Write ``wb`` to ``path`` (atomically: a temp file, then a rename).

    Each ``FileEntry.path`` must exist; its size and hash are refreshed."""
    missing = []
    for f in wb.files:
        if f.members:
            missing += [f"{f.name}/{rel}" for p, rel in f.members
                        if not os.path.isfile(p)]
        elif not os.path.isfile(f.path):
            missing.append(f.name)
    if missing:
        raise WorkbookError("These data files can no longer be found:\n  "
                            + "\n  ".join(missing[:20]))
    for f in wb.files:
        if not _ID_RE.match(f.id):
            raise WorkbookError(f"Invalid file id {f.id!r}.")
        if f.members:
            f.size = sum(os.path.getsize(p) for p, _rel in f.members)
            f.sha256 = sha256_members(f.members)
        else:
            f.size = os.path.getsize(f.path)
            f.sha256 = sha256_file(f.path)
    wb.modified = _now()
    wb.created = wb.created or wb.modified

    logo_member = ""
    if wb.logo:
        ext = os.path.splitext(wb.logo)[1].lower()
        if ext not in _LOGO_EXTS or not os.path.isfile(wb.logo):
            raise WorkbookError("The logo must be an existing PNG or JPEG "
                                "image.")
        logo_member = "assets/logo" + ext

    def entry_of(f):
        if not f.members:
            return {"id": f.id, "member": f"data/{f.id}/{safe_name(f.name)}",
                    "original_name": f.name, "original_path": f.original_path,
                    "size": f.size, "sha256": f.sha256}
        base = f"data/{f.id}/{safe_name(f.name)}"
        return {"id": f.id, "session": True, "original_name": f.name,
                "original_path": f.original_path, "size": f.size,
                "sha256": f.sha256,
                "members": [{"path": safe_rel(rel),
                             "member": f"{base}/{safe_rel(rel)}"}
                            for _p, rel in f.members]}

    manifest = dict(wb.extra)
    manifest.update({
        "format": FORMAT,
        "format_version": 2 if any(f.members for f in wb.files) else 1,
        "created": wb.created, "modified": wb.modified,
        "created_with": appinfo.NAME,
        "files": [entry_of(f) for f in wb.files],
        "logo": logo_member,
    })
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".xpsc_", suffix=".tmp", dir=folder)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED,
                             compresslevel=6) as zf:
            def put_json(name, obj):
                zf.writestr(name, json.dumps(obj, indent=2,
                                             ensure_ascii=False))
            put_json("manifest.json", manifest)
            put_json("workbook.json", {k: wb.details.get(k, "")
                                       for k in DETAIL_FIELDS})
            put_json("state.json", wb.state)
            put_json("figures.json", wb.figures)
            put_json("metadata.json", wb.metadata)
            put_json("annotations.json", wb.annotations)
            put_json("holder.json", wb.holder)
            for f, entry in zip(wb.files, manifest["files"]):
                if f.members:
                    for (src, _rel), m in zip(f.members, entry["members"]):
                        zf.write(src, m["member"])
                else:
                    zf.write(f.path, entry["member"])
            if logo_member:
                zf.write(wb.logo, logo_member)
            if preview_png:
                zf.writestr("preview.png", preview_png)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


# -- reading -----------------------------------------------------------------------
def _read_json(zf, name, default):
    try:
        raw = zf.read(name)
    except KeyError:
        return default
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise WorkbookError(f"{name} in the workbook is damaged ({exc}).")


def load(path, extract_dir) -> Workbook:
    """Read a workbook, extracting its data files (and logo) into
    ``extract_dir``. Only members named in the manifest are read and their
    destination names are sanitised, so a crafted archive cannot write
    elsewhere."""
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise WorkbookError(f"{os.path.basename(path)} is not a valid "
                            f"workbook ({exc}).")
    with zf:
        names = set(zf.namelist())
        if "manifest.json" not in names:
            raise WorkbookError(f"{os.path.basename(path)} is not an "
                                f"{EXT} workbook (no manifest).")
        manifest = _read_json(zf, "manifest.json", {})
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
            raise WorkbookError(f"{os.path.basename(path)} is not an "
                                f"{EXT} workbook.")
        version = manifest.get("format_version")
        if not isinstance(version, int) or version < 1:
            raise WorkbookError("The workbook has no valid format version.")
        if version > FORMAT_VERSION:
            raise WorkbookError(
                f"This workbook was saved by a newer version of the app "
                f"(format {version}; this one reads up to {FORMAT_VERSION}). "
                f"Please update {appinfo.NAME}.")

        known = {"format", "format_version", "created", "modified",
                 "created_with", "files", "logo"}
        wb = Workbook(created=str(manifest.get("created", "")),
                      modified=str(manifest.get("modified", "")),
                      extra={k: v for k, v in manifest.items()
                             if k not in known})
        details = _read_json(zf, "workbook.json", {})
        wb.details = {k: str(details.get(k, "")) if isinstance(details, dict)
                      else "" for k in DETAIL_FIELDS}
        state = _read_json(zf, "state.json", {})
        wb.state = state if isinstance(state, dict) else {}
        figs = _read_json(zf, "figures.json", [])
        wb.figures = [f for f in figs if isinstance(f, dict)
                      and isinstance(f.get("state"), dict)] \
            if isinstance(figs, list) else []
        meta = _read_json(zf, "metadata.json", {})
        wb.metadata = meta if isinstance(meta, dict) else {}
        ann = _read_json(zf, "annotations.json", {})
        wb.annotations = ann if isinstance(ann, dict) else {}
        hold = _read_json(zf, "holder.json", {})
        wb.holder = hold if isinstance(hold, dict) else {}

        os.makedirs(extract_dir, exist_ok=True)
        for entry in manifest.get("files", []):
            fid = str(entry.get("id", ""))
            member = str(entry.get("member", ""))
            if not _ID_RE.match(fid):
                raise WorkbookError(f"Invalid file id {fid!r} in manifest.")
            if entry.get("session"):
                wb.files.append(_extract_session(zf, names, entry, fid,
                                                 extract_dir, wb))
                continue
            if member not in names:
                raise WorkbookError(
                    f"The workbook is missing the data file "
                    f"'{entry.get('original_name', member)}'.")
            name = safe_name(entry.get("original_name") or member)
            dest_dir = os.path.join(extract_dir, fid)
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, name)
            try:
                with zf.open(member) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
            except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
                raise WorkbookError(f"Could not read '{name}' from the "
                                    f"workbook ({exc}).")
            fe = FileEntry(id=fid, name=name, path=dest,
                           original_path=str(entry.get("original_path", "")),
                           size=int(entry.get("size") or 0),
                           sha256=str(entry.get("sha256", "")))
            if fe.sha256 and sha256_file(dest) != fe.sha256:
                wb.warnings.append(f"{name}: contents do not match the "
                                   f"hash recorded when it was saved.")
            wb.files.append(fe)

        logo = str(manifest.get("logo", ""))
        if (logo and logo in names
                and os.path.splitext(logo)[1].lower() in _LOGO_EXTS):
            dest = os.path.join(extract_dir, "assets",
                                "logo" + os.path.splitext(logo)[1].lower())
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with zf.open(logo) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            wb.logo = dest
    return wb


def _extract_session(zf, names, entry, fid, extract_dir, wb) -> FileEntry:
    """Unpack an experiment folder into ``<extract_dir>/<id>/<name>/`` keeping
    its layout. Every destination is checked to stay inside that folder."""
    name = safe_name(entry.get("original_name") or "experiment")
    root = os.path.realpath(os.path.join(extract_dir, fid, name))
    os.makedirs(root, exist_ok=True)
    members = []
    for m in entry.get("members", []):
        if not isinstance(m, dict):
            continue
        member, rel = str(m.get("member", "")), safe_rel(str(m.get("path", "")))
        if member not in names:
            raise WorkbookError(f"The workbook is missing '{rel}' of "
                                f"'{entry.get('original_name', name)}'.")
        dest = os.path.realpath(os.path.join(root, *rel.split("/")))
        if os.path.commonpath([root, dest]) != root:
            raise WorkbookError(f"Unsafe file name in the workbook: {rel}")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        try:
            with zf.open(member) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
        except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
            raise WorkbookError(f"Could not read '{rel}' from the workbook "
                                f"({exc}).")
        members.append((dest, rel))
    fe = FileEntry(id=fid, name=name, path=root,
                   original_path=str(entry.get("original_path", "")),
                   size=int(entry.get("size") or 0),
                   sha256=str(entry.get("sha256", "")), members=members)
    if fe.sha256 and sha256_members(members) != fe.sha256:
        wb.warnings.append(f"{name}: contents do not match the hash recorded "
                           f"when it was saved.")
    return fe


def read_preview(path):
    """The preview PNG bytes of a workbook, or None."""
    try:
        with zipfile.ZipFile(path) as zf:
            return zf.read("preview.png")
    except (KeyError, zipfile.BadZipFile, OSError):
        return None
