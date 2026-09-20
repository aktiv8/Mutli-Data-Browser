"""A minimal OLE2 (compound file) writer for building test fixtures.

Just enough for ``readers.ole2.OleFile`` to read back: version-3 header,
512-byte sectors, one FAT, a flat-ish directory, and every stream padded to
4096 bytes so none needs the mini-stream. Not for real use.
"""

import struct

FREE, END, FATSECT = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD
SECTOR = 512
MIN_STREAM = 4096


def build(tree) -> bytes:
    """``tree`` is a dict: ``name -> bytes`` (a stream) or ``name -> dict``
    (a storage holding more of the same)."""
    entries = [{"name": "Root Entry", "type": 5, "child": FREE, "data": b""}]

    def add(children, parent):
        ids = []
        for name, val in children.items():
            e = {"name": name, "child": FREE, "left": FREE, "right": FREE}
            entries.append(e)
            ids.append(len(entries) - 1)
            if isinstance(val, dict):
                e["type"], e["data"] = 1, b""
                add(val, e)
            else:
                e["type"] = 2
                e["data"] = val.ljust(max(MIN_STREAM, len(val)), b"\0")
        for a, b in zip(ids, ids[1:]):                 # a right-leaning chain
            entries[a]["right"] = b
        parent["child"] = ids[0] if ids else FREE

    add(tree, entries[0])
    entries[0].update(left=FREE, right=FREE)

    n_dir = (len(entries) + 3) // 4
    sizes = [(len(e["data"]) + SECTOR - 1) // SECTOR for e in entries]
    data_sectors = sum(sizes)
    n_fat = 1
    while n_fat * 128 < n_fat + n_dir + data_sectors:
        n_fat += 1
    total = n_fat + n_dir + data_sectors

    fat = [FREE] * (n_fat * 128)
    for i in range(n_fat):
        fat[i] = FATSECT
    nxt = n_fat
    dir_start = nxt
    for i in range(n_dir):
        fat[nxt + i] = nxt + i + 1 if i < n_dir - 1 else END
    nxt += n_dir
    for e, n in zip(entries, sizes):
        e["start"] = END
        if n:
            e["start"] = nxt
            for i in range(n):
                fat[nxt + i] = nxt + i + 1 if i < n - 1 else END
            nxt += n
    assert nxt == total

    header = bytearray(SECTOR)
    header[:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<HHHHH", header, 24, 0x3E, 3, 0xFFFE, 9, 6)
    struct.pack_into("<IIIIIIIII", header, 40, 0, n_fat, dir_start, 0,
                     MIN_STREAM, END, 0, END, 0)
    difat = [FREE] * 109
    for i in range(n_fat):
        difat[i] = i
    struct.pack_into("<109I", header, 76, *difat)

    out = bytearray(header)
    for i in range(n_fat):
        out += struct.pack("<128I", *fat[i * 128:(i + 1) * 128])
    raw = bytearray()
    for e in entries:
        name = e["name"].encode("utf-16le")
        rec = bytearray(128)
        rec[:len(name)] = name
        struct.pack_into("<H", rec, 64, len(name) + 2)
        rec[66], rec[67] = e["type"], 1
        struct.pack_into("<III", rec, 68, e.get("left", FREE),
                         e.get("right", FREE), e["child"])
        struct.pack_into("<I", rec, 116, e["start"])
        struct.pack_into("<I", rec, 120, len(e["data"]) if e["type"] == 2 else 0)
        raw += rec
    raw = raw.ljust(n_dir * SECTOR, b"\0")
    out += raw
    for e in entries:
        out += e["data"].ljust((len(e["data"]) + SECTOR - 1) // SECTOR * SECTOR,
                               b"\0")
    return bytes(out)


def cstring(s: str) -> bytes:
    """An MFC CString as it appears in an Avantage ``.VGX`` stream."""
    n = len(s)
    body = b"\xff\xfe\xff" + (bytes([n]) if n < 255 else b"\xff" +
                              struct.pack("<H", n))
    return body + s.encode("utf-16le")


def contents(*strings, filler=b"\x01\x00\x00\x00") -> bytes:
    """A node ``Contents`` stream: binary filler between the strings."""
    return filler + filler.join(cstring(s) for s in strings) + filler
