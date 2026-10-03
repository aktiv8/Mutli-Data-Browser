"""Finding and starting CasaXPS / KherveFitting, and their icons
(externalapps.py; no window needed).

Run:  python -m unittest discover tests
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import externalapps as ea  # noqa: E402


def touch(path, mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"MZ")
    if mtime:
        os.utime(path, (mtime, mtime))
    return path


class TestFind(unittest.TestCase):
    def setUp(self):
        ea.forget()
        self.addCleanup(ea.forget)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name

    def test_unzipped_folder_with_no_registry_entry_is_found(self):
        """CasaXPS is a plain folder: only a look at the usual roots finds it."""
        exe = touch(os.path.join(self.tmp, "Software", "CasaXPS 64bit",
                                 "CasaXPS.exe"))
        got = ea.find("casaxps", {}, roots=[os.path.join(self.tmp, "Software")])
        self.assertEqual(got, exe)

    def test_users_own_choice_wins(self):
        mine = touch(os.path.join(self.tmp, "mine", "CasaXPS.exe"))
        other = touch(os.path.join(self.tmp, "Software", "CasaXPS", "CasaXPS.exe"))
        cfg = {"external_apps": {"casaxps": mine}}
        self.assertEqual(
            ea.find("casaxps", cfg, roots=[os.path.dirname(os.path.dirname(other))]),
            mine)

    def test_a_saved_location_that_is_gone_is_ignored(self):
        cfg = {"external_apps": {"casaxps": os.path.join(self.tmp, "gone.exe")}}
        self.assertIsNone(ea.find("casaxps", cfg, roots=[self.tmp]))

    def test_the_plain_exe_beats_a_versioned_copy(self):
        base = os.path.join(self.tmp, "Software", "KherveFitting")
        plain = touch(os.path.join(base, "KherveFitting.exe"), 1000)
        touch(os.path.join(base, "KherveFitting_1.80", "KherveFitting_1.80.exe"),
              2000)
        self.assertEqual(ea.find("khervefitting", {}, roots=[os.path.dirname(base)]),
                         plain)

    def test_newest_versioned_exe_when_there_is_no_plain_one(self):
        base = os.path.join(self.tmp, "Software", "KherveFitting")
        touch(os.path.join(base, "KherveFitting_1.65", "KherveFitting_1.65.exe"),
              1000)
        new = touch(os.path.join(base, "KherveFitting_1.80",
                                 "KherveFitting_1.80.exe"), 3000)
        touch(os.path.join(base, "KherveFitting_1.80", "unins000.exe"), 5000)
        self.assertEqual(ea.find("khervefitting", {}, roots=[os.path.dirname(base)]),
                         new)

    def test_nothing_installed_gives_none(self):
        self.assertIsNone(ea.find("casaxps", {}, roots=[self.tmp]))

    def test_the_real_machine_search_does_not_raise(self):
        for key in ea.APPS:
            ea.forget()
            got = ea.find(key, {})
            self.assertTrue(got is None or os.path.isfile(got), got)


class TestLaunch(unittest.TestCase):
    def test_starts_the_program_detached_in_its_own_folder(self):
        with mock.patch.object(ea.subprocess, "Popen") as popen:
            self.assertEqual(ea.launch(os.path.join("x", "CasaXPS.exe")), "")
        args, kwargs = popen.call_args
        self.assertEqual(args[0], [os.path.join("x", "CasaXPS.exe")])
        self.assertEqual(kwargs["cwd"], "x")

    def test_a_failure_is_a_message_not_an_exception(self):
        with mock.patch.object(ea.subprocess, "Popen",
                               side_effect=OSError("no such file")):
            self.assertIn("no such file", ea.launch("nope.exe"))


@unittest.skipUnless(ea.IS_WINDOWS, "icons are read from Windows executables")
class TestIcon(unittest.TestCase):
    def test_missing_file_gives_none(self):
        self.assertIsNone(ea.icon_image(os.path.join("no", "such.exe")))

    def test_an_exe_gives_a_32_pixel_rgba_icon_and_caches_it(self):
        with tempfile.TemporaryDirectory() as cache:
            img = ea.icon_image(sys.executable, cache_dir=cache)
            if img is None:
                self.skipTest("this interpreter has no icon")
            self.assertEqual(img.size, (32, 32))
            self.assertEqual(img.mode, "RGBA")
            self.assertTrue(img.getchannel("A").getbbox())
            self.assertEqual(len(os.listdir(cache)), 1)
            again = ea.icon_image(sys.executable, cache_dir=cache)
            self.assertEqual(again.tobytes(), img.tobytes())


try:
    import tkinter as tk
    import spectradeck as ee
    HAVE_APP = ee.HAVE_MPL
except Exception:                                   # pragma: no cover
    tk, ee, HAVE_APP = None, None, False


@unittest.skipUnless(HAVE_APP, "matplotlib / Tk not available")
class TestLauncherButtons(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import matplotlib
        cls._rc = matplotlib.rcParams.copy()
        try:
            cls.root = tk.Tk()
        except tk.TclError:
            raise unittest.SkipTest("no display")
        cls.root.withdraw()
        cls.ws = ee.Workspace(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        import matplotlib
        matplotlib.rcParams.update(cls._rc)

    def test_a_button_only_for_a_program_that_was_found(self):
        ws = self.ws
        found = {"casaxps": __file__, "khervefitting": None}
        with mock.patch.object(ws, "external_path", side_effect=found.get):
            ws.ribbon.refresh_launchers()
        self.assertEqual(len(ws.ribbon._launchers), 1)
        with mock.patch.object(ws, "external_path", return_value=None):
            ws.ribbon.refresh_launchers()
        self.assertEqual(ws.ribbon._launchers, [])

    def test_clicking_launches_the_found_program(self):
        ws = self.ws
        with mock.patch.object(ws, "external_path", return_value="C:/x/a.exe"), \
                mock.patch.object(ea, "launch", return_value="") as launch:
            ws.launch_external("casaxps")
        launch.assert_called_once_with("C:/x/a.exe")

    def test_drawn_stand_in_icons_when_the_exe_has_no_icon(self):
        ws = self.ws
        with mock.patch.object(ws, "external_path", return_value=__file__), \
                mock.patch.object(ea, "icon_image", return_value=None):
            ws.ribbon.refresh_launchers()
        try:
            self.assertEqual(len(ws.ribbon._launchers), 2)
            self.assertTrue(all(not own for _b, own in ws.ribbon._launchers))
        finally:
            ws.ribbon.refresh_launchers()

    def test_tools_menu_has_open_and_locate_for_both(self):
        import inspect
        src = inspect.getsource(ee.Workspace._build_menu)
        self.assertIn("launch_external", src)
        self.assertIn("locate_external", src)


if __name__ == "__main__":
    unittest.main()
