"""File-format readers and the registry that picks one for a given file."""

from __future__ import annotations

import os

from .base import Region, ImageBlob, TreeNode, SpectrumFile
from .kratos_experiment import EscapeParser
from . import (vamas, thermo_avg, thermo_vgd, phi_spe, scienta_txt,
               kratos_kal)


class UnsupportedFormat(Exception):
    """Raised when no reader recognises a file."""


def _sniff_experiment(head: bytes, ext: str) -> bool:
    return ext == ".experiment"


# (name, sniff(head, ext) -> bool, reader class, file-dialog patterns)
# Content sniffing first, so renamed or unusual extensions still load.
READERS = [
    ("VAMAS (ISO 14976)", vamas.sniff, vamas.VamasFile,
     ("*.vms", "*.vamas", "*.vam")),
    ("Thermo Avantage (.avg)", thermo_avg.sniff, thermo_avg.ThermoAvgFile,
     ("*.avg", "*.avx")),
    ("Thermo Avantage (.vgd)", thermo_vgd.sniff, thermo_vgd.ThermoVgdFile,
     ("*.vgd", "*.avx")),
    ("PHI MultiPak (.spe)", phi_spe.sniff, phi_spe.PhiSpeFile, ("*.spe",)),
    ("Scienta SES (.txt)", scienta_txt.sniff, scienta_txt.ScientaTxtFile,
     ("*.txt",)),
    ("Kratos Vision (.kal)", kratos_kal.sniff, kratos_kal.KratosKalFile,
     ("*.kal",)),
    ("Kratos ESCApe (.experiment)", _sniff_experiment, EscapeParser,
     ("*.experiment",)),
]


def supported_patterns():
    """[(label, [patterns])] for the Open dialog."""
    return [(name, list(pats)) for name, _s, _c, pats in READERS]


def reader_for(path: str):
    ext = os.path.splitext(path)[1].lower()
    try:
        with open(path, "rb") as fh:
            head = fh.read(4096)
    except OSError:
        head = b""              # let the chosen reader raise the real error
    for _name, sniff, cls, _pats in READERS:
        if sniff(head, ext):
            return cls
    raise UnsupportedFormat(
        f"Unrecognised file format: {os.path.basename(path)}")


def load_file(path: str) -> SpectrumFile:
    """Load ``path`` with whichever reader recognises it."""
    return reader_for(path)().load(path)
