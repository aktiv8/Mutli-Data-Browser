"""Optional: load every recognisable file under a folder of real instrument data.

    set XPS_CORPUS=C:\\path\\to\\your\\spectra        (Windows)
    export XPS_CORPUS=/path/to/your/spectra          (macOS / Linux)
    python -m unittest tests.test_corpus

Skipped when XPS_CORPUS is not set. Files that no reader recognises (readmes,
licences, ...) are ignored; recognised files must load, with a matching number
of points in every decodable region.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from readers import load_file, reader_for, UnsupportedFormat  # noqa: E402

CORPUS = os.environ.get("XPS_CORPUS", "")
EXTS = (".vms", ".vamas", ".avg", ".avx", ".vgd", ".spe", ".kal",
        ".experiment", ".txt")


@unittest.skipUnless(CORPUS and os.path.isdir(CORPUS), "XPS_CORPUS not set")
class TestCorpus(unittest.TestCase):
    def test_every_recognised_file_loads(self):
        loaded, failures = 0, []
        for folder, _dirs, files in os.walk(CORPUS):
            for name in files:
                if not name.lower().endswith(EXTS):
                    continue
                path = os.path.join(folder, name)
                try:
                    reader_for(path)
                except UnsupportedFormat:
                    continue
                try:
                    f = load_file(path)
                    self.assertTrue(f.regions, "no regions")
                    for r in f.regions:
                        if r.decodable:
                            self.assertEqual(r.n_points, len(r.energy))
                    loaded += 1
                except Exception as exc:            # noqa: BLE001
                    failures.append(f"{path}: {exc!r}")
        self.assertFalse(failures, "\n".join(failures[:20]))
        print(f"\ncorpus: {loaded} files loaded")


if __name__ == "__main__":
    unittest.main()
