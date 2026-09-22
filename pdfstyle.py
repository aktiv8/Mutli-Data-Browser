"""Type and colour of the PDF report (Tk-free; reportlab only inside functions).

One ``Look`` says which fonts and which accent colour the report is set in.
The typeface is the bundled IBM Plex Sans (registered with reportlab on first
use; it has the "α" of "Al Kα" and the "µ" / "°" that the built-in Helvetica
lacks) and the accent is the one chosen for the cover (``reportspec``). Without
the font files everything falls back to Helvetica. The text and the fill of a
table header use ``ink`` (the accent darkened), so a pale accent such as amber
still reads on white; ``accent`` itself is for rules and bars.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import covers
import fonts

REGULAR, BOLD = "IBMPlexSans", "IBMPlexSans-Bold"
FALLBACK = ("Helvetica", "Helvetica-Bold")
TEXT = "#222222"
MUTED = "#6B7785"
RULE = "#C8D0D8"

_registered: tuple | None = None


def _font_file(name):
    path = os.path.join(fonts.FONT_DIR, name)
    return path if os.path.isfile(path) else ""


def register_fonts():
    """``(regular, bold)`` reportlab font names: IBM Plex Sans when its files
    are there and load, else Helvetica. Registered once per process."""
    global _registered
    if _registered is not None:
        return _registered
    _registered = FALLBACK
    reg, bold = (_font_file(f) for f in fonts.FILES)
    if reg and bold:
        try:
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            pdfmetrics.registerFont(TTFont(REGULAR, reg))
            pdfmetrics.registerFont(TTFont(BOLD, bold))
            # no italic files: <i> keeps the upright face rather than failing
            pdfmetrics.registerFontFamily(REGULAR, normal=REGULAR, bold=BOLD,
                                          italic=REGULAR, boldItalic=BOLD)
            _registered = (REGULAR, BOLD)
        except Exception:                    # noqa: BLE001 - never stop a report
            _registered = FALLBACK
    return _registered


def font_file():
    """The regular typeface's file, for PyMuPDF (page footers); '' = none."""
    return _font_file(fonts.FILES[0]) if register_fonts()[0] == REGULAR else ""


def page_size(option="a4"):
    """``(portrait, figure_landscape_in)`` for the PDF's ``page`` option
    ("a4" or "letter", see ``reportspec.OPTIONS``; anything else is "a4"):
    the reportlab page size (points, portrait) for the text-flow document,
    and the matching landscape size in inches a figure or camera/SnapMap
    page should use so every page in the report is the same size."""
    from reportlab.lib.pagesizes import A4, LETTER
    from reportlab.lib.units import inch
    portrait = LETTER if option == "letter" else A4
    return portrait, (portrait[1] / inch, portrait[0] / inch)


@dataclass(frozen=True)
class Look:
    accent: str = covers.DEFAULT_ACCENT
    font: str = FALLBACK[0]
    bold: str = FALLBACK[1]

    @property
    def ink(self):
        """The accent darkened: text and table headers."""
        return covers.mix(self.accent, "#000000", 0.2)

    def tint(self, t):
        """The accent faded towards white (0 = the accent, 1 = white)."""
        return covers.tint(self.accent, t)


def look(accent=""):
    """The ``Look`` for an accent colour ('' = the default one)."""
    font, bold = register_fonts()
    return Look(covers.valid_accent(accent) or covers.DEFAULT_ACCENT, font, bold)


def rgb(hex_colour):
    """A '#RRGGBB' colour as the 0-1 tuple PyMuPDF takes."""
    h = hex_colour.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def styles(lk):
    """The paragraph styles of the report, as a dict of reportlab styles."""
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT

    text = colors.HexColor(TEXT)
    ink = colors.HexColor(lk.ink)
    base = ParagraphStyle("base", fontName=lk.font, fontSize=10, leading=14.5,
                          textColor=text, alignment=TA_LEFT)

    def make(name, **kw):
        return ParagraphStyle(name, parent=base, **kw)

    return {
        "body": make("body"),
        "small": make("small", fontSize=8, leading=10),
        "title": make("title", fontName=lk.bold, fontSize=26, leading=30,
                      textColor=ink, spaceAfter=6),
        "h1": make("h1", fontName=lk.bold, fontSize=16, leading=20,
                   textColor=ink, spaceBefore=16, spaceAfter=6,
                   keepWithNext=1),
        "h2": make("h2", fontName=lk.bold, fontSize=13, leading=16,
                   textColor=ink, spaceBefore=10, spaceAfter=4,
                   keepWithNext=1),
        "label": make("label", fontName=lk.bold, fontSize=8.5, leading=12,
                      textColor=colors.HexColor(MUTED)),
        "toc1": make("toc1", fontName=lk.bold, fontSize=11, leading=15,
                     textColor=ink),
        "toc2": make("toc2", fontSize=9.5, leading=13, leftIndent=14,
                     textColor=colors.HexColor("#444444")),
    }
