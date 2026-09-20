"""A Thermo Avantage experiment folder opened as one session.

Avantage writes one ``.VGD`` per scan (and a ``.avg`` text copy on request) into
``<experiment>/<source configuration>/<sample>/[<sequence>/]<scan>.VGD`` next to
``<experiment>.VGX``. Opening the folder (or the ``.VGX``) loads everything as one
experiment: the samples and analysis points become tree nodes, scans of the same
core level line up across points, the sample-view camera images (one per point and
pass) are attached to their points, and each SnapMap is one region whose pixels the
map viewer can open.

The ``.VGX`` supplies the experiment identity and the order things were run in;
which folder is which sample comes from the folder names (a VGX sample node lists
its scans in a layout that changes with the scan type, so its strings are only
matched against folder names, never interpreted).

Anything that cannot be read is collected in ``self.errors`` and the rest still
loads; an aborted acquisition (an empty DataSpace) or an auto-height table is
listed in ``self.skipped`` instead.
"""

from __future__ import annotations

import os
import re

from .base import ImageBlob, SpectrumFile, TreeNode
from . import thermo_vgx
from .thermo_avg import ThermoAvgFile
from .thermo_vgd import ThermoVgdFile

DATA_EXTS = (".vgd", ".avg")
_POINT_RE = re.compile(r"(Pt\s*#\s*\w+)", re.I)
SEARCH_UP = 4                       # how far above a folder to look for its .VGX


class LoadCancelled(Exception):
    """The user cancelled while an experiment was loading."""


def _natural(s):
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", s or "")]


def find_vgx(folder: str):
    """The ``.VGX`` that describes ``folder``: one inside it, or in the nearest
    parent within ``SEARCH_UP`` levels (so a single sample folder still gets its
    experiment's name). None when there is none, or several are equally near."""
    here = os.path.abspath(folder)
    for _ in range(SEARCH_UP + 1):
        try:
            hits = [n for n in os.listdir(here) if n.lower().endswith(".vgx")]
        except OSError:
            return None
        if len(hits) == 1:
            return os.path.join(here, hits[0])
        if hits:
            return None
        up = os.path.dirname(here)
        if up == here:
            return None
        here = up
    return None


def data_files(scope: str):
    """Every ``.vgd`` / ``.avg`` under ``scope``, the binary copy winning when a
    scan is present as both; sorted for a stable order."""
    found = {}
    for dp, dirs, files in os.walk(scope):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            stem, ext = os.path.splitext(f)
            if ext.lower() in DATA_EXTS and not f.startswith("."):
                key = (os.path.normcase(dp), stem.lower())
                prev = found.get(key)
                if prev is None or ext.lower() == ".vgd":
                    found[key] = os.path.join(dp, f)
    return sorted(found.values(), key=lambda p: _natural(p))


def looks_like_experiment(folder: str) -> bool:
    """True when opening ``folder`` should give one session: a ``.VGX`` in or
    above it, or Avantage data only in sub-folders (the per-file open would find
    nothing at the top)."""
    if find_vgx(folder):
        return True
    try:
        names = os.listdir(folder)
    except OSError:
        return False
    if any(n.lower().endswith(DATA_EXTS) for n in names):
        return False
    return any(True for _ in data_files(folder))


_STAMP_RE = re.compile(r"\((\d\d)-(\d\d)-\d\d \d\d-\d\d-\d{4}\)")


def _time_of(blob, scan=""):
    """HH:MM for a camera image's label: the local time Avantage puts in the
    file name, else the (UTC) time stored in the file."""
    m = _STAMP_RE.search(scan)
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    m = re.search(r"(\d\d:\d\d)", blob.taken or "")
    return m.group(1) if m else ""


