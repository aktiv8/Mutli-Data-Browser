"""The hand-over ZIP: file naming, per-sample spectra, README, checksums and
safe writing.

Run:  python -m unittest discover tests
"""

import hashlib
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import handover as ho  # noqa: E402
import readers  # noqa: E402
from readers import Region, SpectrumFile  # noqa: E402


def region(name="C 1s", sample="S1", n=12, hi=292.0, lo=280.0, ok=True):
    e = [hi - i * (hi - lo) / (n - 1) for i in range(n)]
    return Region(name=name, index=0, offset=0, energy=e,
                  counts=[float(100 + i) for i in range(n)] if ok else None,
                  decodable=ok, sample=sample, photon_energy=1486.6,
                  pass_energy=20.0, dwell=0.1, step=(hi - lo) / (n - 1),
                  source="a.vms")


def doc(path, regions, instrument=None):
    f = SpectrumFile()
    f.path = path
    f.format_name = "Test"
    f.regions = regions
    f.instrument = instrument or {"Instrument": "Test Spec"}
    f._finish()
    return f


class TestNames(unittest.TestCase):
    def test_safe_stem(self):
        self.assertEqual(ho.safe_stem("MoS2 / study: 1"), "MoS2 _ study_ 1")
        evil = ho.safe_stem("../../evil")
        self.assertEqual(evil, ".._.._evil".strip(" ._"))     # cannot escape
        self.assertNotIn("/", evil)
        self.assertFalse(evil.startswith("."))
        self.assertNotIn("\\", ho.safe_stem("a\\b"))
        self.assertEqual(ho.safe_stem(""), "item")
        self.assertEqual(ho.safe_stem("  ...  ", "x"), "x")
        self.assertEqual(len(ho.safe_stem("a" * 200)), 60)
        self.assertEqual(ho.safe_stem("Cué foil"), "Cué foil")

    def test_unique_name_ignores_case(self):
        used = set()
        self.assertEqual(ho.unique_name("A", used), "A")
        self.assertEqual(ho.unique_name("a", used), "a_2")
        self.assertEqual(ho.unique_name("A", used), "A_3")
        self.assertEqual(ho.unique_name("B", used), "B")


class TestSpectra(unittest.TestCase):
    def test_one_vamas_and_csv_per_sample(self):
        d = doc("a.vms", [region("C 1s", "A"), region("O 1s", "A", lo=525,
                                                     hi=540),
                          region("C 1s", "B")])
        parts, notes = ho.spectra_parts([d])
        self.assertEqual(notes, [])
        arcs = [p.arc for p in parts]
        self.assertEqual(arcs, ["spectra/vamas/A.vms", "spectra/csv/A.csv",
                                "spectra/vamas/B.vms", "spectra/csv/B.csv"])
        self.assertTrue(parts[0].data.startswith(b"VAMAS Surface Chemical"))
        header = parts[1].data.decode().splitlines()[0]
        self.assertIn("C 1s", header)
        self.assertIn("O 1s", header)
        self.assertEqual(parts[0].desc, "VAMAS (ISO 14976), 2 spectra")
        self.assertIn("1 spectrum", parts[2].desc)

    def test_vamas_is_readable_again(self):
        d = doc("a.vms", [region("C 1s", "A")])
        parts, _ = ho.spectra_parts([d])
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "x.vms")
            with open(p, "wb") as fh:
                fh.write(parts[0].data)
            back = readers.load_file(p)
        self.assertEqual(len(back.regions), 1)
        self.assertEqual(back.regions[0].name, "C 1s")
        self.assertEqual(len(back.regions[0].counts), 12)

    def test_regions_without_data_are_skipped(self):
        d = doc("a.vms", [region("C 1s", "A"), region("X", "B", ok=False)])
        parts, notes = ho.spectra_parts([d])
        self.assertEqual([p.arc for p in parts],
                         ["spectra/vamas/A.vms", "spectra/csv/A.csv"])

    def test_display_hook_renames_and_shifts(self):
        import copy
        d = doc("a.vms", [region("C 1s", "raw")])

        def display(r):
            q = copy.copy(r)
            q.sample = "Renamed / sample"
            q.energy = [e + 1.0 for e in r.energy]
            return q
        parts, _ = ho.spectra_parts([d], display)
        self.assertEqual(parts[0].arc, "spectra/vamas/Renamed _ sample.vms")
        first = parts[1].data.decode().splitlines()[1].split(",")[0]
        self.assertEqual(float(first), 293.0)

    def test_several_files_are_told_apart(self):
        a = doc("a.vms", [region("C 1s", "S1")])
        b = doc("b.vms", [region("C 1s", "S1")])
        parts, _ = ho.spectra_parts([a, b])
        self.assertEqual([p.arc for p in parts if p.arc.endswith(".vms")],
                         ["spectra/vamas/a - S1.vms",
                          "spectra/vamas/b - S1.vms"])

    def test_unnamed_sample_and_name_clash(self):
        d = doc("a.vms", [region("C 1s", ""), region("C 1s", "s/1"),
                          region("C 1s", "s\\1")])
        parts, _ = ho.spectra_parts([d])
        arcs = [p.arc for p in parts if p.arc.endswith(".vms")]
        self.assertEqual(len(set(a.lower() for a in arcs)), 3)
        self.assertIn("spectra/vamas/unnamed sample.vms", arcs)

    def test_metadata_parts(self):
        d = doc("dir/a.vms", [region("C 1s", "A")])
        parts = ho.metadata_parts([d, d])
        self.assertEqual([p.arc for p in parts],
                         ["metadata/a.csv", "metadata/a_2.csv"])
        self.assertIn(b"C 1s", parts[0].data)

    def test_metadata_survives_the_alpha_of_al_k_alpha(self):
        # every Avantage file says "Al Kα": the Windows default codec
        # cannot write it, which used to drop the metadata CSV silently
        r = region()
        r.anode = "Al Kα (mono)"
        f = doc("/x/a.vgd", [r], {"Instrument": "K-Alpha+",
                                  "X-ray source": "Al Kα, monochromated"})
        (part,) = ho.metadata_parts([f])
        text = part.read().decode("utf-8-sig")
        self.assertIn("Al Kα (mono)", text)
        self.assertIn("Al Kα, monochromated", text)

    def test_figure_parts(self):
        figs = [{"name": "Depth / profile"}, {"name": "Depth / profile"}]
        parts = ho.figure_parts(figs, [[b"1"], [b"1", b"2"]])
        self.assertEqual([p.arc for p in parts], [
            "figures/figure_01_Depth _ profile.png",
            "figures/figure_02_Depth _ profile_p1.png",
            "figures/figure_02_Depth _ profile_p2.png"])
        self.assertIn("page 2 of 2", parts[2].desc)


