"""The application name: spelt one way, everywhere, and the old name gone.

Run:  python -m unittest discover tests
"""

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import appinfo  # noqa: E402

OLD = "ESCApe Explorer"
SUFFIXES = (".py", ".js", ".html", ".css", ".md", ".bat", ".sh", ".txt")
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules"}


def source_files():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(SUFFIXES):
                yield os.path.join(base, f)


class TestAppName(unittest.TestCase):
    def test_name_and_capitalisation(self):
        self.assertEqual(appinfo.NAME, "eXPoSe SpectraDeck")

    def test_the_old_name_is_only_mentioned_as_the_former_name(self):
        this = os.path.abspath(__file__)
        for path in source_files():
            if os.path.abspath(path) == this:
                continue
            with open(path, encoding="utf-8", errors="replace") as fh:
                for n, line in enumerate(fh, 1):
                    if OLD.lower() in line.lower():
                        self.assertRegex(
                            line, r"(?i)former|formerly|old name|previous",
                            f"{os.path.relpath(path, ROOT)}:{n} still uses "
                            f"the old name: {line.strip()}")

    def test_escape_means_the_kratos_software_or_the_former_name(self):
        """"ESCApe" names the Kratos acquisition software (its .experiment
        files) or is the app's former name; a title or label written for data
        of any format must not carry it."""
        word = re.compile(r"ESCApe(?! Explorer)")
        allowed = re.compile(r"Kratos|\.experiment|EscapeParser|former|old name"
                             r"|previous|escape_explorer", re.I)
        this = os.path.abspath(__file__)
        for path in source_files():
            if os.path.abspath(path) == this:
                continue
            with open(path, encoding="utf-8", errors="replace") as fh:
                for n, line in enumerate(fh, 1):
                    if word.search(line):
                        self.assertRegex(
                            line, allowed,
                            f"{os.path.relpath(path, ROOT)}:{n} uses ESCApe "
                            f"without naming the Kratos software: "
                            f"{line.strip()}")

    def test_only_a_kratos_experiment_names_escape_as_its_software(self):
        import readers.kratos_experiment as ke
        import readers.kratos_kal as kal
        import readers.scienta_txt as sc
        import readers.phi_spe as phi
        import readers.thermo_avg as th
        self.assertEqual(ke.EscapeParser.format_name,
                         "Kratos ESCApe (.experiment)")
        for mod in (kal, sc, phi, th):
            with open(mod.__file__, encoding="utf-8") as fh:
                src = fh.read()
            self.assertNotIn("ESCApe", src.replace("ESCAPE", ""), mod.__name__)

    def test_no_wrong_capitalisation_of_the_new_name(self):
        wrong = re.compile(r"(?i)expose\s*spectra\s*deck")
        for path in source_files():
            with open(path, encoding="utf-8", errors="replace") as fh:
                for n, line in enumerate(fh, 1):
                    for m in wrong.finditer(line):
                        self.assertEqual(
                            m.group(0), appinfo.NAME,
                            f"{os.path.relpath(path, ROOT)}:{n}: "
                            f"'{m.group(0)}'")

    def test_generated_files_carry_the_name(self):
        import workbook as wbk
        import handover
        import htmlbrowser
        self.assertEqual(handover.TOOL, appinfo.NAME)
        import inspect
        self.assertIn("appinfo.NAME", inspect.getsource(wbk.save))
        self.assertIn("appinfo.NAME", inspect.getsource(htmlbrowser))

    def test_entry_point_and_launcher_agree(self):
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "spectradeck.py")))
        self.assertFalse(os.path.exists(os.path.join(ROOT, "escape_explorer.py")))
        with open(os.path.join(ROOT, "launch.py"), encoding="utf-8") as fh:
            self.assertIn('"spectradeck.py"', fh.read())
        for name in ("run.bat", "run.sh"):
            with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
                self.assertIn("launch.py", fh.read())


if __name__ == "__main__":
    unittest.main()
