"""DetailsDialog's methods-template picker (loads assets/method_templates).

Run:  python -m unittest discover tests
"""

import os
import shutil
import sys
import tempfile
import tkinter as tk
import unittest
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import appinfo  # noqa: E402
import workbook_ui  # noqa: E402


class TestDetailsDialogTemplates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError:
            raise unittest.SkipTest("no display")
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self._orig_template_dir = appinfo.template_dir
        self.addCleanup(setattr, appinfo, "template_dir",
                        self._orig_template_dir)

    def fake_app(self):
        return SimpleNamespace(
            root=self.root,
            palette={"bg": "#fff", "fg": "#000", "panel": "#eee",
                     "entry": "#fff"},
            themes=SimpleNamespace(recolor_tk=lambda w: None),
            methods_generated=lambda: "GENERATED TEXT")

    def dialog(self, details=None):
        dlg = workbook_ui.DetailsDialog(
            self.root, self.fake_app(), details or {}, "",
            lambda details, logo: None)
        self.addCleanup(dlg.destroy)
        return dlg

    def test_choosing_a_template_replaces_the_methods_box(self):
        path = os.path.join(self.dir, "Thermo K-Alpha or Nexsa.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("Custom instrument description.")
        appinfo.template_dir = lambda: self.dir
        dlg = self.dialog({"methods": "old text"})
        dlg._load_template(path)
        self.assertEqual(dlg.methods.get("1.0", "end").strip(),
                         "Custom instrument description.")
        menu = dlg._template_menu
        labels = [menu.entrycget(i, "label")
                  for i in range(menu.index("end") + 1)]
        self.assertEqual(labels, ["Thermo K-Alpha or Nexsa"])

    def test_an_empty_template_folder_gives_one_disabled_entry(self):
        appinfo.template_dir = lambda: os.path.join(self.dir, "nope")
        dlg = self.dialog()
        menu = dlg._template_menu
        self.assertEqual(menu.index("end"), 0)
        self.assertEqual(str(menu.entrycget(0, "state")), "disabled")

    def test_a_template_is_stored_as_an_explicit_override_on_ok(self):
        path = os.path.join(self.dir, "House style.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("House style methods text.")
        appinfo.template_dir = lambda: self.dir
        seen = {}
        dlg = workbook_ui.DetailsDialog(
            self.root, self.fake_app(), {"methods": ""}, "",
            lambda details, logo: seen.update(details=details, logo=logo))
        dlg._load_template(path)
        dlg._ok()                             # destroys dlg itself
        self.assertEqual(seen["details"]["methods"],
                         "House style methods text.")


if __name__ == "__main__":
    unittest.main()
