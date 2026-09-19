"""Holder photo geometry (calibration maths and marker picking) and the
per-workbook storage of the calibration.

Run:  python -m unittest discover tests
"""

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import holder  # noqa: E402
import workbook as wbk  # noqa: E402

CALIBS = [
    dict(holder.DEFAULT),
    {"centre_x_mm": 12.5, "centre_y_mm": -3.0, "mm_per_px": 0.031,
     "flip_x": False, "flip_y": False, "rotation_deg": 0.0},
    {"centre_x_mm": 12.5, "centre_y_mm": -3.0, "mm_per_px": 0.031,
     "flip_x": True, "flip_y": False, "rotation_deg": 17.0},
    {"centre_x_mm": -40.0, "centre_y_mm": 8.0, "mm_per_px": 0.05,
     "flip_x": True, "flip_y": True, "rotation_deg": -130.0},
    {"centre_x_mm": 0.0, "centre_y_mm": 0.0, "mm_per_px": 0.02,
     "flip_x": False, "flip_y": True, "rotation_deg": 90.0},
]


class TestMapping(unittest.TestCase):
    def test_centre_maps_to_the_middle_of_the_photo(self):
        c = CALIBS[1]
        self.assertEqual(holder.stage_to_pixel(12.5, -3.0, 800, 600, c),
                         (400.0, 300.0))

    def test_plain_calibration(self):
        c = dict(holder.DEFAULT, mm_per_px=0.5)
        self.assertEqual(holder.stage_to_pixel(10, 5, 100, 80, c),
                         (70.0, 50.0))

    def test_flips_and_rotation(self):
        c = dict(holder.DEFAULT, mm_per_px=1.0)
        self.assertEqual(holder.stage_to_pixel(10, 0, 0, 0, dict(c, flip_x=True)),
                         (-10.0, 0.0))
        self.assertEqual(holder.stage_to_pixel(0, 4, 0, 0, dict(c, flip_y=True)),
                         (0.0, -4.0))
        x, y = holder.stage_to_pixel(10, 0, 0, 0, dict(c, rotation_deg=90))
        self.assertAlmostEqual(x, 0.0)
        self.assertAlmostEqual(y, 10.0)

    def test_pixel_to_stage_inverts_stage_to_pixel(self):
        for c in CALIBS:
            for x, y in ((0.0, 0.0), (20.0, 7.5), (-33.3, 41.0)):
                px, py = holder.stage_to_pixel(x, y, 640, 480, c)
                bx, by = holder.pixel_to_stage(px, py, 640, 480, c)
                self.assertAlmostEqual(bx, x, 6, str(c))
                self.assertAlmostEqual(by, y, 6, str(c))

    def test_marker_points(self):
        pts = holder.marker_points({"A": (0, 0), "B": (10, 0)}, 100, 100,
                                   dict(holder.DEFAULT, mm_per_px=1.0))
        self.assertEqual(pts, {"A": (50.0, 50.0), "B": (60.0, 50.0)})


