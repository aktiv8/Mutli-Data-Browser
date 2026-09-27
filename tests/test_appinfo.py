"""Methods description templates loaded from assets/method_templates.

Run:  python -m unittest discover tests
"""

import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import appinfo  # noqa: E402


class TestMethodTemplates(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def touch(self, name, text="some text"):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_only_txt_files_are_listed_sorted_by_name(self):
        self.touch("Kratos Axis Ultra or Supra.txt")
        self.touch("Thermo K-Alpha or Nexsa.txt")
        self.touch("notes.md")
        self.touch("README.txt")                  # the folder's own blurb
        os.makedirs(os.path.join(self.dir, "a folder.txt"))
        got = appinfo.method_templates(self.dir)
        self.assertEqual([n for n, _p in got],
                         ["Kratos Axis Ultra or Supra.txt",
                          "Thermo K-Alpha or Nexsa.txt"])

    def test_a_missing_folder_is_an_empty_list(self):
        self.assertEqual(
            appinfo.method_templates(os.path.join(self.dir, "nope")), [])

    def test_template_dir_points_at_assets_method_templates(self):
        self.assertTrue(appinfo.template_dir().endswith(
            os.path.join("assets", "method_templates")))

    def test_the_seed_templates_are_present_and_readable(self):
        got = dict(appinfo.method_templates())
        self.assertIn("Thermo K-Alpha or Nexsa.txt", got)
        self.assertIn("Kratos Axis Ultra or Supra.txt", got)
        for name, path in got.items():
            with open(path, "r", encoding="utf-8") as f:
                self.assertTrue(f.read().strip())


if __name__ == "__main__":
    unittest.main()
