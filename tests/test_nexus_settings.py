"""Instrument settings for NeXus export: the settings model, their storage in
the annotations (and so the workbook), what the exporter writes from them, the
hand-over and the dialog (driven through its methods, no mouse).

Run:  python -m unittest discover tests
"""

import json
import os
import shutil
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import annotations  # noqa: E402
import nexus_export  # noqa: E402
import nexus_settings as ns  # noqa: E402

try:
    import h5py
    HAVE_H5PY = True
except Exception:
    HAVE_H5PY = False

FULL = {"source_type": "Fixed Tube X-ray", "dispersion_scheme": "hemispherical",
        "collection_scheme": "angular dispersive", "detector_type": "DLD",
        "amplifier_type": "MCP", "work_function_ev": 4.3,
        "energy_resolution_ev": 0.45, "affiliation": "University of X",
        "operator": "A. Person", "utc_offset_hours": 1.0,
        "energy_scan_mode": "fixed_analyzer_transmission"}


def text(ds):
    v = ds[()]
    return v.decode("utf-8") if isinstance(v, bytes) else str(v)


class TestSanitise(unittest.TestCase):
    def test_a_full_valid_dict_is_kept(self):
        self.assertEqual(ns.sanitise(FULL), FULL)

    def test_a_choice_must_be_an_nxmpes_name(self):
        s = ns.sanitise({"source_type": "Laser pointer",
                         "dispersion_scheme": "HEMISPHERICAL",
                         "detector_type": "dld"})
        self.assertNotIn("source_type", s)
        self.assertEqual(s["dispersion_scheme"], "hemispherical")
        self.assertEqual(s["detector_type"], "DLD")     # canonical spelling

    def test_numbers_must_be_positive_and_finite(self):
        s = ns.sanitise({"work_function_ev": "4,5", "energy_resolution_ev": 0,
                         "x": 1})
        self.assertEqual(s, {"work_function_ev": 4.5})
        for bad in (-1, "n/a", float("nan"), float("inf"), True, None):
            self.assertEqual(ns.sanitise({"work_function_ev": bad}), {})

    def test_a_utc_offset_may_be_zero_or_negative_but_must_be_a_real_zone(self):
        for ok in (0, "0", -5, "5,5", 14, -12, "+1"):
            self.assertIn("utc_offset_hours",
                          ns.sanitise({"utc_offset_hours": ok}), ok)
        self.assertEqual(ns.sanitise({"utc_offset_hours": 0}),
                         {"utc_offset_hours": 0.0})
        for bad in (15, -13, "", "x", None, True, float("nan")):
            self.assertEqual(ns.sanitise({"utc_offset_hours": bad}), {}, bad)

    def test_text_is_trimmed_and_blank_dropped(self):
        self.assertEqual(ns.sanitise({"affiliation": "  Uni  "}),
                         {"affiliation": "Uni"})
        self.assertEqual(ns.sanitise({"affiliation": "   "}), {})

    def test_junk_in_gives_nothing_out(self):
        for junk in (None, 3, "x", [1], {}):
            self.assertEqual(ns.sanitise(junk), {})
            self.assertTrue(ns.is_empty(junk))

    def test_describe_and_merge(self):
        self.assertEqual(ns.describe({}), "nothing set")
        self.assertIn("hemispherical", ns.describe(FULL))
        m = ns.merged({"detector_type": "DLD"},
                      {"detector_type": "ECMOS", "amplifier_type": "MCP"})
        self.assertEqual(m, {"detector_type": "DLD", "amplifier_type": "MCP"})

    def test_every_choice_has_options_and_keys_are_unique(self):
        self.assertEqual(len(set(ns.KEYS)), len(ns.KEYS))
        for key, _label, kind, choices in ns.FIELDS:
            self.assertEqual(bool(choices), kind == "choice", key)


