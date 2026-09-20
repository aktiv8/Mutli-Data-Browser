"""Toolbar icons drawn in code (Pillow only), so they can take the colours of
whichever theme is active and never depend on an icon font.

Every icon is described on a 24 x 24 grid with a main colour and an accent
colour, drawn at 8x and shrunk with LANCZOS. ``draw`` returns a PIL image;
:class:`IconCache` turns them into Tk images for one palette (like
``themes.SwatchCache``) and is rebuilt when the theme changes.
"""

from __future__ import annotations

import math

SUPERSAMPLE = 8
STROKE = 1.7                 # line width on the 24-unit grid


class Pen:
    """Drawing helpers in grid units; ``a=True`` uses the accent colour."""

    def __init__(self, draw, k, main, accent):
        self.d, self.k, self.main, self.accent = draw, k, main, accent
        self.w = max(1, int(round(STROKE * k)))

    def _col(self, a):
        return self.accent if a else self.main

    def _pts(self, pts):
        return [(x * self.k, y * self.k) for x, y in pts]

    def line(self, pts, a=False, close=False):
        pts = list(pts) + ([pts[0]] if close else [])
        sp = self._pts(pts)
        self.d.line(sp, fill=self._col(a), width=self.w, joint="curve")
        r = self.w / 2.0
        for x, y in sp:                                  # round caps / joins
            self.d.ellipse([x - r, y - r, x + r, y + r], fill=self._col(a))

    def rect(self, x0, y0, x1, y1, r=1.5, a=False):
        self.d.rounded_rectangle(
            [x0 * self.k, y0 * self.k, x1 * self.k, y1 * self.k],
            radius=r * self.k, outline=self._col(a), width=self.w)

    def fill(self, x0, y0, x1, y1, r=1.0, a=True):
        self.d.rounded_rectangle(
            [x0 * self.k, y0 * self.k, x1 * self.k, y1 * self.k],
            radius=r * self.k, fill=self._col(a))

    def circle(self, cx, cy, r, a=False, solid=False):
        box = [(cx - r) * self.k, (cy - r) * self.k,
               (cx + r) * self.k, (cy + r) * self.k]
        if solid:
            self.d.ellipse(box, fill=self._col(a))
        else:
            self.d.ellipse(box, outline=self._col(a), width=self.w)

    def pie(self, cx, cy, r, start, end, a=True):
        self.d.pieslice([(cx - r) * self.k, (cy - r) * self.k,
                         (cx + r) * self.k, (cy + r) * self.k],
                        start, end, fill=self._col(a))

    def polygon(self, pts, a=True):
        self.d.polygon(self._pts(pts), fill=self._col(a))

    def ellipse_line(self, cx, cy, rx, ry, rot=0.0, a=False, n=48):
        c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        pts = []
        for i in range(n):
            t = 2 * math.pi * i / n
            x, y = rx * math.cos(t), ry * math.sin(t)
            pts.append((cx + x * c - y * s, cy + x * s + y * c))
        self.line(pts, a=a, close=True)


ICONS = {}


def icon(fn):
    ICONS[fn.__name__.lstrip("_")] = fn
    return fn


def _folder(p, a_line=False):
    p.line([(3, 6), (9, 6), (11, 8.5), (21, 8.5), (21, 19), (3, 19)],
           close=True)
    if a_line:
        p.line([(3, 12.5), (21, 12.5)], a=True)


@icon
def _open(p):
    _folder(p)
    p.line([(12, 16), (12, 11.5)], a=True)
    p.line([(9.8, 13.5), (12, 11.3), (14.2, 13.5)], a=True)


@icon
def folder(p):
    _folder(p, a_line=True)


@icon
def recent(p):
    p.circle(12, 12, 9)
    p.line([(12, 6.5), (12, 12), (15.8, 14.2)], a=True)


@icon
def save(p):
    p.line([(4, 4), (17, 4), (20, 7), (20, 20), (4, 20)], close=True)
    p.line([(8, 4), (8, 9), (15, 9), (15, 4)])
    p.rect(7, 13, 17, 20, r=0.8, a=True)


