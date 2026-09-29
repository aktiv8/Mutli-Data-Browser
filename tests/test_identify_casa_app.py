"""Labelling several ticked Survey spectra from their own CasaXPS regions
shows every one's labels on the shared panel, not just the first (needs a
display and matplotlib/Tk; skipped otherwise).

Run:  python -m unittest discover tests
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

try:
    import tkinter as tk
    import spectradeck as ee
    HAVE_MPL = ee.HAVE_MPL
except Exception:                                   # pragma: no cover
    tk, ee, HAVE_MPL = None, None, False

import casafit  # noqa: E402
from readers import Region, SpectrumFile  # noqa: E402


def survey_region(sample, region_name, be, hv=1486.6, n=41):
    e = [1200.0 - i * 1200.0 / (n - 1) for i in range(n)]
    c = [100.0] * n
    r = Region(name="Survey", index=0, offset=0, energy=e, counts=c,
              decodable=True, sample=sample, photon_energy=hv,
              source="a.vms", count_units="counts/s")
    ke = hv - be
    reg = casafit.FitRegion(name=region_name, background="none",
                            start_ke=ke - 5.0, end_ke=ke + 5.0)
    r.fit = casafit.Fit(regions=[reg], components=[])
    return r


def doc(path, regions):
    f = SpectrumFile()
    f.path = path
    f.format_name = "Test"
    f.regions = regions
    f.instrument = {"Instrument": "Test Spec"}
    f._finish()
    return f


@unittest.skipUnless(HAVE_MPL, "matplotlib / Tk not available")
class TestCasaLabelsAcrossMultipleSurveys(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError:
            raise unittest.SkipTest("no display")
        cls.root.withdraw()
        cls.docs = {
            "a.vms": doc("a.vms", [survey_region("Sample A", "C1s", 284.8)]),
            "b.vms": doc("b.vms", [survey_region("Sample B", "O1s", 532.0)]),
        }
        cls._load = ee.load_file
        ee.load_file = lambda p: cls.docs[os.path.basename(p)]
        cls.ws = ee.Workspace(cls.root)

    @classmethod
    def tearDownClass(cls):
        ee.load_file = cls._load
        cls.root.destroy()

    def setUp(self):
        ws = self.ws
        for d in list(ws.docs):
            ws.docs.remove(d)
        ws.file_ids.clear()
        ws.region_parser.clear()
        ws.group_var.set("Element name")
        ws.view_var.set("Stack")
        ws.norm_var.set("None")
        ws.z_var.set("Auto")
        ws.scale_var.set("Binding")
        ws.panels_var.set("Auto")
        ws.traces_var.set("All")
        ws.panel_views = {}
        ws.trace_start = 0
        ws.ann.markers.clear()
        for p in self.docs:
            ws._add_file(p, file_id=p[:-4], refresh=False)
        ws._finish_adding()
        ws.checked = {id(r) for d in ws.docs for r in d.regions}

    def _rendered_markers(self):
        """[(be, label, kin[, tier]), ...] from every panel drawn."""
        captured = []
        orig = ee.draw_stack

        def spy(*args, **kwargs):
            captured.append(kwargs.get("markers", ()))
            return orig(*args, **kwargs)

        ee.draw_stack = spy
        try:
            self.ws._render()
        finally:
            ee.draw_stack = orig
        return [m for marks in captured for m in marks]

    def test_both_surveys_share_one_panel_by_default_grouping(self):
        keys = [k for k, _ in self.ws._groups()]
        self.assertEqual(len(keys), 1, keys)

    def test_labels_from_every_ticked_survey_are_drawn(self):
        ws = self.ws
        for d in ws.docs:
            for r in d.regions:
                n = ws.identify_from_casa(r)
                self.assertEqual(n, 1)

        marks = self._rendered_markers()
        labels = {m[1] for m in marks}
        self.assertIn("C 1s", labels)
        self.assertIn("O 1s", labels)

    def test_only_labelling_one_region_leaves_the_other_unlabelled(self):
        ws = self.ws
        a_region = self.docs["a.vms"].regions[0]
        ws.identify_from_casa(a_region)

        marks = self._rendered_markers()
        labels = {m[1] for m in marks}
        self.assertIn("C 1s", labels)
        self.assertNotIn("O 1s", labels)

    def test_predefined_regions_ignores_tree_selection(self):
        """predefined_regions() must return every ticked CasaXPS-region
        spectrum even when only one row is highlighted in the tree (the
        real bug: the Identify dialog used to be handed sel_regions-scoped
        regions, so its 'Label from CasaXPS regions' button only ever saw
        one row's worth of spectra -- see test_identify_dialog.py for the
        dialog-level regression test against workbook_ui._casa_label)."""
        ws = self.ws
        a_region = self.docs["a.vms"].regions[0]
        ws.sel_regions = [a_region]

        found = ws.predefined_regions()

        self.assertEqual(len(found), 2, found)


if __name__ == "__main__":
    unittest.main()
