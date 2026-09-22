"""Stitching camera pictures into a mosaic (mosaic.py) and its place in the
report pages. The pictures are cut from one synthetic scene at known places,
with deliberate errors in their stage positions, so the matching can be checked
against the truth. Needs numpy, Pillow and matplotlib."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

try:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure
    import numpy as np
    from PIL import Image
    HAVE = True
except Exception:                                    # pragma: no cover
    HAVE = False

if HAVE:
    import imagepages as ip
    import mosaic
    import reportspec as rs
    import snapshot
    from readers import ImageBlob
    from readers.imaging import encode_png
    from test_htmlbrowser import CAMERA_CAL, doc, region

UM = 10.0                                     # micrometres per pixel of the scene
TW, TH = 320, 240                             # a tile, in pixels


def scene(w=900, h=600, seed=3):
    """A textured RGB picture: smooth blobs and a few sharp lines."""
    rng = np.random.default_rng(seed)
    noise = rng.normal(size=(h, w, 3))
    fx = np.fft.fftfreq(w)[None, :, None]
    fy = np.fft.fftfreq(h)[:, None, None]
    low = np.exp(-(fx ** 2 + fy ** 2) / (2 * 0.02 ** 2))
    img = np.fft.ifft2(np.fft.fft2(noise, axes=(0, 1)) * low,
                       axes=(0, 1)).real
    img = (img - img.min()) / (img.max() - img.min())
    out = (img * 200 + 25).astype("uint8")
    for x in range(60, w, 170):
        out[:, x:x + 3] = 250
    for y in range(40, h, 130):
        out[y:y + 3, :] = 10
    return out


SCENE_FRAME = {"x_mm": 0.0, "y_mm": 0.0, "um_per_px_x": UM, "um_per_px_y": UM,
               "width": 900, "height": 600}


class Tile:
    """A picture cut from ``img`` with its top left corner at ``(left, top)``;
    its stage position is that of the cut, plus ``err`` pixels."""

    def __init__(self, name, img, left, top, err=(0, 0)):
        self.name = name
        self.crop = img[top:top + TH, left:left + TW]
        cx, cy = snapshot.pixel_to_stage(SCENE_FRAME, left + err[0] + TW / 2,
                                         top + err[1] + TH / 2)
        self.calib = {"x_mm": cx, "y_mm": cy, "width": TW, "height": TH,
                      "um_per_px_x": UM, "um_per_px_y": UM}
        self.truth = (left, top)

    def array(self, max_px=640):
        if max_px >= TW:
            return self.crop
        im = Image.fromarray(self.crop).resize(
            (max_px, round(TH * max_px / TW)), Image.LANCZOS)
        return np.asarray(im)


@unittest.skipUnless(HAVE, "numpy, Pillow and matplotlib needed")
class TestClusters(unittest.TestCase):
    def setUp(self):
        self.img = scene()

    def test_overlapping_pictures_form_one_group_and_a_far_one_none(self):
        a = Tile("a", self.img, 100, 100)
        b = Tile("b", self.img, 300, 120)              # overlaps a
        c = Tile("c", self.img, 500, 130)              # overlaps b only
        far = Tile("far", self.img, 100, 100, err=(0, 0))
        far.calib = dict(far.calib, x_mm=far.calib["x_mm"] + 50)
        got = mosaic.clusters([a, b, c, far])
        self.assertEqual([[t.name for t in g] for g in got], [["a", "b", "c"]])

    def test_the_latest_picture_at_a_position_is_the_one_used(self):
        early = Tile("early", self.img, 100, 100)
        late = Tile("late", self.img, 100, 100)
        b = Tile("b", self.img, 300, 110)
        (g,) = mosaic.clusters([early, b, late])
        self.assertEqual([t.name for t in g], ["late", "b"])

    def test_pictures_of_another_pixel_size_are_not_mixed(self):
        a = Tile("a", self.img, 100, 100)
        b = Tile("b", self.img, 300, 110)
        b.calib = dict(b.calib, um_per_px_x=UM * 2, um_per_px_y=UM * 2)
        self.assertEqual(mosaic.clusters([a, b]), [])

    def test_a_barely_touching_pair_is_not_a_group(self):
        a = Tile("a", self.img, 100, 100)
        b = Tile("b", self.img, 100 + TW - 10, 100)     # 10 px of 320 overlap
        self.assertEqual(mosaic.clusters([a, b]), [])


@unittest.skipUnless(HAVE, "numpy, Pillow and matplotlib needed")
class TestGeometry(unittest.TestCase):
    def test_the_canvas_has_its_own_calibration_and_places_pictures_exactly(self):
        img = scene()
        tiles = [Tile("a", img, 100, 100), Tile("b", img, 300, 140)]
        frame = mosaic.frame_of(tiles)
        self.assertEqual((frame["width"], frame["height"]),
                         (520, 280))                    # 100..620 x 100..380
        for t, (left, top) in zip(tiles, mosaic.placed(frame, tiles)):
            self.assertAlmostEqual(left, t.truth[0] - 100, places=6)
            self.assertAlmostEqual(top, t.truth[1] - 100, places=6)
        # and the snapshot functions work on it like on a picture
        cx, cy = snapshot.pixel_to_stage(SCENE_FRAME, 200.0, 180.0)
        col, row = snapshot.stage_to_pixel(frame, cx, cy)
        self.assertAlmostEqual(col, 100.0, places=6)
        self.assertAlmostEqual(row, 80.0, places=6)


@unittest.skipUnless(HAVE, "numpy, Pillow and matplotlib needed")
class TestMatching(unittest.TestCase):
    def setUp(self):
        mosaic._memo.clear()
        self.img = scene()

    def offsets(self, m, tiles):
        """Where each picture ended up relative to the first, minus where it
        truly is: ~0 when the matching found the truth."""
        (l0, t0) = m.positions[tiles[0].name]
        out = []
        for t in tiles[1:]:
            l, tp = m.positions[t.name]
            out.append((round((l - l0) - (t.truth[0] - tiles[0].truth[0]), 1),
                        round((tp - t0) - (t.truth[1] - tiles[0].truth[1]), 1)))
        return out

    def test_a_stage_error_is_found_and_removed(self):
        a = Tile("a", self.img, 100, 100)
        b = Tile("b", self.img, 300, 140, err=(9, -7))     # 9 px right, 7 up
        m = mosaic.build([a, b])
        (dx, dy), = self.offsets(m, [a, b])
        self.assertLessEqual(abs(dx), 2.0)
        self.assertLessEqual(abs(dy), 2.0)
        self.assertEqual((m.matched, m.pairs), (1, 1))
        # without matching the error is left as it is
        mosaic._memo.clear()
        (rx, ry), = self.offsets(mosaic.build([a, b], refine=False), [a, b])
        self.assertAlmostEqual(rx, 9.0, delta=0.6)
        self.assertAlmostEqual(ry, -7.0, delta=0.6)

    def test_a_retaken_picture_does_not_reuse_the_old_mosaic(self):
        # same name, same stage position as a real retake would have, but a
        # different crop (so different pixels) and its own "blob" identity
        a = Tile("a", self.img, 100, 100)
        b = Tile("b", self.img, 300, 140)
        a.blob, b.blob = object(), object()
        m1 = mosaic.build([a, b])
        a2 = Tile("a", self.img, 140, 160)
        a2.calib = dict(a.calib)          # identical calibration to "a"
        a2.blob = object()                # a distinct picture, though
        m2 = mosaic.build([a2, b])
        self.assertFalse(np.array_equal(m1.array, m2.array))
        # calling again with the very same objects still hits the cache
        m3 = mosaic.build([a2, b])
        self.assertIs(m2, m3)

    def test_errors_along_a_chain_do_not_drift(self):
        tiles = [Tile("a", self.img, 60, 100), Tile("b", self.img, 250, 110,
                                                     err=(6, 5)),
                 Tile("c", self.img, 440, 120, err=(-8, 4)),
                 Tile("d", self.img, 600, 130, err=(5, -6))]
        m = mosaic.build(tiles)
        for dx, dy in self.offsets(m, tiles):
            self.assertLessEqual(abs(dx), 2.5)
            self.assertLessEqual(abs(dy), 2.5)

    def test_no_detail_no_move(self):
        flat = np.full((600, 900, 3), 128, dtype="uint8")
        a = Tile("a", flat, 100, 100)
        b = Tile("b", flat, 300, 140, err=(9, -7))
        m = mosaic.build([a, b])
        self.assertEqual(m.matched, 0)
        (rx, ry), = self.offsets(m, [a, b])
        self.assertAlmostEqual(rx, 9.0, delta=0.6)          # stage position kept
        self.assertTrue(any("too little detail" in n for n in m.notes))

    def test_a_perfect_placement_reproduces_the_scene(self):
        a = Tile("a", self.img, 100, 100)
        b = Tile("b", self.img, 300, 140)
        m = mosaic.build([a, b])
        k = m.array.shape[1] / m.calib["width"]
        self.assertAlmostEqual(k, 1.0)                        # small: full size
        truth = self.img[100:380, 100:620].astype(int)
        covered = np.zeros(truth.shape[:2], dtype=bool)
        for t in (a, b):                     # the corners no picture reaches
            covered[t.truth[1] - 100:t.truth[1] - 100 + TH,
                    t.truth[0] - 100:t.truth[0] - 100 + TW] = True
        self.assertLess(np.abs(m.array.astype(int) - truth)[covered].mean(),
                        1.0)
        self.assertEqual(m.array[~covered][:, 0].max(), 24)      # left dark

    def test_a_large_set_is_shrunk_to_the_limit(self):
        big = scene(w=5200, h=600, seed=5)
        tiles = [Tile(str(i), big, 60 + 300 * i, 100) for i in range(16)]
        m = mosaic.build(tiles, refine=False)
        self.assertLessEqual(max(m.array.shape[:2]), mosaic.MOSAIC_PX)
        self.assertGreater(m.calib["width"], mosaic.MOSAIC_PX)   # calibration: full size

    def test_solving_makes_pair_shifts_consistent(self):
        # 0 -> 1 by 4, 1 -> 2 by 4 and 0 -> 2 by 8: picture 2 moves about 8
        t = mosaic.solve_offsets(3, [(0, 1, 4, 0, 1.0), (1, 2, 4, 0, 1.0),
                                     (0, 2, 8, 0, 1.0)])
        self.assertAlmostEqual(t[2][0] - t[0][0], 8.0, delta=0.5)
        self.assertAlmostEqual(t[1][0] - t[0][0], 4.0, delta=0.4)
        # a picture nothing was matched to stays put
        t = mosaic.solve_offsets(3, [(0, 1, 4, 0, 1.0)])
        self.assertAlmostEqual(t[2][0], 0.0, places=6)


@unittest.skipUnless(HAVE, "numpy, Pillow and matplotlib needed")
class TestInThePages(unittest.TestCase):
    def setUp(self):
        mosaic._memo.clear()

    def blob(self, name, x_mm):
        w, h = 64, 48
        px = bytes((x * 4 + int(x_mm * 50)) % 256 if c == 0
                   else (y * 5) % 256 if c == 1 else 90
                   for y in range(h) for x in range(w) for c in range(3))
        return ImageBlob(name=name, offset=0, data=encode_png(w, h, px),
                         is_jpeg_intact=False, fmt="png", sample="S1",
                         calib=dict(CAMERA_CAL, x_mm=x_mm))

    def doc(self, xs=(10.0, 11.0, 12.0)):
        blobs = [self.blob(f"S1 Pt #00{i}a  10:0{i}", x)
                 for i, x in enumerate(xs)]
        return doc("a.vgd", [region("C 1s", "S1")],
                   positions={"S1": (10.0, 20.0), "S2": (11.0, 20.0)},
                   images=blobs)

    def test_a_mosaic_page_follows_the_sheets_when_asked(self):
        d = self.doc()
        self.assertEqual([p.kind for p in ip.plan([d])], ["camera"])
        pages = ip.plan([d], mosaics=True)
        self.assertEqual([(p.kind, p.title, p.n_items) for p in pages],
                         [("camera", "Camera pictures", 3),
                          ("mosaic", "Camera mosaic", 3)])

    def test_it_draws_with_the_analysis_points_on_it(self):
        pages = ip.plan([self.doc()], mosaics=True)
        fig = Figure(figsize=(11.7, 8.3), dpi=50)
        pages[1].draw(fig, (0.0, 0.05, 1.0, 0.93))
        ax = fig.axes[0]
        self.assertEqual(len(ax.images), 1)
        texts = [t.get_text() for t in ax.texts]
        self.assertIn("S1", texts)                    # the points sit on it
        self.assertIn("S2", texts)
        self.assertIn("Mosaic of 3 pictures", ax.get_title())
        note = pages[1].notes()
        self.assertIn("Mosaic:", note)
        self.assertIn("S1 Pt #000a  10:00", note)

    def test_a_picture_left_out_is_not_stitched_and_two_are_needed(self):
        d = self.doc()
        keys = [k for k, _l in ip.items([d])]
        pages = ip.plan([d], mosaics=True, skip=keys[:1])
        self.assertEqual(pages[1].n_items, 2)
        pages = ip.plan([d], mosaics=True, skip=keys[:2])
        self.assertEqual([p.kind for p in pages], ["camera"])   # one picture left

    def test_pictures_far_apart_make_no_mosaic(self):
        pages = ip.plan([self.doc(xs=(10.0, 40.0))], mosaics=True)
        self.assertEqual([p.kind for p in pages], ["camera"])

    def test_two_files_are_never_stitched_together(self):
        a, b = self.doc(xs=(10.0,)), self.doc(xs=(11.0,))
        b.path = "b.vgd"
        pages = ip.plan([a, b], mosaics=True)
        self.assertEqual([p.kind for p in pages], ["camera"])

    def test_the_option_is_on_by_default_and_off_for_the_old_names(self):
        self.assertEqual(rs.option(rs.default_spec(), "mosaic"), "on")
        self.assertEqual(rs.option(rs.with_option(rs.default_spec(), "mosaic",
                                                  "weird"), "mosaic"), "on")
        self.assertEqual(rs.option(rs.spec_from_sections(
            ("title", "images"), "deck"), "mosaic"), "off")


if __name__ == "__main__":
    unittest.main()
