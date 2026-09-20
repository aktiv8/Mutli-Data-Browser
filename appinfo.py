"""The application's name, in one place. Every window title, generated
document and file metadata that names the app uses ``NAME``, so the spelling
(including the capitals) cannot drift.

Also the version, the project link, where the splash / About picture lives and
the plain-text version report the About box copies. Tk-free."""

import os
import platform

NAME = "eXPoSe SpectraDeck"
VERSION = "1.0"
DESCRIPTION = ("Browse, plot and export XPS spectra from many instruments "
               "in one window.")
GITHUB_URL = "https://github.com/aktiv8"
FONT_CREDIT = "Fonts: IBM Plex Sans, SIL Open Font License 1.1"

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif")

# (label, import name, distribution name) of the libraries the About box lists
LIBRARIES = (("matplotlib", "matplotlib", "matplotlib"),
             ("Pillow", "PIL", "pillow"),
             ("numpy", "numpy", "numpy"),
             ("reportlab", "reportlab", "reportlab"),
             ("PyMuPDF", "fitz", "pymupdf"),
             ("python-pptx", "pptx", "python-pptx"))


def image_path(kind="splash"):
    """The picture the user supplied, or None. ``kind`` is ``"splash"`` or
    ``"about"`` (an optional smaller picture; the splash is used when there is
    none). Looks for ``assets/<kind>.png`` / ``.jpg`` / ``.jpeg`` / ``.gif``."""
    stems = [kind] if kind == "splash" else [kind, "splash"]
    for stem in stems:
        for ext in IMAGE_EXTS:
            path = os.path.join(ASSETS, stem + ext)
            if os.path.isfile(path):
                return path
    return None


def cover_dir():
    """The folder the user drops report cover pictures into (it need not
    exist): ``assets/covers``."""
    return os.path.join(ASSETS, "covers")


def cover_images(folder=None):
    """``[(file name, path)]`` of the pictures in the cover folder, by name.
    Never raises (a missing or unreadable folder is an empty list)."""
    folder = folder or cover_dir()
    try:
        names = sorted(os.listdir(folder), key=str.lower)
    except OSError:
        return []
    return [(n, os.path.join(folder, n)) for n in names
            if os.path.splitext(n)[1].lower() in IMAGE_EXTS
            and os.path.isfile(os.path.join(folder, n))]


def library_versions():
    """``[(label, version or None)]`` for the libraries the app can use;
    None when one is not installed. Never raises."""
    from importlib import metadata
    out = []
    for label, module, dist in LIBRARIES:
        version = None
        try:
            version = metadata.version(dist)
        except Exception:
            try:
                version = getattr(__import__(module), "__version__", None)
            except Exception:
                version = None
        out.append((label, version))
    return out


def version_report():
    """Plain text for a bug report: app, Python, Tk and library versions."""
    try:
        import tkinter
        tk_version = str(tkinter.TkVersion)
    except Exception:
        tk_version = "not available"
    lines = [f"{NAME} {VERSION}",
             f"Python {platform.python_version()} "
             f"({platform.system()} {platform.release()}, "
             f"{platform.machine()})",
             f"Tk {tk_version}"]
    for label, version in library_versions():
        lines.append(f"{label} {version}" if version
                     else f"{label} (not installed)")
    lines.append(GITHUB_URL)
    return "\n".join(lines)