class TestAdjustments(unittest.TestCase):
    def moved(self, c, new, pos=(7.0, -4.0)):
        a = holder.stage_to_pixel(*pos, 640, 480, c)
        b = holder.stage_to_pixel(*pos, 640, 480, new)
        return b[0] - a[0], b[1] - a[1]

    def test_nudge_moves_the_markers_by_that_many_pixels(self):
        """An arrow always moves the markers the way it points, whatever
        the flips and rotation."""
        for c in CALIBS:
            for dx, dy in ((10, 0), (-10, 0), (0, 10), (0, -10), (7, -3)):
                mx, my = self.moved(c, holder.nudged(c, dx, dy))
                self.assertAlmostEqual(mx, dx, 6, f"{c} {dx},{dy}")
                self.assertAlmostEqual(my, dy, 6, f"{c} {dx},{dy}")

    def test_nudge_leaves_scale_flips_and_rotation_alone(self):
        c = CALIBS[3]
        n = holder.nudged(c, 5, 5)
        for k in ("mm_per_px", "flip_x", "flip_y", "rotation_deg"):
            self.assertEqual(n[k], c[k])
        self.assertIsNot(n, c)

    def test_scaled_spreads_markers_from_the_centre(self):
        c = CALIBS[2]
        wide = holder.scaled(c, 1.5)
        a = holder.stage_to_pixel(30, 10, 640, 480, c)
        b = holder.stage_to_pixel(30, 10, 640, 480, wide)
        self.assertAlmostEqual(b[0] - 320, (a[0] - 320) * 1.5)
        self.assertAlmostEqual(b[1] - 240, (a[1] - 240) * 1.5)
        self.assertEqual(holder.scaled(c, 0), c)
        self.assertEqual(holder.scaled(c, -2), c)

    def test_rotation_wraps_and_flip_toggles(self):
        c = dict(holder.DEFAULT, rotation_deg=175.0)
        self.assertAlmostEqual(holder.rotated(c, 10)["rotation_deg"], -175.0)
        self.assertAlmostEqual(holder.rotated(c, -350)["rotation_deg"], -175.0)
        self.assertTrue(holder.flipped(c, "x")["flip_x"])
        self.assertFalse(holder.flipped(holder.flipped(c, "y"), "y")["flip_y"])
        self.assertFalse(c["flip_x"])                    # input untouched

    def test_rotating_by_zero_or_a_full_turn_changes_nothing(self):
        c = CALIBS[1]
        p = holder.stage_to_pixel(5, 5, 640, 480, c)
        for deg in (0, 360):
            q = holder.stage_to_pixel(5, 5, 640, 480, holder.rotated(c, deg))
            self.assertAlmostEqual(p[0], q[0])
            self.assertAlmostEqual(p[1], q[1])


class TestNearest(unittest.TestCase):
    pts = {"A": (100.0, 100.0), "B": (110.0, 100.0), "C": (400.0, 300.0)}

    def test_closest_within_radius(self):
        self.assertEqual(holder.nearest(self.pts, 108, 101, 16), "B")
        self.assertEqual(holder.nearest(self.pts, 102, 99, 16), "A")
        self.assertEqual(holder.nearest(self.pts, 398, 305, 16), "C")

    def test_nothing_in_reach(self):
        self.assertIsNone(holder.nearest(self.pts, 250, 200, 16))
        self.assertIsNone(holder.nearest({}, 0, 0, 16))


try:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure
    HAVE_MPL = True
except Exception:
    HAVE_MPL = False


@unittest.skipUnless(HAVE_MPL, "matplotlib not installed")
class TestMarkerDrawing(unittest.TestCase):
    def marks(self, points, hot=()):
        import plots
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        fig = Figure(figsize=(4, 3), dpi=80)
        FigureCanvasAgg(fig)
        ax = fig.add_subplot(111)
        ax.set_xlim(0, 100)
        ax.set_ylim(100, 0)
        out = plots.draw_holder_markers(ax, points, hot)
        fig.tight_layout()
        plots.place_marker_labels(ax, out, hot)
        fig.canvas.draw()
        return fig, ax, out

    def test_one_artist_set_per_sample_with_a_halo(self):
        _fig, _ax, out = self.marks({"A": (20, 20), "": (60, 60)}, {"A"})
        self.assertEqual(set(out), {"A", ""})
        ring, dot, text = out["A"]
        self.assertEqual(text.get_text(), "A")
        self.assertEqual(out[""][2].get_text(), "(unnamed)")
        self.assertTrue(text.get_path_effects())          # label halo
        self.assertGreater(ring.get_linewidths()[0], dot.get_linewidths()[0])
        self.assertEqual(text.get_fontweight(), "bold")   # selected
        self.assertNotEqual(out[""][2].get_fontweight(), "bold")

    def test_neighbouring_labels_do_not_overlap(self):
        pts = {"Sample A": (50, 50), "Sample B": (52, 51),
               "Sample C": (50, 53)}
        fig, _ax, out = self.marks(pts, {"Sample A"})
        r = fig.canvas.get_renderer()
        boxes = [t.get_window_extent(r) for _a, _b, t in out.values()]
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                self.assertFalse(a.overlaps(b))

    def test_a_label_does_not_cover_another_marker(self):
        pts = {"Long sample name": (50, 50), "B": (58, 50)}
        fig, ax, out = self.marks(pts)
        r = fig.canvas.get_renderer()
        bb = out["Long sample name"][2].get_window_extent(r)
        bx, by = ax.transData.transform((58, 50))
        self.assertFalse(bb.contains(bx, by))


