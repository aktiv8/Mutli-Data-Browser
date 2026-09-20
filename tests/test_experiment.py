"""The Avantage experiment session: ``.VGX`` parsing and a folder of scans
opened as one experiment. Fixtures are built here (a tiny OLE2 writer for the
``.VGX``, synthetic ``.avg`` dumps for the data), so no instrument files are
needed."""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import olewriter  # noqa: E402
from test_thermo_kinds import dump, snapmap_text  # noqa: E402
import readers  # noqa: E402
from readers import thermo_vgx  # noqa: E402
from readers.thermo_experiment import (find_vgx, data_files,  # noqa: E402
                                       looks_like_experiment, LoadCancelled)

cs, ct = olewriter.cstring, olewriter.contents


def make_vgx():
    """Experiment 'Trial': one Multi Point group of configuration
    'X-Ray1 200um - FG  ON' holding Sample B (run first) and Sample A."""
    step = lambda name: ct("Standard", "", "", name, "")            # noqa: E731
    return olewriter.build({
        "Contents": ct("X-Ray1 400um - FG OFF", "Gun Shutdown", "C:\\Avantage",
                       "20260824", "Project X", "Standard platter", "Trial",
                       ""),
        "Embedding 10": {
            "Contents": ct("Multi Point", "B #002", "A #003",
                           "X-Ray1 200um - FG  ON", ""),
            "Embedding 1": {                       # Sample B: survey then C 1s
                "Contents": ct("XPS Survey", "C1s Scan", "Sample B", "",
                               "Pt #001a", "Standard", ""),
                "Embedding 2": {"Contents": step("XPS Survey")},
                "Embedding 3": {"Contents": step("C1s Scan")}},
            "Embedding 2": {                       # Sample A: C 1s then O 1s
                "Contents": ct("C1s Scan", "O1s Scan", "Sample A", "", "Standard",
                               ""),
                "Embedding 4": {"Contents": step("C1s Scan")},
                "Embedding 5": {"Contents": step("O1s Scan")}}},
        "Embedding 11": {"Contents": ct("Gun Shutdown", "")}})


def spectrum(title, ne=6, base=0):
    axes = [(1188.0, 0.5, ne, "ENERGY", "LINEAR", "E", "eV", "Energy")]
    return dump(title, axes, [(0, ne - 1, 1)],
                [((), [], [base + c for c in range(ne)])])


def two_points(title, ne=4):
    """One scan over two analysis points (a POSITION axis)."""
    axes = [(1188.0, 0.5, ne, "ENERGY", "LINEAR", "E", "eV", "Energy"),
            (1.0, 1.0, 2, "POSITION", "LINEAR", "Pos", "", "Position"),
            (5000.0, 0.0, 2, "X", "NON-LINEAR", "X", "\xb5m", "X"),
            (6000.0, 0.0, 2, "Y", "NON-LINEAR", "Y", "\xb5m", "Y")]
    blocks = []
    for k, (label, x, y) in enumerate([("Pt #001a", 5000.0, 6000.0),
                                       ("Pt #001b", 7000.0, 6500.0)]):
        labels = ["$AXISVALUE= DATAXIS=1 SPACEAXIS=1 LABEL='Position' "
                  "POINT=%d VALUE='%s';" % (k, label),
                  "$AXISVALUE= DATAXIS=1 SPACEAXIS=2 LABEL='X' POINT=%d "
                  "VALUE=%f;" % (k, x),
                  "$AXISVALUE= DATAXIS=1 SPACEAXIS=3 LABEL='Y' POINT=%d "
                  "VALUE=%f;" % (k, y)]
        blocks.append(((k,), labels, [10.0 * k + c for c in range(ne)]))
    return dump(title, axes, [(0, ne - 1, 1), (0, 1, 3)], blocks)


def camera(title, w=4, h=2):
    axes = [(0.0, 4.5, w, "X", "LINEAR", "X", "\xb5m", "X"),
            (0.0, 4.0, h, "Y", "LINEAR", "Y", "\xb5m", "Y")]
    blocks = [((y,), [], [65536 * y + 256 * x for x in range(w)])
              for y in range(h)]
    return dump(title, axes, [(0, w - 1, 1), (0, h - 1, 1)], blocks,
                vtype=13, vlabel="RGB")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "Trial")
        os.makedirs(self.root)

    def put(self, rel, data):
        p = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        mode = "wb" if isinstance(data, bytes) else "w"
        with open(p, mode, **({} if mode == "wb" else
                              {"encoding": "latin-1", "newline": ""})) as fh:
            fh.write(data)
        return p

    def build(self, vgx=True):
        cfg = "X-Ray1 200um - FG  ON"
        if vgx:
            self.put("Trial.VGX", make_vgx())
        self.put(f"{cfg}/Sample A/O1s Scan.avg", spectrum("O1s Scan", base=50))
        self.put(f"{cfg}/Sample A/C1s Scan.avg", spectrum("C1s Scan", base=10))
        self.put(f"{cfg}/Sample B/C1s Scan.avg", spectrum("C1s Scan", base=30))
        self.put(f"{cfg}/Sample B/XPS Survey.avg", spectrum("XPS Survey"))
        return cfg


