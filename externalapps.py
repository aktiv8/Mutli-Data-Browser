"""Finding and starting the other programs a spectroscopist keeps beside this
one: CasaXPS and KherveFitting (Tk-free; ``winreg`` / ``ctypes`` are imported
only on Windows, inside the functions that need them).

``find(key, cfg)`` looks, in this order, at: the location the user gave
(``cfg["external_apps"]``), the Windows Uninstall and App Paths registry keys,
``PATH``, and the folders programs are usually put in (``Program Files``,
``<drive>:\\Software`` ...: one level of folders, then the exe in it or in a
versioned sub-folder). The last step matters: the CasaXPS download is a plain
unzipped folder with no registry entry or Start-Menu shortcut, so only a look
at the folders finds it. Nothing is ever searched recursively, so it is fast.

``icon_image(path)`` returns the program's own icon as a PIL image (Windows
only; ``None`` elsewhere or on any failure) and keeps it as a PNG under
``~/.spectradeck_icons`` so the extraction happens once per exe version.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

IS_WINDOWS = sys.platform == "win32"

APPS = {
    "casaxps": {"name": "CasaXPS", "exe": "CasaXPS.exe", "hint": "casaxps",
                "tip": "Open CasaXPS"},
    "khervefitting": {"name": "KherveFitting", "exe": "KherveFitting.exe",
                      "hint": "khervefitting", "tip": "Open KherveFitting"},
}

ICON_DIR = os.path.join(os.path.expanduser("~"), ".spectradeck_icons")
_SKIP = ("unins", "uninstall", "setup", "update")
_cache = {}


def forget():
    """Drop what ``find`` remembered (after the user changes a location)."""
    _cache.clear()


# -- finding ---------------------------------------------------------------
def _is_exe(path, exe):
    """``path`` is a file that looks like the program's own executable."""
    if not path or not os.path.isfile(path):
        return False
    base = os.path.basename(path).lower()
    stem = os.path.splitext(exe)[0].lower()
    return (base.endswith(".exe") if IS_WINDOWS else True) \
        and base.startswith(stem) and not base.startswith(_SKIP)


def _clean(value):
    """A registry path value: quotes and the ``,0`` icon index removed."""
    value = (value or "").strip().strip('"')
    if "," in value and not os.path.exists(value):
        value = value.rsplit(",", 1)[0].strip().strip('"')
    return value


def _in_folder(folder, exe):
    """The program's exe in ``folder``: the exact name, else the newest
    versioned one (``KherveFitting_1.80~26c01.exe``) in it or one level
    below."""
    if not os.path.isdir(folder):
        return None
    exact = os.path.join(folder, exe)
    if os.path.isfile(exact):
        return exact
    found = []
    try:
        for name in os.listdir(folder):
            p = os.path.join(folder, name)
            if _is_exe(p, exe):
                found.append(p)
            elif os.path.isdir(p):
                try:
                    found += [os.path.join(p, n) for n in os.listdir(p)
                              if _is_exe(os.path.join(p, n), exe)]
                except OSError:
                    pass
    except OSError:
        return None
    return max(found, key=os.path.getmtime) if found else None


def _registry_paths(hint, exe):
    """Candidate exes named by the Uninstall and App Paths keys."""
    out = []
    try:
        import winreg
    except ImportError:
        return out
    uninstall = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    for root, sub in (
            (winreg.HKEY_LOCAL_MACHINE, uninstall),
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, uninstall)):
        try:
            key = winreg.OpenKey(root, sub)
        except OSError:
            continue
        with key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    with winreg.OpenKey(key, winreg.EnumKey(key, i)) as k:
                        def val(n, k=k):
                            try:
                                return winreg.QueryValueEx(k, n)[0]
                            except OSError:
                                return ""
                        if hint not in str(val("DisplayName")).lower():
                            continue
                        out.append(_clean(val("DisplayIcon")))
                        loc = _clean(val("InstallLocation"))
                        if loc:
                            out.append(loc)
                except OSError:
                    continue
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(
                    root, r"SOFTWARE\Microsoft\Windows\CurrentVersion"
                          r"\App Paths" + "\\" + exe) as k:
                out.append(_clean(winreg.QueryValueEx(k, None)[0]))
        except OSError:
            pass
    return out


def _fixed_drives():
    """``["C:\\", "D:\\"]``: local disks only, so an unplugged network drive
    cannot stall the search."""
    try:
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        return [f"{chr(65 + i)}:\\" for i in range(26)
                if mask >> i & 1 and ctypes.windll.kernel32.GetDriveTypeW(
                    f"{chr(65 + i)}:\\") == 3]
    except Exception:
        return []


def _scan_roots():
    roots = []
    for d in _fixed_drives():
        roots += [d, d + "Program Files", d + "Program Files (x86)",
                  d + "Software", d + "Programs"]
    for var in ("ProgramFiles", "ProgramFiles(x86)"):
        if os.environ.get(var):
            roots.append(os.environ[var])
    if os.environ.get("LOCALAPPDATA"):
        roots.append(os.path.join(os.environ["LOCALAPPDATA"], "Programs"))
    # an unzipped download sits wherever the user put it
    home = os.path.expanduser("~")
    roots += [os.path.join(home, d) for d in
              ("Desktop", "Downloads", "Documents", "Applications")] + [home]
    if sys.platform == "darwin":
        roots.append("/Applications")
    elif not IS_WINDOWS:
        roots += ["/opt", os.path.join(home, ".local", "share")]
    seen, out = set(), []
    for r in roots:
        k = os.path.normcase(r)
        if k not in seen and os.path.isdir(r):
            seen.add(k)
            out.append(r)
    return out