class ThermoExperiment(SpectrumFile):
    format_name = "Thermo Avantage experiment"

    def __init__(self):
        super().__init__()
        self.root_dir = ""              # the folder the relative paths hang off
        self.vgx_path = ""
        self.vgx = None                 # thermo_vgx.VgxTree, or None
        self.members = []               # [(absolute path, path below root_dir)]
        self.files = []                 # what was loaded: dicts for the file table
        self.errors = []                # [(path, message)]
        self.skipped = []               # [(path, reason)]
        self.tables = []                # (sample, value_table) e.g. auto-height Z
        self.groups = []                # [(label, [sample])] in tree order
        self.experiment = {}

    # -- loading ---------------------------------------------------------------
    def load(self, path: str, progress=None):
        """Load a folder or a ``.VGX``. ``progress(i, n, name)`` is called
        before each file; return True from it to cancel."""
        path = os.path.abspath(path)
        if os.path.isdir(path):
            scope = path
            vgx = find_vgx(path)
        else:
            scope = os.path.dirname(path)
            vgx = path
        self.path = path
        self.vgx_path = vgx or ""
        self.root_dir = os.path.dirname(vgx) if vgx else scope
        if vgx:
            try:
                self.vgx = thermo_vgx.load(vgx)
            except Exception as exc:                # noqa: BLE001
                self.warnings.append(
                    f"{os.path.basename(vgx)} could not be read ({exc}); the "
                    "folder layout is used instead.")
        files = data_files(scope)
        if not files:
            raise ValueError("no Avantage data files (.vgd / .avg) found here")

        loaded = []                     # (path, sub, sample, config, rank)
        for i, f in enumerate(files):
            if progress and progress(i, len(files), os.path.basename(f)):
                raise LoadCancelled()
            rel = os.path.relpath(f, self.root_dir)
            parts = rel.split(os.sep)
            try:
                sub = (ThermoVgdFile() if f.lower().endswith(".vgd")
                       else ThermoAvgFile()).load(f)
            except ValueError as exc:
                if "is empty" in str(exc):
                    self.skipped.append((rel, "aborted acquisition: no data"))
                else:
                    self.errors.append((rel, str(exc)))
                continue
            except Exception as exc:                # noqa: BLE001
                self.errors.append((rel, str(exc) or type(exc).__name__))
                continue
            if sub.kind == "table":
                self.skipped.append((rel, f"{sub.value_table['label']} table "
                                          "(auto-height), not a spectrum"))
                sample = self._sample_of(parts)[0]
                self.tables.append((sample, sub.value_table))
                continue
            sample, config = self._sample_of(parts)
            loaded.append((f, rel, sub, sample, config))
            self.members.append((f, rel))

        if self.vgx_path:
            self.members.insert(0, (self.vgx_path, os.path.relpath(
                self.vgx_path, self.root_dir)))
        self._merge(loaded)
        return self._finish()

    def _sample_of(self, parts):
        """``(sample, configuration)`` from a path below the root."""
        if len(parts) >= 3:
            return parts[1], parts[0]
        if len(parts) == 2:
            return parts[0], ""
        return os.path.basename(self.root_dir) or "Experiment", ""

    # -- merging the files into one experiment ----------------------------------
    def _rank_of(self):
        """A sort key for (configuration, sample, scan) from the run order in
        the ``.VGX``; anything unknown sorts after, by name."""
        gi, si, steps = {}, {}, {}
        if self.vgx is not None:
            for g_no, g in enumerate(self.vgx.groups):
                gi[g.name] = g_no
                for s_no, node in enumerate(g.children):
                    names = thermo_vgx.step_names(node)
                    for cand in {x for x in node.strings if x}:
                        si.setdefault((g.name, cand), s_no)
                        steps.setdefault((g.name, cand), names)

        def key(config, sample, scan):
            g = gi.get(config, len(gi))
            s = si.get((config, sample), 10 ** 6)
            order = steps.get((config, sample), [])
            k = order.index(scan) if scan in order else 10 ** 6
            return (g, s, _natural(sample), k, _natural(scan))
        return key

    def _merge(self, loaded):
        rank = self._rank_of()
        regions, images = [], []
        first = None
        for f, rel, sub, sample, config in loaded:
            scan = os.path.splitext(os.path.basename(f))[0]
            first = first or sub
            self.files.append({"path": f, "rel": rel, "kind": sub.kind,
                               "sample": sample, "config": config,
                               "regions": len(sub.regions),
                               "images": len(sub.images)})
            for blob in sub.images:
                pt = _POINT_RE.search(scan)
                point = re.sub(r"\s+", " ", pt.group(1)) if pt else scan
                blob.sample = f"{sample} {point}"
                t = _time_of(blob, scan)
                blob.name = f"{blob.sample}  {t}".strip()
                images.append(blob)
            for r in sub.regions:
                point = r.sample                       # "Pt #001a", or ""
                r.sample = f"{sample} {point}" if point else sample
                r.extra["group"] = sample
                r.extra["config"] = config
                r.extra["scan"] = scan
                r.extra["sort"] = rank(config, sample, scan)
                r.source = os.path.basename(f)
                regions.append(r)
                if sub.kind in ("spectrum", "map", "levels") and r.pos_x is not None \
                        and r.sample not in self._sample_pos:
                    self._sample_pos[r.sample] = (r.pos_x, r.pos_y)
            for s, xy in sub._sample_pos.items():
                self._sample_pos[f"{sample} {s}"] = xy
            if sub.depth_profile.get("is_profile"):
                self.depth_profile = dict(sub.depth_profile)
            if not self.sputter_hint and sub.sputter_hint:
                self.sputter_hint = sub.sputter_hint
            self.warnings += [f"{scan}: {w}" for w in sub.warnings]

        regions.sort(key=lambda r: (r.extra["sort"], r.date, r.index))
        images.sort(key=lambda b: (_natural(b.sample), b.taken))
        for k, r in enumerate(regions):
            r.index = r.offset = k
        self.regions, self.images = regions, images
        for k, b in enumerate(images):
            b.offset = k
        if self.depth_profile.get("is_profile"):
            levels = [r for r in regions if r.etch_level is not None]
            times = sorted({r.etch_time for r in levels
                            if r.etch_time is not None})
            self.depth_profile.update(
                n_levels=len(levels), cumulative=times,
                total_etch_time=times[-1] if times else 0.0)
        if first is not None:
            self.instrument = dict(first.instrument)
        v = self.vgx
        name = (v.experiment if v and v.experiment
                else os.path.basename(self.root_dir.rstrip("\\/")))
        self.experiment = {"name": name,
                           "project": v.project if v else "",
                           "platter": v.platter if v else "",
                           "date": v.date_folder if v else ""}
        if v:
            for k, val in (("Experiment", v.experiment),
                           ("Project", v.project), ("Platter", v.platter)):
                if val:
                    self.instrument[k] = val
        # the order samples appear in, grouped by the folder they came from
        order, seen = [], {}
        for r in regions:
            if r.sample not in seen:
                seen[r.sample] = r.extra["group"]
                order.append(r.sample)
        groups = {}
        for s in order:
            groups.setdefault(seen[s], []).append(s)
        self.groups = list(groups.items())
        if self.errors:
            n = len(self.errors)
            shown = "; ".join(f"{p}: {m}" for p, m in self.errors[:5])
            self.warnings.insert(0, f"{n} file{'s' if n != 1 else ''} could "
                                    f"not be read ({shown}"
                                    f"{'; …' if n > 5 else ''}).")

    # -- session bookkeeping ------------------------------------------------------
    def _file_size(self):
        total = 0
        for p, _rel in self.members:
            try:
                total += os.path.getsize(p)
            except OSError:
                pass
        return total

    # -- tree -------------------------------------------------------------------
    def _build_tree(self):
        name = (self.experiment.get("name")
                or os.path.basename(self.root_dir.rstrip("\\/")) or "Experiment")
        root = TreeNode(name, "experiment")
        by_sample = {}
        for r in self.regions:
            by_sample.setdefault(r.sample, []).append(r)
        pos = self.sample_positions()

        def leaf(r, dup):
            tag = "" if r.decodable else "  [no data]"
            label = r.name
            if dup:
                label += f"  ·  {r.extra.get('scan', '')}"
            elif r.extra.get("cube") is not None:
                label += "  (SnapMap)"
            return TreeNode(
                label + tag, "EscaSpectrum", r.offset, region=r,
                cols=(self._be_str(r), str(r.n_points), self._pe_str(r), ""))

        def sample_node(sample):
            rs = by_sample[sample]
            pstr = ""
            if sample in pos:
                pstr = f"({pos[sample][0]:.1f}, {pos[sample][1]:.1f} mm)"
            node = TreeNode(sample, "sample", cols=(pstr, "", "", ""))
            if any(r.etch_level is not None for r in rs):
                byname, order = {}, []
                for r in rs:
                    if r.name not in byname:
                        byname[r.name] = []
                        order.append(r.name)
                    byname[r.name].append(r)
                for rname in order:
                    rl = byname[rname]
                    folder = TreeNode(rname, "regionfolder",
                                      cols=(f"{len(rl)} levels", "",
                                            self._pe_str(rl[0]), ""))
                    for r in rl:
                        et = (f"{r.etch_time:g} s" if r.etch_time is not None
                              else "")
                        folder.children.append(TreeNode(
                            f"Level {r.etch_level}", "EscaSpectrum", r.offset,
                            region=r, cols=(self._be_str(r), str(r.n_points),
                                            self._pe_str(r), et)))
                    node.children.append(folder)
                return node
            counts = {}
            for r in rs:
                counts[r.name] = counts.get(r.name, 0) + 1
            for r in rs:
                node.children.append(leaf(r, counts[r.name] > 1))
            return node

        for label, samples in self.groups:
            if len(samples) == 1:
                root.children.append(sample_node(samples[0]))
                continue
            folder = TreeNode(label, "samplegroup",
                              cols=(f"{len(samples)} points", "", "", ""))
            for s in samples:
                folder.children.append(sample_node(s))
            root.children.append(folder)

        if self.images:
            imgs = TreeNode(f"Camera images ({len(self.images)})",
                            "HolderSnapshotFolder")
            for b in self.images:
                imgs.children.append(
                    TreeNode(b.name, "HolderContentSnapshot", b.offset,
                             image=b))
            root.children.append(imgs)
        self.tree = root