class TestAnnotations(unittest.TestCase):
    def test_store_per_file_and_remove_when_empty(self):
        a = annotations.Annotations()
        self.assertTrue(a.is_empty())
        a.set_instrument("f1", FULL)
        self.assertFalse(a.is_empty())
        self.assertEqual(a.instrument_for("f1"), FULL)
        self.assertEqual(a.instrument_for("f2"), {})
        a.set_instrument("f1", {})
        self.assertEqual(a.instrument, {})
        self.assertTrue(a.is_empty())

    def test_round_trip_and_copy(self):
        a = annotations.Annotations()
        a.set_instrument("f1", FULL)
        b = annotations.Annotations.from_json(
            json.loads(json.dumps(a.to_json())))
        self.assertEqual(b.to_json(), a.to_json())
        self.assertEqual(b.instrument_for("f1"), FULL)
        c = a.copy()
        c.set_instrument("f1", {})
        self.assertEqual(a.instrument_for("f1"), FULL)

    def test_loading_is_tolerant(self):
        a = annotations.Annotations.from_json({"instrument": {
            "f1": {"source_type": "nonsense", "detector_type": "DLD"},
            "f2": {"source_type": "nonsense"}, "f3": "text", "f4": None}})
        self.assertEqual(a.instrument, {"f1": {"detector_type": "DLD"}})
        self.assertEqual(
            annotations.Annotations.from_json({"instrument": [1]}).instrument,
            {})

    def test_an_old_workbook_without_settings_loads(self):
        self.assertEqual(
            annotations.Annotations.from_json({"version": 1}).instrument, {})


def region():
    from readers import Region
    r = Region(name="C 1s", index=0, offset=0,
               energy=[290.0 - 0.1 * i for i in range(11)],
               counts=[10.0 + i for i in range(11)], decodable=True,
               sample="S", photon_energy=1486.71, pass_energy=20.0,
               dwell=0.1, step=0.1, anode="Al Kα", source="a.vms")
    r.extra["n_scans"] = 3
    r.extra["t_start"] = "2026-01-05 10:00:00"
    r.extra["analyser_mode"] = "Constant analyser energy (CAE)"
    return r


