"""The splash screen, the About box and the constants behind them.

Window checks are skipped when there is no display.

Run:  python -m unittest discover tests
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import about_ui  # noqa: E402
import appinfo  # noqa: E402
import splash  # noqa: E402

try:
    from PIL import Image
    HAVE_PIL = True
except Exception:
    HAVE_PIL = False


def make_picture(folder, name="splash.png", size=(1600, 900)):
    path = os.path.join(folder, name)
    Image.new("RGB", size, "#204060").save(path)
    return path


class TempAssets(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        p = mock.patch.object(appinfo, "ASSETS", self.dir)
        p.start()
        self.addCleanup(p.stop)


class TestAppInfo(TempAssets):
    def test_the_name_and_link(self):
        self.assertEqual(appinfo.NAME, "eXPoSe SpectraDeck")
        self.assertEqual(appinfo.GITHUB_URL, "https://github.com/aktiv8")
        self.assertRegex(appinfo.VERSION, r"^\d+\.\d+")

    def test_no_picture_is_none(self):
        self.assertIsNone(appinfo.image_path("splash"))
        self.assertIsNone(appinfo.image_path("about"))

    @unittest.skipUnless(HAVE_PIL, "Pillow not installed")
    def test_the_picture_is_found_in_any_supported_format(self):
        for ext in (".png", ".jpg", ".gif"):
            for f in os.listdir(self.dir):
                os.remove(os.path.join(self.dir, f))
            path = os.path.join(self.dir, "splash" + ext)
            Image.new("RGB", (20, 10), "red").save(path)
            self.assertEqual(appinfo.image_path("splash"), path)

    @unittest.skipUnless(HAVE_PIL, "Pillow not installed")
    def test_about_prefers_its_own_picture_and_falls_back_to_the_splash(self):
        splash_png = make_picture(self.dir, "splash.png", (40, 20))
        self.assertEqual(appinfo.image_path("about"), splash_png)
        about_png = make_picture(self.dir, "about.png", (20, 20))
        self.assertEqual(appinfo.image_path("about"), about_png)
        self.assertEqual(appinfo.image_path("splash"), splash_png)

    def test_version_report_names_everything(self):
        text = appinfo.version_report()
        for want in (appinfo.NAME, appinfo.VERSION, "Python", "Tk",
                     appinfo.GITHUB_URL, "matplotlib"):
            self.assertIn(want, text)

    def test_a_missing_library_is_reported_not_raised(self):
        with mock.patch.object(appinfo, "LIBRARIES",
                               (("Nope", "no_such_module_xyz",
                                 "no-such-dist-xyz"),)):
            self.assertEqual(appinfo.library_versions(), [("Nope", None)])
            self.assertIn("Nope (not installed)", appinfo.version_report())


class TestSplashSetting(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, "cfg.json")

    def test_on_by_default(self):
        self.assertTrue(splash.wanted([], self.path))              # no file

    def test_switched_off_by_the_flag(self):
        self.assertFalse(splash.wanted(["x", "--no-splash"], self.path))

    def test_switched_off_by_the_setting(self):
        with open(self.path, "w") as fh:
            json.dump({"show_splash": False}, fh)
        self.assertFalse(splash.wanted([], self.path))
        with open(self.path, "w") as fh:
            json.dump({"show_splash": True}, fh)
        self.assertTrue(splash.wanted([], self.path))

    def test_a_broken_settings_file_does_not_stop_the_splash(self):
        with open(self.path, "w") as fh:
            fh.write("{not json")
        self.assertTrue(splash.wanted([], self.path))


def tk_root():
    try:
        import tkinter
        root = tkinter.Tk()
    except Exception:
        return None
    root.withdraw()
    return root


class TestSplashWindow(TempAssets):
    def setUp(self):
        super().setUp()
        self.root = tk_root()
        if self.root is None:
            self.skipTest("no display")
        self.addCleanup(self.root.destroy)
        self.addCleanup(splash._destroy)

    @unittest.skipUnless(HAVE_PIL, "Pillow not installed")
    def test_shows_the_picture_scaled_to_the_screen(self):
        make_picture(self.dir, size=(6000, 3000))
        win = splash.show(self.root)
        self.assertTrue(splash.is_open())
        self.assertLessEqual(splash._S["photo"].width(),
                             self.root.winfo_screenwidth() * 0.61)
        self.assertLessEqual(win.winfo_reqwidth(),
                             self.root.winfo_screenwidth())

    def test_without_a_picture_it_is_a_text_card(self):
        splash.show(self.root)
        self.assertTrue(splash.is_open())
        self.assertIsNone(splash._S["photo"])

    def test_an_unreadable_picture_is_ignored(self):
        with open(os.path.join(self.dir, "splash.png"), "w") as fh:
            fh.write("not an image")
        splash.show(self.root)
        self.assertTrue(splash.is_open())
        self.assertIsNone(splash._S["photo"])

    def test_status_updates_and_is_harmless_when_closed(self):
        splash.show(self.root)
        splash.status("Loading the file readers…")
        self.assertIn("readers", splash._S["status"].cget("text"))
        splash._destroy()
        splash.status("again")                      # no error

    def test_finish_keeps_it_for_the_minimum_time_then_closes(self):
        splash.show(self.root)
        with mock.patch.object(splash, "MIN_SECONDS", 0.15):
            splash._S["t0"] = time.monotonic()
            splash.finish(self.root)
            self.assertTrue(splash.is_open())
            for _ in range(40):
                self.root.update()
                time.sleep(0.01)
            self.assertFalse(splash.is_open())
        self.assertEqual(self.root.state(), "normal")

    def test_finish_without_a_splash_just_shows_the_window(self):
        splash.finish(self.root)
        self.assertEqual(self.root.state(), "normal")


class Stub:
    """What the About box needs from the Workspace."""

    def __init__(self, root):
        import themes
        self.themes = themes.ThemeManager(root)
        self.palette = self.themes.apply("Light")
        self.font_family = "TkDefaultFont"


class TestAboutBox(TempAssets):
    def setUp(self):
        super().setUp()
        self.root = tk_root()
        if self.root is None:
            self.skipTest("no display")
        self.addCleanup(self.root.destroy)

    @unittest.skipUnless(HAVE_PIL, "Pillow not installed")
    def test_picture_is_a_small_version_of_the_supplied_one(self):
        make_picture(self.dir, size=(1600, 900))
        img = about_ui.small_picture(self.root)
        self.assertEqual(max(img.width(), img.height()),
                         about_ui.PICTURE_SIDE)
        self.assertAlmostEqual(img.width() / img.height(), 1600 / 900,
                               delta=0.02)

    def test_no_picture_no_error(self):
        self.assertIsNone(about_ui.small_picture(self.root))
        dlg = about_ui.AboutDialog(self.root, Stub(self.root))
        self.addCleanup(dlg.destroy)
        self.assertIsNone(dlg.picture)

    def test_link_opens_the_project_page(self):
        dlg = about_ui.AboutDialog(self.root, Stub(self.root))
        self.addCleanup(dlg.destroy)
        self.assertEqual(dlg.link.cget("text"), appinfo.GITHUB_URL)
        self.assertTrue(dlg.link.bind("<Button-1>"))          # clickable
        self.assertTrue(dlg.link.bind("<Return>"))            # and by keyboard
        with mock.patch.object(about_ui.webbrowser, "open",
                               return_value=True) as opened:
            self.assertTrue(about_ui.open_link())
        opened.assert_called_once_with(appinfo.GITHUB_URL)

    def test_open_link_survives_a_failing_browser(self):
        with mock.patch.object(about_ui.webbrowser, "open",
                               side_effect=RuntimeError):
            self.assertFalse(about_ui.open_link())

    def test_copy_puts_the_version_report_on_the_clipboard(self):
        dlg = about_ui.AboutDialog(self.root, Stub(self.root))
        self.addCleanup(dlg.destroy)
        dlg.copy_info()
        self.assertEqual(dlg.clipboard_get(), appinfo.version_report())


if __name__ == "__main__":
    unittest.main()
