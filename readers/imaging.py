"""Tiny image helpers for readers: packed-RGB pixels to a PNG, no Pillow.

Avantage stores its sample-view camera images as one float per pixel holding
``B << 16 | G << 8 | R`` (a Windows COLORREF; checked pixel for pixel against
the PNG Avantage exports); the GUI shows any image Pillow can open, so a reader
hands over a PNG.
"""

from __future__ import annotations

import struct
import zlib


def encode_png(width: int, height: int, rgb: bytes, level: int = 3) -> bytes:
    """A truecolour PNG from ``width * height * 3`` bytes of RGB."""
    if len(rgb) != width * height * 3:
        raise ValueError("pixel data does not match the image size")
    stride = width * 3
    raw = bytearray()
    for y in range(height):
        raw.append(0)                                  # filter: none
        raw += rgb[y * stride:(y + 1) * stride]

    def chunk(tag: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2,
                                         0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), level))
            + chunk(b"IEND", b""))


def unpack_rgb(values) -> bytes:
    """RGB bytes from packed pixel values (``B << 16 | G << 8 | R``, as
    floats or ints). Uses numpy when it is installed."""
    try:
        import numpy as np
    except ImportError:
        out = bytearray(3 * len(values))
        for i, v in enumerate(values):
            n = int(v)
            out[3 * i] = n & 255
            out[3 * i + 1] = (n >> 8) & 255
            out[3 * i + 2] = (n >> 16) & 255
        return bytes(out)
    a = np.asarray(values, dtype=np.float64).astype(np.uint32)
    rgb = np.empty((a.size, 3), dtype=np.uint8)
    rgb[:, 0] = a & 255
    rgb[:, 1] = (a >> 8) & 255
    rgb[:, 2] = (a >> 16) & 255
    return rgb.tobytes()