@icon
def export(p):
    p.line([(4, 14), (4, 20), (20, 20), (20, 14)])
    p.line([(12, 15), (12, 4)], a=True)
    p.line([(8, 8), (12, 4), (16, 8)], a=True)


@icon
def image(p):
    p.rect(3, 5, 21, 19)
    p.circle(8, 10, 1.7, a=True, solid=True)
    p.line([(3.5, 17), (9, 12.5), (13, 16), (16, 13), (20.5, 17.5)])


@icon
def _close(p):
    p.line([(6, 6), (18, 18)])
    p.line([(18, 6), (6, 18)], a=True)


@icon
def calibrate(p):
    p.rect(3, 8.5, 21, 15.5, r=1.2)
    for x in (7, 11, 15, 19):
        p.line([(x, 8.5), (x, 11.5)])
    p.line([(12, 15.5), (12, 20.5)], a=True)
    p.line([(9.5, 18), (12, 20.5), (14.5, 18)], a=True)


@icon
def identify(p):
    p.circle(10, 10, 6.5)
    p.line([(14.8, 14.8), (20.5, 20.5)])
    p.line([(6.8, 12.2), (8.5, 7.8), (10, 11), (11.5, 9), (13.2, 12.2)],
           a=True)


@icon
def iss(p):
    p.circle(12, 12, 2, a=True, solid=True)
    for rot in (0, 60, 120):
        p.ellipse_line(12, 12, 9.5, 3.8, rot)


@icon
def sputter(p):
    p.line([(12, 3), (12, 11)], a=True)
    p.line([(8.8, 8), (12, 11.2), (15.2, 8)], a=True)
    p.line([(4, 14.5), (20, 14.5)])
    p.line([(6, 18), (18, 18)])
    p.line([(8, 21.5), (16, 21.5)])


@icon
def snapmap(p):
    p.rect(4, 4, 20, 20, r=1.5)
    p.line([(9.3, 4), (9.3, 20)])
    p.line([(14.7, 4), (14.7, 20)])
    p.line([(4, 9.3), (20, 9.3)])
    p.line([(4, 14.7), (20, 14.7)])
    p.fill(9.9, 9.9, 14.1, 14.1, r=0.5)


@icon
def rename(p):
    p.line([(4, 20), (5, 15), (16, 4), (20, 8), (9, 19)], close=True)
    p.line([(13.5, 6.5), (17.5, 10.5)], a=True)


@icon
def notes(p):
    p.line([(4, 4), (20, 4), (20, 15), (15, 20), (4, 20)], close=True)
    p.line([(15, 20), (15, 15), (20, 15)], a=True)
    p.line([(7.5, 9), (16.5, 9)])
    p.line([(7.5, 13), (12, 13)])


@icon
def details(p):
    p.line([(5, 3), (14, 3), (19, 8), (19, 21), (5, 21)], close=True)
    p.line([(14, 3), (14, 8), (19, 8)], a=True)
    for y in (12, 15.5, 19):
        p.line([(8, y), (16, y)])


@icon
def figures(p):
    p.line([(4, 4), (4, 20), (20, 20)])
    p.line([(6.5, 16), (10, 10.5), (13, 14), (19, 6)], a=True)


@icon
def report(p):
    p.line([(5, 3), (14, 3), (19, 8), (19, 21), (5, 21)], close=True)
    p.fill(8, 8, 15, 10.2, r=0.6)
    p.line([(8, 14), (16, 14)])
    p.line([(8, 17.5), (13.5, 17.5)])


@icon
def preview(p):
    p.line([(2.5, 12), (7, 6.5), (12, 5), (17, 6.5), (21.5, 12),
            (17, 17.5), (12, 19), (7, 17.5)], close=True)
    p.circle(12, 12, 3, a=True, solid=True)


@icon
def slides(p):
    p.rect(3, 4.5, 21, 16.5)
    p.line([(12, 16.5), (12, 20.5)])
    p.line([(8, 20.5), (16, 20.5)])
    p.polygon([(10, 7.5), (10, 13.5), (15, 10.5)])


