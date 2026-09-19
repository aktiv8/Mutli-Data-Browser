"""Minimal pure-Python reader for OLE2 / Compound File Binary containers
(used by Thermo Avantage ``.vgd``). Read-only, no third-party dependency.

Only what is needed to list and read streams: header, DIFAT/FAT, mini-FAT,
directory tree (flattened to slash-separated paths) and stream extraction.
"""

from __future__ import annotations

import struct

MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_FREE, _END, _FATSECT, _DIFSECT = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFC


class OleError(Exception):
    pass


def is_ole(head: bytes) -> bool:
    return head[:8] == MAGIC


class OleFile:
    def __init__(self, data: bytes):
        if data[:8] != MAGIC:
            raise OleError("not an OLE2 compound file")
        self.data = data
        (self.minor, self.major, self.byteorder, sector_shift, mini_shift) = \
            struct.unpack_from("<HHHHH", data, 24)
        self.sector = 1 << sector_shift
        self.mini_sector = 1 << mini_shift
        (n_dir_sectors, n_fat, dir_start, _tx, self.mini_cutoff, minifat_start,
         n_minifat, difat_start, n_difat) = struct.unpack_from(
            "<IIIIIIIII", data, 40)
        difat = list(struct.unpack_from("<109I", data, 76))
        s = difat_start
        for _ in range(n_difat):                       # extra DIFAT sectors
            if s >= _DIFSECT:
                break
            chunk = self._sector(s)
            ids = struct.unpack("<%dI" % (self.sector // 4), chunk)
            difat += ids[:-1]
            s = ids[-1]
        self.fat = []
        for sid in difat[:n_fat]:
            if sid >= _DIFSECT:
                continue
            self.fat += struct.unpack("<%dI" % (self.sector // 4),
                                      self._sector(sid))
        # directory
        raw = b"".join(self._sector(s) for s in self._chain(dir_start))
        self.entries = []
        for i in range(len(raw) // 128):
            e = raw[i * 128:(i + 1) * 128]
            nl = struct.unpack_from("<H", e, 64)[0]
            name = e[:max(0, nl - 2)].decode("utf-16le", "replace")
            self.entries.append({
                "name": name, "type": e[66],
                "left": struct.unpack_from("<I", e, 68)[0],
                "right": struct.unpack_from("<I", e, 72)[0],
                "child": struct.unpack_from("<I", e, 76)[0],
                "start": struct.unpack_from("<I", e, 116)[0],
                "size": struct.unpack_from("<Q", e, 120)[0]
                if self.major >= 4 else struct.unpack_from("<I", e, 120)[0],
            })
        root = self.entries[0]
        self._ministream = b"".join(
            self._sector(s) for s in self._chain(root["start"]))[:root["size"]]
        self.minifat = []
        for s in self._chain(minifat_start):
            self.minifat += struct.unpack("<%dI" % (self.sector // 4),
                                          self._sector(s))
        self.streams = {}
        self._walk(root["child"], "")

    # -- internals -------------------------------------------------------
    def _sector(self, sid):
        off = (sid + 1) * self.sector
        return self.data[off:off + self.sector]

    def _chain(self, start):
        out, seen = [], set()
        while start < _DIFSECT and start not in seen and start < len(self.fat):
            seen.add(start)
            out.append(start)
            start = self.fat[start]
        return out

    def _mini_chain(self, start):
        out, seen = [], set()
        while start < _DIFSECT and start not in seen and start < len(self.minifat):
            seen.add(start)
            out.append(start)
            start = self.minifat[start]
        return out

    def _walk(self, idx, prefix):
        """In-order traversal of the directory red-black tree."""
        stack, node = [], idx
        while stack or node != _FREE:
            while node != _FREE and node < len(self.entries):
                stack.append(node)
                node = self.entries[node]["left"]
            if not stack:
                break
            node = stack.pop()
            e = self.entries[node]
            path = f"{prefix}{e['name']}"
            if e["type"] == 2:                       # stream
                self.streams[path] = e
            elif e["type"] == 1:                     # storage
                self._walk(e["child"], path + "/")
            node = e["right"]

    # -- public ----------------------------------------------------------
    def listdir(self):
        return list(self.streams)

    def read(self, path: str) -> bytes:
        e = self.streams[path]
        size = e["size"]
        if size < self.mini_cutoff:                  # lives in the mini stream
            buf = b"".join(
                self._ministream[s * self.mini_sector:(s + 1) * self.mini_sector]
                for s in self._mini_chain(e["start"]))
        else:
            buf = b"".join(self._sector(s) for s in self._chain(e["start"]))
        return buf[:size]
