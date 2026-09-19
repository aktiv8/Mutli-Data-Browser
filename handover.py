"""The hand-over package: everything a customer or collaborator needs from an
experiment in one ZIP.

::

    <name>/README.txt          what is in the package, and the experiment details
    <name>/report.pdf          the experiment report
    <name>/methods.txt         the methods text
    <name>/metadata/<file>.csv acquisition metadata, one row per spectrum
    <name>/spectra/vamas/<sample>.vms   one VAMAS file per sample
    <name>/spectra/csv/<sample>.csv     the same spectra as CSV
    <name>/figures/figure_01_<name>.png the saved figures
    <name>/workbook/<name>.xpscontainer the workbook (optional)
    <name>/SHA256SUMS.txt      checksum of every file above

Spectra are exported the way the app exports them (display names and binding
energy shifts applied, when the caller passes ``display``). The report, the
figure pictures and the workbook need the GUI's renderers, so the caller
hands those in as ready-made ``Part``s. No Tk and no matplotlib here.
"""

from __future__ import annotations

import datetime
import hashlib
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass

import appinfo
import exporters

TOOL = appinfo.NAME


class HandoverError(Exception):
    """The package could not be built (message is user-facing)."""


@dataclass
class Part:
    """One file of the package: ``arc`` is its path inside the folder,
    ``desc`` a short description for the README. The content is ``data``
    (bytes) or the file at ``path``."""
    arc: str
    desc: str = ""
    path: str = ""
    data: bytes | None = None

    def read(self) -> bytes:
        if self.data is not None:
            return self.data
        with open(self.path, "rb") as fh:
            return fh.read()