class TestSanitise(unittest.TestCase):
    def test_good_calibration_is_completed(self):
        c = holder.sanitise({"centre_x_mm": "5", "mm_per_px": 0.1})
        self.assertEqual(c["centre_x_mm"], 5.0)
        self.assertEqual(c["mm_per_px"], 0.1)
        self.assertEqual(c["rotation_deg"], 0.0)
        self.assertFalse(c["flip_x"])

    def test_unusable_values_give_none(self):
        for bad in (None, "x", [], {"mm_per_px": 0}, {"mm_per_px": "abc"},
                    {"centre_x_mm": float("nan")}, {"centre_y_mm": True},
                    {"centre_x_mm": [1]}):
            self.assertIsNone(holder.sanitise(bad), bad)

    def test_negative_scale_is_made_positive(self):
        self.assertEqual(holder.sanitise({"mm_per_px": -0.2})["mm_per_px"],
                         0.2)

    def test_round_trip(self):
        for c in CALIBS:
            self.assertEqual(holder.sanitise(c), c)


class TestWorkbookHolder(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.data = os.path.join(self.dir, "a.avg")
        with open(self.data, "wb") as fh:
            fh.write(b"<xml/>")

    def book(self, **kw):
        return wbk.Workbook(files=[wbk.FileEntry("f1", "a.avg", self.data)],
                            **kw)

    def test_calibration_is_stored_in_the_workbook(self):
        path = os.path.join(self.dir, "x" + wbk.EXT)
        wbk.save(path, self.book(holder={"calibration": CALIBS[3]}))
        out = wbk.load(path, os.path.join(self.dir, "out"))
        self.assertEqual(holder.sanitise(out.holder["calibration"]),
                         CALIBS[3])

    def test_workbook_without_holder_loads_with_an_empty_one(self):
        path = os.path.join(self.dir, "y" + wbk.EXT)
        wbk.save(path, self.book())
        out = wbk.load(path, os.path.join(self.dir, "out"))
        self.assertEqual(out.holder, {})
        # a workbook saved before holder.json existed
        import zipfile
        old = os.path.join(self.dir, "old" + wbk.EXT)
        with zipfile.ZipFile(path) as zin, zipfile.ZipFile(old, "w") as zout:
            for name in zin.namelist():
                if name != "holder.json":
                    zout.writestr(name, zin.read(name))
        self.assertEqual(wbk.load(old, os.path.join(self.dir, "o2")).holder,
                         {})

    def test_damaged_holder_is_ignored_not_fatal(self):
        import json
        import zipfile
        path = os.path.join(self.dir, "z" + wbk.EXT)
        wbk.save(path, self.book(holder={"calibration": CALIBS[1]}))
        bad = os.path.join(self.dir, "bad" + wbk.EXT)
        with zipfile.ZipFile(path) as zin, zipfile.ZipFile(bad, "w") as zout:
            for name in zin.namelist():
                data = zin.read(name)
                if name == "holder.json":
                    data = json.dumps([1, 2]).encode()
                zout.writestr(name, data)
        self.assertEqual(wbk.load(bad, os.path.join(self.dir, "o")).holder, {})


if __name__ == "__main__":
    unittest.main()