class TestVgx(unittest.TestCase):
    def test_strings_follow_the_mfc_layout(self):
        raw = ct("Point", "", "X-Ray1 200um - FG  ON")
        self.assertEqual(thermo_vgx.strings_of(raw),
                         ["Point", "", "X-Ray1 200um - FG  ON"])
        long = "x" * 300
        self.assertEqual(thermo_vgx.strings_of(ct(long)), [long])
        self.assertEqual(thermo_vgx.strings_of(b"nothing here"), [])

    def test_the_run_tree_and_experiment_identity(self):
        t = thermo_vgx.parse(make_vgx())
        self.assertEqual((t.experiment, t.project, t.platter, t.date_folder),
                         ("Trial", "Project X", "Standard platter", "20260824"))
        self.assertEqual(t.data_root, "C:\\Avantage")
        self.assertEqual(t.setups, ["X-Ray1 400um - FG OFF"])
        (g,) = t.groups                       # "Gun Shutdown" has no children
        self.assertEqual(g.name, "X-Ray1 200um - FG  ON")
        self.assertIs(t.group_for("X-Ray1 200um - FG  ON"), g)
        self.assertIsNone(t.group_for("nope"))
        self.assertEqual([thermo_vgx.step_names(n) for n in g.children],
                         [["XPS Survey", "C1s Scan"], ["C1s Scan", "O1s Scan"]])
        self.assertIn("Sample B", g.children[0].strings)

    def test_sniff_needs_ole_and_the_extension(self):
        head = make_vgx()[:4096]
        self.assertTrue(thermo_vgx.sniff(head, ".vgx"))
        self.assertFalse(thermo_vgx.sniff(head, ".vgd"))
        self.assertFalse(thermo_vgx.sniff(b"plain text", ".vgx"))


