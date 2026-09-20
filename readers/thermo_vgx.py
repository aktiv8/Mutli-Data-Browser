"""Thermo Avantage experiment file (``.VGX``): what was planned and in what order.

A ``.VGX`` is an OLE2 container (see ole2.py) of MFC-serialised objects: the
root ``Contents`` stream describes the experiment and each ``Embedding N``
storage is one node of the run tree, whose own ``Contents`` stream holds a
handful of length-prefixed UTF-16 strings and binary settings. Only the
strings are read here; the settings live in the ``.VGD`` files with the data.

The tree, checked against three real experiments::

    experiment                      names + "C:\\Avantage", date, project, platter, name
      acquisition group             ("Point", "Multi Point", "SnapMap"...; last string
                                    is the source configuration, "X-Ray005 200um - FG  ON")
        sample / position           (its own strings list the steps; the name is not
                                    always the last string, so it is matched by folder)
          [sequence]                ("Depth Profile")
            step                    (last non-empty string = the ``.VGD`` name)

The node numbers (``Embedding 8``) are creation order, which is also the order
of acquisition, so they give the order of samples and scans.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field

from .base import read_bytes
from .ole2 import OleFile, is_ole


@dataclass
class VgxNode:
    number: int = 0                       # the N of "Embedding N" (0 for the root)
    strings: list = field(default_factory=list)
    children: list = field(default_factory=list)

    @property
    def name(self) -> str:
        """The last non-empty string: a scan's name, a group's configuration."""
        for s in reversed(self.strings):
            if s:
                return s
        return ""

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


@dataclass
class VgxTree:
    root: VgxNode
    experiment: str = ""
    project: str = ""
    platter: str = ""
    date_folder: str = ""
    data_root: str = ""
    setups: list = field(default_factory=list)   # source configurations at the top

    @property
    def groups(self):
        return [n for n in self.root.children if n.children]

    def group_for(self, config: str):
        """The acquisition group whose source configuration is ``config``."""
        for g in self.groups:
            if g.name == config:
                return g
        return None


def sniff(head: bytes, ext: str) -> bool:
    return ext == ".vgx" and is_ole(head)


def strings_of(b: bytes) -> list:
    """The MFC ``CString``s (``FF FE FF`` + length + UTF-16) in a stream."""
    out, pos = [], 0
    while True:
        i = b.find(b"\xff\xfe\xff", pos)
        if i < 0 or i + 4 > len(b):
            return out
        n, q = b[i + 3], i + 4
        if n == 0xFF:                              # long form: 16-bit length
            if q + 2 > len(b):
                return out
            n, q = struct.unpack_from("<H", b, q)[0], q + 2
        raw = b[q:q + 2 * n]
        if len(raw) < 2 * n:
            return out
        out.append(raw.decode("utf-16le", "replace"))
        pos = q + 2 * n


def _embedding_no(name: str) -> int:
    m = re.match(r"Embedding (\d+)$", name)
    return int(m.group(1)) if m else 0


def parse(data: bytes) -> VgxTree:
    """The run tree of a ``.VGX`` file."""
    ole = OleFile(data)
    kids = {}                                # parent path -> [child path]
    for name in ole.listdir():
        if name != "Contents" and not name.endswith("/Contents"):
            continue
        path = name[:-len("Contents")].rstrip("/")
        parent = path.rsplit("/", 1)[0] if "/" in path else ""
        if path:
            kids.setdefault(parent, []).append(path)

    def build(path):
        node = VgxNode(
            number=_embedding_no(path.rsplit("/", 1)[-1]) if path else 0,
            strings=strings_of(ole.read((path + "/" if path else "")
                                        + "Contents")))
        for c in sorted(kids.get(path, []),
                        key=lambda p: _embedding_no(p.rsplit("/", 1)[-1])):
            node.children.append(build(c))
        return node

    root = build("")
    tree = VgxTree(root)
    s = [x for x in root.strings]
    # ... setups ..., "Gun Shutdown", "C:\Avantage", date, project, platter, name, ""
    path_at = next((i for i, x in enumerate(s) if re.match(r"^[A-Za-z]:\\", x)),
                   None)
    if path_at is not None:
        tree.setups = [x for x in s[:path_at] if x and x != "Gun Shutdown"]
        tail = [x for x in s[path_at + 1:] if x != ""]
        tree.data_root = s[path_at]
        for attr, val in zip(("date_folder", "project", "platter",
                              "experiment"), tail):
            setattr(tree, attr, val)
    return tree


def load(path: str) -> VgxTree:
    """Read a ``.VGX`` from disk; raises ``OleError`` (from ole2) for anything else."""
    return parse(read_bytes(path))


def step_names(node: VgxNode) -> list:
    """The scan names below a sample, in the order they were set up."""
    return [n.name for n in node.walk() if n is not node and not n.children]


def sample_nodes(tree: VgxTree, config: str):
    """The samples / positions under one acquisition group, in run order."""
    g = tree.group_for(config)
    return list(g.children) if g else []