@icon
def package(p):
    p.line([(12, 3), (20, 7.5), (20, 16.5), (12, 21), (4, 16.5), (4, 7.5)],
           close=True)
    p.line([(4, 7.5), (12, 12), (20, 7.5)], a=True)
    p.line([(12, 12), (12, 21)], a=True)


@icon
def web(p):
    p.circle(12, 12, 9)
    p.ellipse_line(12, 12, 4, 9)
    p.line([(3, 12), (21, 12)], a=True)


@icon
def theme(p):
    p.circle(12, 12, 8.5)
    p.pie(12, 12, 8.5, 90, 270)


@icon
def style(p):
    for y, x in ((7, 8), (12, 15.5), (17, 10)):
        p.line([(4, y), (20, y)])
        p.circle(x, y, 2.1, a=True, solid=True)


@icon
def files(p):
    p.rect(3, 4, 21, 20, r=1.5)
    p.fill(3.8, 4.8, 8.6, 19.2, r=0.6)
    p.line([(9.5, 4), (9.5, 20)])


@icon
def details_pane(p):
    p.rect(3, 4, 21, 20, r=1.5)
    p.fill(15.4, 4.8, 20.2, 19.2, r=0.6)
    p.line([(14.5, 4), (14.5, 20)])


@icon
def focus(p):
    for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        cx, cy = 12 + sx * 8, 12 + sy * 8
        p.line([(cx - sx * 5, cy), (cx, cy), (cx, cy - sy * 5)],
               a=(sx == sy))


@icon
def expand(p):
    p.line([(7, 6.5), (12, 11), (17, 6.5)])
    p.line([(7, 13), (12, 17.5), (17, 13)], a=True)


@icon
def collapse(p):
    p.line([(7, 11), (12, 6.5), (17, 11)])
    p.line([(7, 17.5), (12, 13), (17, 17.5)], a=True)


@icon
def untick(p):
    p.rect(4, 4, 20, 20, r=2)
    p.line([(8, 12), (16, 12)], a=True)


@icon
def about(p):
    p.circle(12, 12, 9)
    p.circle(12, 7.8, 1.3, a=True, solid=True)
    p.line([(12, 11), (12, 17)], a=True)


NAMES = tuple(ICONS)


def draw(name, size=24, colour="#000000", accent=None):
    """The icon ``name`` as a ``size`` x ``size`` RGBA PIL image. ``accent``
    defaults to the main colour. KeyError for an unknown name."""
    from PIL import Image, ImageDraw
    fn = ICONS[name]
    big = int(size) * SUPERSAMPLE
    im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    fn(Pen(ImageDraw.Draw(im), big / 24.0, colour, accent or colour))
    return im.resize((int(size), int(size)), Image.LANCZOS)


def resolve_colour(colour, master=None):
    """``colour`` as a ``#rrggbb`` string Pillow can read. Tk colour names
    such as the native theme's ``systemwindowtext`` go through Tk."""
    from PIL import ImageColor
    try:
        ImageColor.getrgb(colour)
        return colour
    except ValueError:
        pass
    try:
        import tkinter
        w = master or tkinter._default_root
        r, g, b = (v // 257 for v in w.winfo_rgb(colour))
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return "#808080"


class IconCache:
    """Tk images of the icons for one palette: the main colour is the text
    colour, the accent the palette accent, and the disabled look uses the
    muted colour for both. Needs a Tk root (creates ``ImageTk`` images)."""

    def __init__(self, palette, size=22, master=None):
        self.pal = palette
        self.size = int(size)
        self.master = master
        self._cache = {}

    def get(self, name, disabled=False):
        key = (name, bool(disabled))
        img = self._cache.get(key)
        if img is None:
            from PIL import ImageTk
            p = self.pal
            main = resolve_colour(p["muted" if disabled else "fg"],
                                  self.master)
            acc = resolve_colour(p["muted" if disabled else "accent"],
                                 self.master)
            img = self._cache[key] = ImageTk.PhotoImage(
                draw(name, self.size, main, acc), master=self.master)
        return img