class TestReadme(unittest.TestCase):
    def test_contents_and_details(self):
        parts = [ho.Part("report.pdf", "the report", data=b"x" * 2048),
                 ho.Part("spectra/csv/A.csv", "CSV", data=b"y")]
        text = ho.readme_text(
            {"title": "MoS2 study", "customer": "ACME", "reference": "J-42",
             "operator": "DM", "date": "2026-01-02", "summary": "It worked."},
            parts, [{"name": "a.vgd", "format": "Thermo", "regions": 3,
                     "size": 5000, "sha256": "ab" * 32}],
            "Shifted by +0.8 eV.")
        for want in ("MoS2 study", "Customer:  ACME", "J-42", "It worked.",
                     "Shifted by +0.8 eV.", "report.pdf", "2.0 KB",
                     "SHA256SUMS.txt", "a.vgd", "ab" * 32,
                     "not charge-corrected"):
            self.assertIn(want, text)

    def test_untitled_and_empty_details(self):
        text = ho.readme_text({}, [ho.Part("a", "b", data=b"")])
        self.assertTrue(text.startswith("Experiment hand-over"))
        self.assertNotIn("Customer", text)


class TestZip(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.out = os.path.join(self.dir, "out.zip")

    def test_layout_checksums_and_root_folder(self):
        src = os.path.join(self.dir, "wb.xpscontainer")
        with open(src, "wb") as fh:
            fh.write(b"workbook bytes")
        parts = [ho.Part("report.pdf", "r", data=b"%PDF"),
                 ho.Part("workbook/w.xpscontainer", "w", path=src)]
        names = ho.write_zip(self.out, "My / package", parts,
                             {"title": "T"}, [], "")
        with zipfile.ZipFile(self.out) as zf:
            self.assertEqual(zf.namelist(), names)
            self.assertEqual(
                names, ["My _ package/README.txt", "My _ package/report.pdf",
                        "My _ package/workbook/w.xpscontainer",
                        "My _ package/SHA256SUMS.txt"])
            sums = zf.read("My _ package/SHA256SUMS.txt").decode()
            for line in sums.splitlines():
                digest, arc = line.split("  ", 1)
                self.assertEqual(
                    hashlib.sha256(zf.read(f"My _ package/{arc}")).hexdigest(),
                    digest, arc)
            self.assertIn("workbook/w.xpscontainer", sums)
            self.assertNotIn("SHA256SUMS", sums)
            self.assertEqual(zf.read("My _ package/workbook/w.xpscontainer"),
                             b"workbook bytes")
            self.assertIn(b"T\n=", zf.read("My _ package/README.txt"))

    def test_nothing_to_write_is_an_error_and_leaves_no_file(self):
        with self.assertRaises(ho.HandoverError):
            ho.write_zip(self.out, "x", [])
        self.assertFalse(os.path.exists(self.out))

    def test_duplicate_names_are_refused(self):
        with self.assertRaises(ho.HandoverError):
            ho.write_zip(self.out, "x", [ho.Part("A.csv", data=b"1"),
                                         ho.Part("a.csv", data=b"2")])

    def test_failure_leaves_no_partial_or_temp_file(self):
        parts = [ho.Part("ok.txt", "ok", data=b"1"),
                 ho.Part("gone.bin", "x",
                         path=os.path.join(self.dir, "missing"))]
        with self.assertRaises(OSError):
            ho.write_zip(self.out, "x", parts)
        self.assertEqual(os.listdir(self.dir), [])

    def test_an_existing_package_is_replaced_atomically(self):
        with open(self.out, "wb") as fh:
            fh.write(b"old")
        ho.write_zip(self.out, "x", [ho.Part("a.txt", data=b"new")])
        with zipfile.ZipFile(self.out) as zf:
            self.assertEqual(zf.read("x/a.txt"), b"new")
        self.assertEqual(os.listdir(self.dir), ["out.zip"])


if __name__ == "__main__":
    unittest.main()