# -- names ---------------------------------------------------------------------
def safe_stem(text, default="item", limit=60) -> str:
    """A file-name-safe version of ``text`` (letters, digits, ``._- ``)."""
    s = re.sub(r"[^\w.\- ]+", "_", (text or "").strip(), flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip(" ._")
    return s[:limit].strip(" ._") or default


def unique_name(name, used) -> str:
    """``name``, or ``name_2``, ``name_3`` ... not in ``used`` (which is
    updated). Comparison ignores case, as Windows does."""
    key = name.lower()
    if key not in used:
        used.add(key)
        return name
    n = 2
    while f"{name}_{n}".lower() in used:
        n += 1
    used.add(f"{name}_{n}".lower())
    return f"{name}_{n}"


# -- spectra ---------------------------------------------------------------------
def sample_groups(docs, display=None):
    """``[(file_parser, sample_label, [regions], [metadata])]`` in file order,
    holding only spectra with data. ``display(region)`` returns the region as
    it should be exported (names, BE shift); the sample label is taken from
    it. ``metadata`` are the file's own ``region_metadata`` of each."""
    out = []
    for p in docs:
        order, groups, metas = [], {}, {}
        for r in p.regions:
            if not (r.decodable and r.counts):
                continue
            d = display(r) if display else r
            key = d.sample
            if key not in groups:
                groups[key], metas[key] = [], []
                order.append(key)
            groups[key].append(d)
            metas[key].append(p.region_metadata(r))
        out += [(p, k, groups[k], metas[k]) for k in order]
    return out


def spectra_parts(docs, display=None):
    """VAMAS and CSV parts, one pair per sample. Returns ``(parts, notes)``;
    ``notes`` lists samples that could not be written."""
    parts, notes = [], []
    used_v, used_c = set(), set()
    multi = len(docs) > 1
    for p, sample, regions, metas in sample_groups(docs, display):
        base = safe_stem(sample, "unnamed sample")
        if multi:
            base = safe_stem(os.path.splitext(os.path.basename(p.path or ""))[0],
                             "file") + " - " + base
        inst = getattr(p, "instrument", {}) or {}
        try:
            with tempfile.TemporaryDirectory(prefix="xpsc_ho_") as tmp:
                v = os.path.join(tmp, "a.vms")
                c = os.path.join(tmp, "a.csv")
                exporters.export_vamas(
                    regions, v, instrument=inst.get("Instrument", ""),
                    operator=inst.get("Acquisition computer", ""),
                    experiment_id=os.path.basename(p.path or ""),
                    sample_id=sample or "Sample", metadata=metas)
                exporters.export_csv(regions, c)
                with open(v, "rb") as fh:
                    vdata = fh.read()
                with open(c, "rb") as fh:
                    cdata = fh.read()
        except (ValueError, OSError) as exc:
            notes.append(f"{sample or 'unnamed sample'}: {exc}")
            continue
        n = len(regions)
        what = f"{n} spectrum" if n == 1 else f"{n} spectra"
        parts.append(Part(
            f"spectra/vamas/{unique_name(base, used_v)}.vms",
            f"VAMAS (ISO 14976), {what}", data=vdata))
        parts.append(Part(
            f"spectra/csv/{unique_name(base, used_c)}.csv",
            f"CSV, {what} (energy and intensity columns)", data=cdata))
    return parts, notes


def metadata_parts(docs):
    """One metadata CSV per loaded file."""
    parts, used = [], set()
    for p in docs:
        base = safe_stem(os.path.splitext(os.path.basename(p.path or ""))[0],
                         "experiment")
        with tempfile.TemporaryDirectory(prefix="xpsc_ho_") as tmp:
            path = os.path.join(tmp, "m.csv")
            try:
                exporters.export_metadata_csv(p, path)
            except (ValueError, OSError):
                continue
            with open(path, "rb") as fh:
                data = fh.read()
        parts.append(Part(f"metadata/{unique_name(base, used)}.csv",
                          f"acquisition metadata of {os.path.basename(p.path or base)}",
                          data=data))
    return parts


def figure_parts(figures, pages):
    """PNG parts for saved figures. ``pages[i]`` is the list of PNG bytes for
    ``figures[i]`` (one per page)."""
    parts, used = [], set()
    for number, (fig, pngs) in enumerate(zip(figures, pages), 1):
        base = f"figure_{number:02d}_" + safe_stem(fig.get("name", ""),
                                                   "figure", 40)
        for i, png in enumerate(pngs, 1):
            name = base + (f"_p{i}" if len(pngs) > 1 else "")
            parts.append(Part(
                f"figures/{unique_name(name, used)}.png",
                f"Figure {number}: {fig.get('name', '')}"
                + (f" (page {i} of {len(pngs)})" if len(pngs) > 1 else ""),
                data=png))
    return parts


# -- README and checksums ---------------------------------------------------------
def _human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0


def readme_text(details, parts, file_rows=(), calibration="", when=None):
    """The README of the package. ``parts`` are the files it lists."""
    when = when or datetime.datetime.now()
    d = details or {}
    title = (d.get("title") or "").strip() or "Experiment hand-over"
    lines = [title, "=" * len(title), ""]
    for label, key in (("Customer", "customer"), ("Reference", "reference"),
                       ("Operator", "operator"), ("Date", "date")):
        if (d.get(key) or "").strip():
            lines.append(f"{label + ':':<11}{d[key].strip()}")
    lines.append(f"{'Packaged:':<11}{when:%Y-%m-%d %H:%M} with {TOOL}")
    if (d.get("summary") or "").strip():
        lines += ["", "Summary", "-------", d["summary"].strip()]
    if calibration and calibration.strip():
        lines += ["", "Energy calibration", "------------------",
                  calibration.strip()]
    lines += ["", "Contents", "--------"]
    width = max([len(p.arc) for p in parts] + [12])
    for p in sorted(parts, key=lambda p: p.arc):
        size = len(p.data) if p.data is not None else (
            os.path.getsize(p.path) if p.path and os.path.isfile(p.path)
            else 0)
        lines.append(f"  {p.arc:<{width}}  {_human(size):>9}  {p.desc}")
    lines.append(f"  {'SHA256SUMS.txt':<{width}}  {'':>9}  checksum of every "
                 f"file above (sha256sum -c SHA256SUMS.txt)")
    if file_rows:
        lines += ["", "Original data files", "-------------------"]
        for r in file_rows:
            lines.append(f"  {r.get('name', '')}  ({r.get('format', '')}, "
                         f"{r.get('regions', '')} regions, "
                         f"{_human(r.get('size', 0))})")
            if r.get("sha256"):
                lines.append(f"      sha256 {r['sha256']}")
    lines += ["", "About the spectra", "-----------------",
              "Binding energy is photon energy minus kinetic energy and, "
              "unless the",
              "report states a calibration, is not charge-corrected. The VAMAS",
              "files use a kinetic-energy axis with the transmission function "
              "where the",
              "instrument recorded one (as CasaXPS writes it); the CSV files "
              "hold binding",
              "energy and intensity in two columns per spectrum.", ""]
    return "\n".join(lines)


def checksum_text(parts_with_data) -> str:
    """``sha256sum``-style lines for ``[(arc, bytes)]``."""
    return "".join(f"{hashlib.sha256(data).hexdigest()}  {arc}\n"
                   for arc, data in parts_with_data)


# -- writing ------------------------------------------------------------------------------
def write_zip(path, root, parts, details=None, file_rows=(), calibration="",
              when=None):
    """Write the package to ``path`` (atomically). Every part goes under
    ``root/``, plus ``README.txt`` and ``SHA256SUMS.txt``. Returns the list of
    archive member names."""
    if not parts:
        raise HandoverError("Nothing to put in the package: choose at least "
                            "one item that has content.")
    arcs = [p.arc for p in parts]
    if len(set(a.lower() for a in arcs)) != len(arcs):
        raise HandoverError("Two files in the package have the same name.")
    root = safe_stem(root, "handover")
    contents = [(p.arc, p.read()) for p in parts]
    readme = readme_text(details, parts, file_rows, calibration, when).encode(
        "utf-8")
    contents.insert(0, ("README.txt", readme))
    sums = checksum_text(contents).encode("utf-8")
    contents.append(("SHA256SUMS.txt", sums))
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".handover_", suffix=".tmp", dir=folder)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED,
                             compresslevel=6) as zf:
            for arc, data in contents:
                zf.writestr(f"{root}/{arc}", data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return [f"{root}/{arc}" for arc, _d in contents]
