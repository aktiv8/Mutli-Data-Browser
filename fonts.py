"""Bundled UI typeface (IBM Plex Sans, SIL Open Font License, see
``assets/fonts/OFL.txt``) for both Tk and matplotlib.

Tk cannot load web fonts, so the font files are registered with the operating
system *for this process only* (call :func:`register_process_fonts` before
``tk.Tk()``). Every step is best effort: if anything fails, the app keeps the
system font and the plots keep matplotlib's default.
"""

from __future__ import annotations

import ctypes
import os
import sys

FAMILY = "IBM Plex Sans"
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "assets", "fonts")
FILES = ("IBMPlexSans-Regular.ttf", "IBMPlexSans-Bold.ttf")

# Type scale (points): caption / body / strong / section / panel title
SIZE = {"caption": 8, "body": 9, "strong": 9, "section": 10, "title": 10}

_TK_NAMED = ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont",
             "TkCaptionFont", "TkSmallCaptionFont", "TkIconFont",
             "TkTooltipFont")


def font_paths():
    return [p for p in (os.path.join(FONT_DIR, f) for f in FILES)
            if os.path.isfile(p)]


def register_process_fonts() -> bool:
    """Make the bundled font files visible to Tk. True if all were added."""
    paths = font_paths()
    if len(paths) != len(FILES):
        return False
    try:
        if sys.platform.startswith("win"):
            add = ctypes.windll.gdi32.AddFontResourceExW
            add.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
            return all(add(p, 0x10, None) for p in paths)      # FR_PRIVATE
        if sys.platform == "darwin":
            ct = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/CoreText.framework/CoreText")
            cf = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/CoreFoundation.framework/"
                "CoreFoundation")
            make = cf.CFURLCreateFromFileSystemRepresentation
            make.restype = ctypes.c_void_p
            make.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long,
                             ctypes.c_bool]
            reg = ct.CTFontManagerRegisterFontsForURL
            reg.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
            reg.restype = ctypes.c_bool
            ok = True
            for p in paths:
                raw = os.fsencode(p)
                ok &= bool(reg(make(None, raw, len(raw), False), 1, None))
            return ok
        fc = ctypes.cdll.LoadLibrary("libfontconfig.so.1")
        fc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        return all(fc.FcConfigAppFontAddFile(None, os.fsencode(p))
                   for p in paths)
    except Exception:                       # noqa: BLE001 - never block start-up
        return False


def apply_tk_fonts(root) -> str:
    """Point Tk's named fonts at the bundled family. Returns the family now in
    use (the system default's family if the bundled one isn't available)."""
    import tkinter.font as tkfont
    default = tkfont.nametofont("TkDefaultFont").actual("family")
    try:
        if FAMILY not in set(tkfont.families(root)):
            return default
        for name in _TK_NAMED:
            f = tkfont.nametofont(name)
            f.configure(family=FAMILY, size=SIZE["body"])
        tkfont.nametofont("TkCaptionFont").configure(weight="bold")
        return FAMILY
    except Exception:                       # noqa: BLE001
        return default


def register_matplotlib() -> str | None:
    """Add the font files to matplotlib; returns the family or None."""
    try:
        from matplotlib import font_manager
        for p in font_paths():
            font_manager.fontManager.addfont(p)
        names = {f.name for f in font_manager.fontManager.ttflist}
        return FAMILY if FAMILY in names else None
    except Exception:                       # noqa: BLE001
        return None
