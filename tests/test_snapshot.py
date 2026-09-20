"""Camera-image geometry (snapshot.py), checked against numbers measured on real
K-Alpha+ images: two points 2048 um apart in Y and 100 um in X sat 435 px
apart in the picture, in the direction given below."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import snapshot as sn  # noqa: E402
import snapmap  # noqa: E402
from readers.base import ImageBlob  # noqa: E402

CAL = {"width": 1280, "height": 960, "um_per_px_x": 4.72103125,
       "um_per_px_y": 4.705885416666667, "x_mm": 38.897708, "y_mm": 40.268707}


class TestGeometry(unittest.TestCase):
    def test_the_centre_is_the_stage_position(self):
        self.assertEqual(sn.stage_to_pixel(CAL, 38.897708, 40.268707),
                         (640.0, 480.0))

    def test_directions_measured_on_real_images(self):
        # point 001b: +2048.4 um in Y and +99.6 um in X from point 001a
        col, row = sn.stage_to_pixel(CAL, 38.9973, 42.3171)
        self.assertAlmostEqual(row, 480 + 435.3, delta=0.5)   # down, with +Y
        self.assertAlmostEqual(col, 640 - 21.1, delta=0.5)    # left, against +X
        # and the photos, registered against each other, put the content 438 px
        # up for the Y step
        self.assertLess(abs((row - 480) - 438), 4)

    def test_round_trip(self):
        for pos in ((38.9, 40.2), (30.0, 45.5), (43.4, 13.5)):
            back = sn.pixel_to_stage(CAL, *sn.stage_to_pixel(CAL, *pos))
            self.assertAlmostEqual(back[0], pos[0], places=9)
            self.assertAlmostEqual(back[1], pos[1], places=9)

    def test_field_of_view(self):
        w, h = sn.field_of_view_mm(CAL)
        self.assertAlmostEqual(w, 6.0429, places=3)
        self.assertAlmostEqual(h, 4.5177, places=3)

    def test_markers_keep_only_what_is_in_view(self):
        pos = {"here": (38.9, 40.27), "near": (38.99, 42.3),
               "far": (22.86, 44.68)}
        got = sn.markers(CAL, pos)
        self.assertEqual(set(got), {"here", "near"})
        self.assertEqual(set(sn.markers(CAL, pos, margin=1e5)), set(pos))

    def test_calibration_needs_every_field(self):
        self.assertTrue(sn.has_calibration(CAL))
        self.assertFalse(sn.has_calibration({}))
        self.assertFalse(sn.has_calibration(None))
        self.assertFalse(sn.has_calibration({**CAL, "x_mm": None}))


class TestMapOnPicture(unittest.TestCase):
    def cube(self, **kw):
        # the real map: 100 x 100 pixels of 20 um, -990 .. +990
        return snapmap.MapCube([1.0, 2.0], 100, 100, -990.0, 20.0, -990.0, 20.0,
                               **kw)

    def test_a_centred_map_covers_the_middle_of_the_picture(self):
        cube = self.cube(stage_x_mm=CAL["x_mm"], stage_y_mm=CAL["y_mm"])
        left, top, w, h = sn.map_rectangle(CAL, cube)
        self.assertAlmostEqual(left + w / 2, 640.0, places=6)
        self.assertAlmostEqual(top + h / 2, 480.0, places=6)
        self.assertAlmostEqual(w, 2000 / 4.72103125, places=6)     # 2 mm wide
        self.assertAlmostEqual(h, 2000 / 4.705885416666667, places=6)

    def test_an_off_centre_map_moves_with_the_stage_not_the_image_axes(self):
        # map 0.5 mm further +Y and +X than the picture centre
        cube = self.cube(stage_x_mm=CAL["x_mm"] + 0.5,
                         stage_y_mm=CAL["y_mm"] + 0.5)
        left, top, w, h = sn.map_rectangle(CAL, cube)
        self.assertLess(left + w / 2, 640)         # X: to the left
        self.assertGreater(top + h / 2, 480)       # Y: further down

    def test_no_stage_position_means_the_centre(self):
        left, top, w, h = sn.map_rectangle(CAL, self.cube())
        self.assertAlmostEqual(left + w / 2, 640.0, places=6)


class TestNearestImage(unittest.TestCase):
    def blob(self, x, y, name):
        return ImageBlob(name, 0, b"", False, calib={**CAL, "x_mm": x,
                                                     "y_mm": y})

    def test_finds_the_picture_taken_at_a_position(self):
        a, b = self.blob(22.855, 44.677, "a"), self.blob(22.855, 46.123, "b")
        self.assertIs(sn.nearest_image([a, b], 22.8556, 44.6771), a)
        self.assertIsNone(sn.nearest_image([a, b], 30.0, 30.0))

    def test_uncalibrated_images_are_ignored(self):
        plain = ImageBlob("holder", 0, b"", True)
        self.assertIsNone(sn.nearest_image([plain], 1.0, 1.0))

    def test_the_latest_of_equally_near_pictures_wins(self):
        early, late = (self.blob(1.0, 1.0, "early"), self.blob(1.0, 1.0, "late"))
        self.assertIs(sn.nearest_image([early, late], 1.0, 1.0), late)


if __name__ == "__main__":
    unittest.main()