@unittest.skipUnless(HAVE_H5PY, "h5py not installed")
class TestExport(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, "x.nxs")

    def write(self, **kw):
        nexus_export.export_nexus([region()], self.path, **kw)
        return h5py.File(self.path)

    def test_the_user_settings_are_written_where_nxxps_wants_them(self):
        with self.write(settings=FULL) as f:
            e = f["S_C_1s"]
            self.assertEqual(text(e["instrument/source_probe/type"]),
                             "Fixed Tube X-ray")
            a = e["instrument/electronanalyzer"]
            self.assertEqual(text(a["energydispersion/scheme"]),
                             "hemispherical")
            self.assertEqual(text(a["collectioncolumn/scheme"]),
                             "angular dispersive")
            self.assertEqual(a["work_function"][()], 4.3)
            self.assertEqual(a["work_function"].attrs["units"], "eV")
            d = a["electron_detector"]
            self.assertEqual(d.attrs["NX_class"], "NXelectron_detector")
            self.assertEqual(text(d["detector_type"]), "DLD")
            self.assertEqual(text(d["amplifier_type"]), "MCP")
            r = e["instrument/energy_resolution"]
            self.assertEqual(r.attrs["NX_class"], "NXresolution")
            self.assertEqual(text(r["physical_quantity"]), "energy")
            self.assertEqual(r["resolution"][()], 0.45)
            self.assertEqual(text(e["user/name"]), "A. Person")
            self.assertEqual(text(e["user/affiliation"]), "University of X")
            self.assertEqual(text(a["energydispersion/energy_scan_mode"]),
                             "fixed_analyzer_transmission")
            self.assertEqual(text(e["start_time"]),
                             "2026-01-05T10:00:00+01:00")

    def test_an_affiliation_without_a_name_is_not_a_user(self):
        with self.write(settings={"affiliation": "Uni"}) as f:
            self.assertNotIn("user", f["S_C_1s"])
            doc = json.loads(text(f["S_C_1s/metadata/data"]))
            self.assertEqual(doc["entered_by_user"], {"affiliation": "Uni"})

    def test_the_users_utc_offset_only_fills_a_zone_the_reader_lacks(self):
        r = region()
        r.extra["t_start"] = "2026-01-05 10:00:00"
        self.assertEqual(nexus_export.start_time(r), "2026-01-05T10:00:00")
        self.assertEqual(nexus_export.start_time(r, 0.0),
                         "2026-01-05T10:00:00+00:00")
        self.assertEqual(nexus_export.start_time(r, -5.5),
                         "2026-01-05T10:00:00-05:30")
        r.extra["tz"] = "UTC"                  # the file itself says UTC
        self.assertEqual(nexus_export.start_time(r, 2.0),
                         "2026-01-05T10:00:00+00:00")

    def test_the_users_scan_mode_beats_the_recorded_one(self):
        with self.write(settings={
                "energy_scan_mode": "fixed_retarding_ratio"}) as f:
            self.assertEqual(
                text(f["S_C_1s/instrument/electronanalyzer/"
                       "energydispersion/energy_scan_mode"]),
                "fixed_retarding_ratio")

    def test_without_settings_none_of_it_is_written(self):
        with self.write() as f:
            e = f["S_C_1s"]
            self.assertNotIn("type", e["instrument/source_probe"])
            self.assertNotIn("scheme", e["instrument/electronanalyzer/"
                                         "energydispersion"])
            self.assertNotIn("scheme", e["instrument/electronanalyzer/"
                                         "collectioncolumn"])
            self.assertNotIn("electron_detector",
                             e["instrument/electronanalyzer"])
            self.assertNotIn("energy_resolution", e["instrument"])
            self.assertNotIn("user", e)

    def test_what_the_user_entered_beats_what_the_file_recorded(self):
        inst = {"Work function (eV)": "4.5", "Institution": "File Uni",
                "Operator": "DJM"}
        with self.write(instrument=inst,
                        settings={"work_function_ev": 4.1,
                                  "affiliation": "My Uni"}) as f:
            e = f["S_C_1s"]
            self.assertEqual(e["instrument/electronanalyzer/work_function"][()],
                             4.1)
            self.assertEqual(text(e["user/affiliation"]), "My Uni")
        with self.write(instrument=inst) as f:          # nothing entered
            e = f["S_C_1s"]
            self.assertEqual(e["instrument/electronanalyzer/work_function"][()],
                             4.5)
            self.assertEqual(text(e["user/affiliation"]), "File Uni")

    def test_invalid_settings_never_reach_the_file(self):
        with self.write(settings={"source_type": "Laser pointer",
                                  "detector_type": "DLD"}) as f:
            e = f["S_C_1s"]
            self.assertNotIn("type", e["instrument/source_probe"])
            self.assertEqual(
                text(e["instrument/electronanalyzer/electron_detector/"
                       "detector_type"]), "DLD")

    def test_the_metadata_note_says_these_were_entered_by_the_user(self):
        with self.write(settings=FULL) as f:
            doc = json.loads(text(f["S_C_1s/metadata/data"]))
            self.assertEqual(doc["entered_by_user"], FULL)
        with self.write() as f:
            doc = json.loads(text(f["S_C_1s/metadata/data"]))
            self.assertNotIn("entered_by_user", doc)


@unittest.skipUnless(HAVE_H5PY, "h5py not installed")
class TestHandover(unittest.TestCase):
    def test_the_hand_over_writes_each_files_own_settings(self):
        import handover
        from readers.base import SpectrumFile
        d = SpectrumFile()
        d.path = "a.vms"
        d.regions = [region()]
        d._finish()
        a = annotations.Annotations()
        a.set_instrument("fid1", {"source_type": "Fixed Tube X-ray"})
        d.annotations, d.file_id = a, "fid1"
        parts, notes = handover.spectra_parts([d], nexus=True)
        self.assertEqual(notes, [])
        nx = next(p for p in parts if p.arc.endswith(".nxs"))
        path = os.path.join(tempfile.mkdtemp(), "h.nxs")
        self.addCleanup(shutil.rmtree, os.path.dirname(path), True)
        with open(path, "wb") as fh:
            fh.write(nx.data)
        with h5py.File(path) as f:
            self.assertEqual(
                text(f["S_C_1s/instrument/source_probe/type"]),
                "Fixed Tube X-ray")


class TestDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tkinter as tk
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"no display: {exc}")
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        import instrument_ui
        self.ann = annotations.Annotations()
        self.items = [{"label": "a.vms", "fid": "A",
                       "recorded": {"Work function (eV)": "4.5"}},
                      {"label": "b.vms", "fid": "B", "recorded": {}}]
        self.calls = 0

        def set_(item, s):
            self.calls += 1
            self.ann.set_instrument(item["fid"], s)
        app = types.SimpleNamespace(
            root=self.root, themes=types.SimpleNamespace(
                recolor_tk=lambda w: None),
            palette={"bg": "#fff", "fg": "#000", "panel": "#eee",
                     "entry": "#fff", "select_bg": "#06c",
                     "select_fg": "#fff", "accent": "#06c"},
            instrument_files=lambda: self.items,
            instrument_get=lambda it: self.ann.instrument_for(it["fid"]),
            instrument_set=set_)
        self.dlg = instrument_ui.InstrumentDialog(self.root, app)
        self.addCleanup(self.dlg.destroy)

    def test_editing_a_field_stores_it_for_that_file(self):
        self.dlg.vars["source_type"].set("Fixed Tube X-ray")
        self.dlg.vars["work_function_ev"].set("4.31")
        self.dlg._commit()
        self.assertEqual(self.ann.instrument_for("A"),
                         {"source_type": "Fixed Tube X-ray",
                          "work_function_ev": 4.31})
        self.assertEqual(self.ann.instrument_for("B"), {})

    def test_an_unchanged_form_stores_nothing(self):
        self.dlg._commit()
        self.assertEqual(self.calls, 0)

    def test_the_hint_shows_what_the_file_recorded(self):
        self.assertIn("4.5", self.dlg.info.cget("text"))
        self.dlg.list.selection_clear(0, "end")
        self.dlg.list.selection_set(1)
        self.dlg._on_select()
        self.assertIn("none", self.dlg.info.cget("text"))

    def test_switching_files_shows_their_own_values(self):
        self.ann.set_instrument("B", {"detector_type": "DLD"})
        self.dlg.list.selection_clear(0, "end")
        self.dlg.list.selection_set(1)
        self.dlg._on_select()
        self.assertEqual(self.dlg.vars["detector_type"].get(), "DLD")
        self.assertEqual(self.dlg.vars["source_type"].get(),
                         "(not set)")

    def test_not_set_clears_a_choice(self):
        self.ann.set_instrument("A", {"detector_type": "DLD"})
        self.dlg._on_select()
        self.dlg.vars["detector_type"].set("(not set)")
        self.dlg._commit()
        self.assertEqual(self.ann.instrument_for("A"), {})

    def test_use_for_every_file_and_clear(self):
        import tkinter.messagebox as mb
        real = mb.showinfo
        mb.showinfo = lambda *a, **k: None
        self.addCleanup(setattr, mb, "showinfo", real)
        self.dlg.vars["affiliation"].set("Uni")
        self.dlg._all()
        self.assertEqual(self.ann.instrument_for("A"), {"affiliation": "Uni"})
        self.assertEqual(self.ann.instrument_for("B"), {"affiliation": "Uni"})
        self.dlg._clear()
        self.assertEqual(self.ann.instrument_for("A"), {})
        self.assertEqual(self.ann.instrument_for("B"), {"affiliation": "Uni"})
        self.assertEqual(self.dlg.vars["affiliation"].get(), "")


if __name__ == "__main__":
    unittest.main()