def _scan_folders(hint, exe, roots=None):
    for root in (_scan_roots() if roots is None else roots):
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for name in names:
            if hint in name.lower().replace(" ", ""):
                got = _in_folder(os.path.join(root, name), exe)
                if got:
                    return got
    return None


def find(key, cfg=None, roots=None):
    """Path of the program ``key`` ("casaxps" / "khervefitting") or None."""
    app = APPS[key]
    saved = ((cfg or {}).get("external_apps") or {}).get(key)
    if saved and os.path.isfile(saved):
        return saved
    if key in _cache:
        return _cache[key]
    hint, exe = app["hint"], app["exe"]
    got = None
    if IS_WINDOWS and roots is None:
        for p in _registry_paths(hint, exe):
            if os.path.isdir(p):
                p = _in_folder(p, exe)
            if _is_exe(p, exe):
                got = p
                break
    if got is None and roots is None:
        got = shutil.which(exe) or shutil.which(os.path.splitext(exe)[0])
    if got is None:
        got = _scan_folders(hint, exe, roots)
    _cache[key] = got
    return got


# -- starting ---------------------------------------------------------------
def launch(path):
    """Start the program detached from this one. Returns ``""`` or a short
    message saying why it did not start."""
    try:
        if IS_WINDOWS:
            flags = (getattr(subprocess, "DETACHED_PROCESS", 0x8)
                     | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200))
            subprocess.Popen([path], cwd=os.path.dirname(path) or None,
                             close_fds=True, creationflags=flags)
        else:
            subprocess.Popen([path], cwd=os.path.dirname(path) or None,
                             start_new_session=True)
    except OSError as exc:
        return str(exc)
    return ""


# -- the program's own icon ----------------------------------------------------
def _extract_icon(path):
    """The large icon of an exe as RGBA (Windows). It is drawn on black and on
    white and the transparency worked out from the two, which keeps soft edges
    without ``pywin32``."""
    import ctypes
    from ctypes import wintypes
    from PIL import Image
    user32, gdi32, shell32 = (ctypes.windll.user32, ctypes.windll.gdi32,
                              ctypes.windll.shell32)
    shell32.ExtractIconExW.argtypes = [
        wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p), wintypes.UINT]
    gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi32.CreateDIBSection.restype = ctypes.c_void_p
    gdi32.SelectObject.restype = ctypes.c_void_p
    gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
    gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi32.CreateDIBSection.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, wintypes.DWORD]
    user32.DrawIconEx.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
        ctypes.c_int, ctypes.c_int, wintypes.UINT, ctypes.c_void_p,
        wintypes.UINT]
    user32.DestroyIcon.argtypes = [ctypes.c_void_p]

    large = ctypes.c_void_p()
    if shell32.ExtractIconExW(path, 0, ctypes.byref(large), None, 1) < 1 \
            or not large.value:
        return None
    n = 32

    class BIH(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]
    bih = BIH(ctypes.sizeof(BIH), n, -n, 1, 32, 0, n * n * 4, 0, 0, 0, 0)
    dc = gdi32.CreateCompatibleDC(None)
    bits = ctypes.c_void_p()
    bmp = gdi32.CreateDIBSection(dc, ctypes.byref(bih), 0,
                                 ctypes.byref(bits), None, 0)
    try:
        if not dc or not bmp or not bits.value:
            return None
        old = gdi32.SelectObject(dc, bmp)
        shots = []
        for fill in (0x00, 0xFF):
            ctypes.memset(bits.value, fill, n * n * 4)
            user32.DrawIconEx(dc, 0, 0, large, n, n, 0, None, 3)
            shots.append(ctypes.string_at(bits.value, n * n * 4))
        gdi32.SelectObject(dc, old)
    finally:
        if bmp:
            gdi32.DeleteObject(bmp)
        if dc:
            gdi32.DeleteDC(dc)
        user32.DestroyIcon(large)
    dark, light = shots
    out = bytearray(n * n * 4)
    for i in range(0, n * n * 4, 4):
        # per channel: light - dark = 255 * (1 - alpha)
        gap = sum(light[i + c] - dark[i + c] for c in range(3)) / 3.0
        a = max(0.0, min(1.0, 1.0 - gap / 255.0))
        if a > 0.004:
            for c, dst in ((2, 0), (1, 1), (0, 2)):         # BGR -> RGB
                out[i + dst] = min(255, int(round(dark[i + c] / a)))
        out[i + 3] = int(round(a * 255))
    return Image.frombytes("RGBA", (n, n), bytes(out))


def icon_image(path, cache_dir=None):
    """The program's own icon (32 x 32 RGBA PIL image) or None."""
    if not IS_WINDOWS or not path or not os.path.isfile(path):
        return None
    try:
        from PIL import Image
        cache_dir = cache_dir or ICON_DIR
        stamp = f"{os.path.getmtime(path):.0f}"
        name = "".join(c if c.isalnum() else "_" for c in
                       os.path.splitext(os.path.basename(path))[0])
        cached = os.path.join(cache_dir, f"{name}-{stamp}.png")
        if os.path.isfile(cached):
            return Image.open(cached).convert("RGBA")
        img = _extract_icon(path)
        if img is None or not img.getchannel("A").getbbox():
            return None
        try:
            os.makedirs(cache_dir, exist_ok=True)
            img.save(cached)
        except OSError:
            pass
        return img
    except Exception:
        return None