class TestSession(Base):
    def test_a_folder_opens_as_one_experiment_in_run_order(self):
        self.build()
        f = readers.load_file(self.root)
        self.assertEqual(f.format_name, "Thermo Avantage experiment")
        self.assertEqual(f.experiment["name"], "Trial")
        self.assertEqual(f.instrument["Project"], "Project X")
        # the VGX says Sample B was run first, and its scans in run order
        self.assertEqual([(r.sample, r.name) for r in f.regions],
                         [("Sample B", "Survey"), ("Sample B", "C 1s"),
                          ("Sample A", "C 1s"), ("Sample A", "O 1s")])
        self.assertEqual([r.extra["scan"] for r in f.regions],
                         ["XPS Survey", "C1s Scan", "C1s Scan", "O1s Scan"])
        self.assertEqual([r.index for r in f.regions], [0, 1, 2, 3])
        self.assertTrue(all(r.source.endswith(".avg") for r in f.regions))

    def test_the_vgx_file_itself_opens_the_same_session(self):
        self.build()
        a = readers.load_file(self.root)
        b = readers.load_file(os.path.join(self.root, "Trial.VGX"))
        self.assertEqual([(r.sample, r.name) for r in a.regions],
                         [(r.sample, r.name) for r in b.regions])
        self.assertIs(readers.reader_for(os.path.join(self.root, "Trial.VGX")),
                      readers.ThermoExperiment)

    def test_without_a_vgx_the_folder_layout_is_enough(self):
        self.build(vgx=False)
        f = readers.load_file(self.root)
        self.assertEqual(f.experiment["name"], "Trial")
        self.assertEqual({r.sample for r in f.regions}, {"Sample A", "Sample B"})
        self.assertEqual(f.regions[0].sample, "Sample A")    # alphabetical

    def test_a_single_sample_folder_finds_its_experiment_above(self):
        cfg = self.build()
        sub = os.path.join(self.root, cfg, "Sample A")
        self.assertEqual(find_vgx(sub), os.path.join(self.root, "Trial.VGX"))
        f = readers.load_file(sub)
        self.assertEqual({r.sample for r in f.regions}, {"Sample A"})
        self.assertEqual(f.experiment["name"], "Trial")

    def test_vgd_wins_over_its_avg_twin(self):
        cfg = self.build()
        self.put(f"{cfg}/Sample A/C1s Scan.vgd", b"not really a vgd")
        files = [os.path.basename(p) for p in data_files(self.root)]
        self.assertIn("C1s Scan.vgd", files)
        self.assertEqual(files.count("C1s Scan.avg"), 1)     # Sample B's only

    def test_many_points_and_scans_line_up(self):
        cfg = self.build()
        self.put(f"{cfg}/Sample B/C1s Scan.avg", two_points("C1s Scan"))
        f = readers.load_file(self.root)
        b = [r for r in f.regions if r.extra["group"] == "Sample B"
             and r.name == "C 1s"]
        self.assertEqual([r.sample for r in b],
                         ["Sample B Pt #001a", "Sample B Pt #001b"])
        self.assertEqual(f.sample_positions()["Sample B Pt #001b"], (7.0, 6.5))
        kinds = [(label, samples) for label, samples in f.groups]
        self.assertEqual(kinds[0][0], "Sample B")
        self.assertIn("Sample B Pt #001a", kinds[0][1])

    def test_camera_images_are_attached_to_their_point(self):
        cfg = self.build()
        self.put(f"{cfg}/Sample A/Sample A_Pt #001a  (10-51-15 24-08-2026).avg",
                 camera("x"))
        self.put(f"{cfg}/Sample A/Sample A_Pt #001a  (14-32-13 24-08-2026).avg",
                 camera("x"))
        f = readers.load_file(self.root)
        self.assertEqual(len(f.images), 2)
        first, second = f.images
        self.assertEqual(first.sample, "Sample A Pt #001a")
        self.assertEqual(first.name, "Sample A Pt #001a  10:51")   # local stamp
        self.assertEqual(second.name, "Sample A Pt #001a  14:32")
        self.assertTrue(f.extract_jpeg(first).startswith(b"\x89PNG"))
        self.assertEqual(first.calib["width"], 4)
        kinds = [n.type_name for n in f.tree.children]
        self.assertEqual(kinds[-1], "HolderSnapshotFolder")

    def test_snapmaps_come_in_with_their_pixels(self):
        cfg = self.build()
        self.put(f"{cfg}/Sample A/C1s SnapMap.avg", snapmap_text())
        f = readers.load_file(self.root)
        (m,) = [r for r in f.regions if "cube" in r.extra]
        self.assertEqual(m.sample, "Sample A")
        cube = m.extra["cube"]
        self.assertEqual((cube.nx, cube.ny), (3, 2))
        tree_labels = [c.label for s in f.tree.children if s.label == "Sample A"
                       for c in s.children]
        self.assertIn("C 1s  ·  C1s Scan", tree_labels)     # same core level twice
        self.assertIn("C 1s  ·  C1s SnapMap", tree_labels)

    def test_bad_and_empty_files_are_reported_not_fatal(self):
        cfg = self.build()
        self.put(f"{cfg}/Sample A/Broken.vgd", b"\xd0\xcf\x11\xe0 truncated")
        self.put(f"{cfg}/Sample A/AutoPos.avg",
                 "$FORMAT=4\n$DATAAXES=0,#empty#\n")
        f = readers.load_file(self.root)
        self.assertEqual(len(f.regions), 4)
        self.assertEqual([p.split(os.sep)[-1] for p, _m in f.errors],
                         ["Broken.vgd"])
        self.assertTrue(any("could not be read" in w for w in f.warnings))
        self.assertEqual([p.split(os.sep)[-1] for p, _m in f.skipped],
                         ["AutoPos.avg"])

    def test_progress_and_cancel(self):
        self.build()
        seen = []
        readers.load_file(self.root, progress=lambda i, n, name:
                          seen.append((i, n)) and False)
        self.assertEqual(seen, [(0, 4), (1, 4), (2, 4), (3, 4)])
        with self.assertRaises(LoadCancelled):
            readers.load_file(self.root, progress=lambda i, n, name: i == 1)

    def test_members_list_what_a_workbook_must_keep(self):
        self.build()
        f = readers.load_file(self.root)
        rels = sorted(rel.replace(os.sep, "/") for _p, rel in f.members)
        self.assertEqual(rels[0], "Trial.VGX")
        self.assertEqual(len(rels), 5)
        self.assertGreater(f.summary["size"], 0)

    def test_what_counts_as_an_experiment_folder(self):
        cfg = self.build(vgx=False)
        # loose data next to nothing else: the old per-file open applies
        self.assertTrue(looks_like_experiment(self.root))          # only in subfolders
        self.assertFalse(looks_like_experiment(
            os.path.join(self.root, cfg, "Sample A")))             # files at top
        self.put("Trial.VGX", make_vgx())
        self.assertTrue(looks_like_experiment(
            os.path.join(self.root, cfg, "Sample A")))             # VGX above
        empty = os.path.join(self.tmp.name, "empty")
        os.makedirs(empty)
        self.assertFalse(looks_like_experiment(empty))
        with self.assertRaises(ValueError):
            readers.load_file(empty)


if __name__ == "__main__":
    unittest.main()
