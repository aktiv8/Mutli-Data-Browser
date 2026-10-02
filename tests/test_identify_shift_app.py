"""Identify peaks on a charge-corrected survey: the line tables hold calibrated
binding energies, so a click, the automatic labels and the nearby lines must
all be matched in the frame the spectrum is drawn in, and a marker must land
where it was clicked (needs a display and matplotlib/Tk; skipped otherwise).

Run:  python -m unittest discover tests
"""

import math
import os
import sys
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

try:
    import tkinter as tk
    import spectradeck as ee
    HAVE_MPL = ee.HAVE_MPL
except Exception:                                   # pragma: no cover
    tk, ee, HAVE_MPL = None, None, False

import workbook_ui  # noqa: E402
import xpslines  # noqa: E402
from readers import Region, SpectrumFile  # noqa: E402

HV = 1486.6
SHIFT = 2.5                      # the file's charge correction (eV)
O1S_SHOWN = 531.0                # where O 1s is drawn after the correction


def survey(sample, shift, peaks=((O1S_SHOWN, 9000.0),), n=1201):
    """A survey whose stored axis is *raw*: a peak drawn at ``be`` after the
    correction sits at ``be - shift`` in the file."""
    e = [1200.0 - i for i in range(n)]
    c = [100.0 + sum(h * math.exp(-0.5 * ((x + shift - be) / 0.8) ** 2)
                     for be, h in peaks) for x in e]
    r = Region(name="Survey", index=0, offset=0, energy=e, counts=c,
               decodable=True, sample=sample, photon_energy=HV,
               source=sample + ".vms", count_units="counts/s")
    r.calibration_shift = shift
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
class TestIdentifyOnAShiftedSurvey(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError:
            raise unittest.SkipTest("no display")
        cls.root.withdraw()
        cls.rc = dict(ee.matplotlib.rcParams)
        cls.docs = {
            "a.vms": doc("a.vms", [survey("A", 0.0, ((O1S_SHOWN, 9000.0),))]),
            "b.vms": doc("b.vms", [survey("B", SHIFT)]),
        }
        cls._load = ee.load_file
        ee.load_file = lambda p: cls.docs[os.path.basename(p)]
        cls.ws = ee.Workspace(cls.root)

    @classmethod
    def tearDownClass(cls):
        ee.load_file = cls._load
        ee.matplotlib.rcParams.update(cls.rc)
        cls.root.destroy()

    def setUp(self):
        ws = self.ws
        for d in list(ws.docs):
            ws.docs.remove(d)
        ws.file_ids.clear()
        ws.region_parser.clear()
        ws.group_var.set("Element, per sample")
        ws.view_var.set("Stack")
        ws.norm_var.set("None")
        ws.z_var.set("Auto")
        ws.scale_var.set("Binding")
        ws.panels_var.set("Auto")
        ws.traces_var.set("All")
        ws.panel_views = {}
        ws.trace_start = 0
        ws.ann.markers.clear()
        ws._disp_cache.clear()
        for v in ws.ident_vars.values():
            v.set(False)
        for p in self.docs:
            ws._add_file(p, file_id=p[:-4], refresh=False)
        ws._finish_adding()
        ws.checked = {id(r) for d in ws.docs for r in d.regions}
        self.a = self.docs["a.vms"].regions[0]
        self.b = self.docs["b.vms"].regions[0]

    def _rendered_markers(self):
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

    def test_the_correction_is_in_the_drawn_frame(self):
        d = self.ws._display(self.b)
        top = max(range(len(d.counts)), key=d.counts.__getitem__)
        self.assertAlmostEqual(d.energy[top], O1S_SHOWN, delta=0.6)

    def test_auto_label_finds_o1s_and_draws_it_where_the_peak_is(self):
        ws = self.ws
        self.assertGreaterEqual(ws.identify_auto(self.b), 1)
        stored = {m["label"]: m["be"] for m in ws.identify_markers(self.b)}
        self.assertIn("O 1s", stored)
        # stored as measured: the shown position minus the correction
        self.assertAlmostEqual(stored["O 1s"], O1S_SHOWN - SHIFT, delta=0.6)
        drawn = {m[1]: m[0] for m in self._rendered_markers()}
        self.assertAlmostEqual(drawn["O 1s"], O1S_SHOWN, delta=0.6)

    def test_a_click_on_the_shifted_peak_offers_o1s_and_marks_the_click(self):
        ws = self.ws
        dlg = workbook_ui.IdentifyDialog(ws.root, ws, [self.b])
        self.addCleanup(dlg.destroy)
        clicked = O1S_SHOWN + 0.2
        dlg._on_click(clicked)
        rows = [(k, e) for k, _d, e in dlg.rows if k == "line"]
        idx = next(i for i, (k, _d, e) in enumerate(dlg.rows)
                   if k == "line" and xpslines.label_of(e) == "O 1s")
        dlg.cand_list.selection_clear(0, "end")
        dlg.cand_list.selection_set(idx)
        dlg._add()
        self.assertTrue(rows)
        drawn = {m[1]: m[0] for m in self._rendered_markers()}
        self.assertAlmostEqual(drawn["O 1s"], clicked, places=6)

    def test_the_marker_uses_the_chosen_spectrums_own_shift(self):
        """Two surveys in one panel (shifts 0 and +2.5): a marker made for
        the second lands on the clicked x, not shifted by the first's."""
        ws = self.ws
        ws.group_var.set("Element name")           # one shared panel
        self.assertEqual(len(ws._groups()), 1)
        dlg = workbook_ui.IdentifyDialog(ws.root, ws, [self.a, self.b])
        self.addCleanup(dlg.destroy)
        dlg.reg_cb.current(1)                       # the shifted one
        dlg._on_click(O1S_SHOWN)
        idx = next(i for i, (k, _d, e) in enumerate(dlg.rows)
                   if k == "line" and xpslines.label_of(e) == "O 1s")
        dlg.cand_list.selection_clear(0, "end")
        dlg.cand_list.selection_set(idx)
        dlg._add()
        self.assertEqual(ws.identify_markers(self.a), [])
        self.assertAlmostEqual(ws.identify_markers(self.b)[0]["be"],
                               O1S_SHOWN - SHIFT, places=6)
        drawn = [m for m in self._rendered_markers() if m[1] == "O 1s"]
        self.assertEqual(len(drawn), 1)
        self.assertAlmostEqual(drawn[0][0], O1S_SHOWN, places=6)

    def test_nearby_lines_sit_at_their_table_energy(self):
        """A secondary line is drawn at its (calibrated) table BE, not at
        that plus the correction again."""
        ws = self.ws
        ws.ident_vars["secondary"].set(True)
        ws.identify_add(self.b, O1S_SHOWN - SHIFT, "O 1s")
        lines = ws.element_lines()
        expected = xpslines.nearby_lines(
            O1S_SHOWN, ws.IDENT_NEARBY_WINDOW, lines, hv=HV + SHIFT,
            exclude="O 1s", secondary=True)
        expected = [(be, lbl) for be, lbl, tier in expected
                    if tier == "secondary"]
        self.assertTrue(expected, "fixture needs a line near O 1s")
        drawn = {m[1]: m[0] for m in self._rendered_markers()
                 if len(m) > 3 and m[3] == "secondary"}
        for be, lbl in expected:
            self.assertIn(lbl, drawn)
            self.assertAlmostEqual(drawn[lbl], be, places=6)

    def test_an_auger_line_keeps_its_kinetic_energy(self):
        ws = self.ws
        ws.ident_vars["auger"].set(True)
        ws.identify_add(self.b, O1S_SHOWN - SHIFT, "O 1s")
        lines = ws.element_lines()
        expected = [(be, lbl) for be, lbl, tier in xpslines.nearby_lines(
            O1S_SHOWN, ws.IDENT_NEARBY_WINDOW, lines, hv=HV + SHIFT,
            exclude="O 1s", auger=True) if tier == "auger"]
        drawn = {m[1]: m[0] for m in self._rendered_markers()
                 if len(m) > 3 and m[3] == "auger"}
        for be, lbl in expected:
            self.assertAlmostEqual(drawn[lbl], be, places=6)
            # hv shifts with the correction, so KE = hv - BE is unchanged
            entry = next(e for e in lines if xpslines.label_of(e) == lbl)
            self.assertAlmostEqual((HV + SHIFT) - drawn[lbl], entry["ke"],
                                   places=6)

    def test_binding_at_still_gives_the_measured_value(self):
        """Calibrate's one-shot pick keeps getting the unshifted energy."""
        ws = self.ws
        ws._render()
        ax = next(iter(ws._axinfo))
        ws._axmap[ax] = ws._axmap.get(ax)
        ev = SimpleNamespace(inaxes=ax, xdata=O1S_SHOWN)
        self.assertAlmostEqual(ws.displayed_be(ev), O1S_SHOWN)
        measured = ws._binding_at(ev)
        key = ws._axmap.get(ax)
        first = next(rs[0] for k, rs in ws._groups() if k == key)
        self.assertAlmostEqual(measured,
                               O1S_SHOWN - ws._marker_shift(first))


if __name__ == "__main__":
    unittest.main()
