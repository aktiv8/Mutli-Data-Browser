"""IdentifyDialog: element-line and chemical-state candidate lookup on a
plot click (workbook_ui.IdentifyDialog).

Run:  python -m unittest discover tests
"""

import os
import sys
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import chemstates  # noqa: E402
import workbook_ui  # noqa: E402
import xpslines  # noqa: E402

FIXTURE_STATES = [
    {"core_level": "Fe 2p", "state": "Fe2p3/2 aFe2O3 peak 1", "be": 709.83,
     "fwhm": 1.0, "model": "GL (Area)",
     "source": "Biesinger et al., Appl. Surf. Sci. 257 (2011) 2717"},
    {"core_level": "Fe 2p", "state": "Fe2p3/2 Metal", "be": 706.9,
     "fwhm": 0.9, "model": "GL (Area)",
     "source": "Biesinger et al., Appl. Surf. Sci. 257 (2011) 2717"},
    {"core_level": "Ti 2p", "state": "Ti2p3/2 TiO2", "be": 458.6,
     "fwhm": 1.1, "model": "GL (Area)", "source": "irrelevant"},
]


class TestIdentifyDialog(unittest.TestCase):
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
        patcher = mock.patch.object(chemstates, "load_states",
                                    return_value=FIXTURE_STATES)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.added = []
        self.markers = []
        self.predefined = []
        self.casa_labelled = []
        self.shift = 0.0

    def fake_app(self):
        return SimpleNamespace(
            root=self.root,
            palette={"bg": "#fff", "fg": "#000", "panel": "#eee",
                     "entry": "#fff", "select_bg": "#ccc",
                     "select_fg": "#000", "accent": "#06c"},
            themes=SimpleNamespace(recolor_tk=lambda w: None),
            element_lines=lambda: xpslines.load_lines(),
            calibration_label=lambda r: r.name,
            identify_markers=lambda r: self.markers,
            identify_frame=lambda r: (self.shift, r.photon_energy + self.shift),
            identify_add=self._fake_add,
            identify_remove=lambda r, m: None,
            identify_clear=lambda r: None,
            identify_auto=lambda r: 0,
            predefined_regions=lambda: self.predefined,
            identify_from_casa=self._fake_casa_label)

    def _fake_add(self, region, be, label):
        self.added.append((region.name, be, label))

    def _fake_casa_label(self, region):
        self.casa_labelled.append(region.name)
        return 1

    def region(self, name="Fe 2p", hv=1486.6):
        return SimpleNamespace(name=name, photon_energy=hv)

    def dialog(self, regions=None):
        dlg = workbook_ui.IdentifyDialog(
            self.root, self.fake_app(), regions or [self.region()])
        self.addCleanup(dlg.destroy)
        return dlg

    def test_nist_link_opens_the_database_and_does_not_ship_its_data(self):
        dlg = self.dialog()
        with mock.patch.object(workbook_ui.about_ui, "open_link",
                              return_value=True) as opened:
            dlg._open_nist_link()
        opened.assert_called_once_with(workbook_ui.NIST_XPS_URL)
        self.assertTrue(workbook_ui.NIST_XPS_URL.startswith("https://"))

    def test_a_click_lists_both_lines_and_states(self):
        dlg = self.dialog()
        dlg._on_click(709.9)
        kinds = [kind for kind, _d, _e in dlg.rows]
        self.assertIn("state", kinds)
        # the fixture's two Fe 2p states are both within the default 2 eV
        # window of 709.9; the unrelated Ti 2p state must not appear
        state_labels = [chemstates.label_of(e) for k, _d, e in dlg.rows
                        if k == "state"]
        self.assertIn("Fe2p3/2 aFe2O3 peak 1", state_labels)
        self.assertNotIn("Ti2p3/2 TiO2", state_labels)

    def test_state_rows_are_visually_marked_and_sorted_nearest_first(self):
        dlg = self.dialog()
        dlg._on_click(709.9)
        texts = [dlg.cand_list.get(i) for i in range(dlg.cand_list.size())]
        state_rows = [t for t in texts if t.startswith(dlg.STATE_MARK)]
        self.assertTrue(state_rows)
        deltas = [abs(d) for kind, d, _e in dlg.rows if kind == "state"]
        self.assertEqual(deltas, sorted(deltas))

    def test_selecting_a_state_row_shows_its_source(self):
        dlg = self.dialog()
        dlg._on_click(709.9)
        idx = next(i for i, (kind, _d, _e) in enumerate(dlg.rows)
                  if kind == "state")
        dlg.cand_list.selection_clear(0, "end")
        dlg.cand_list.selection_set(idx)
        dlg._on_select()
        self.assertIn("Biesinger", dlg.source_label.cget("text"))

    def test_adding_a_state_candidate_uses_its_own_label(self):
        dlg = self.dialog()
        dlg._on_click(709.9)
        idx = next(i for i, (kind, _d, _e) in enumerate(dlg.rows)
                  if kind == "state")
        dlg.cand_list.selection_clear(0, "end")
        dlg.cand_list.selection_set(idx)
        dlg._add()
        self.assertEqual(len(self.added), 1)
        region_name, be, label = self.added[0]
        self.assertEqual(region_name, "Fe 2p")
        self.assertAlmostEqual(be, 709.9)
        self.assertIn(label, ("Fe2p3/2 aFe2O3 peak 1", "Fe2p3/2 Metal"))

    def test_a_charge_corrected_click_is_looked_up_as_shown(self):
        """The click arrives as drawn (O 1s at 531.0 after a +2.5 eV
        correction); the table is calibrated, so O 1s must be offered, and
        the marker is stored as measured (shown minus the shift)."""
        self.shift = 2.5
        dlg = self.dialog(regions=[self.region(name="O 1s")])
        dlg._on_click(531.0)
        labels = [xpslines.label_of(e) for k, _d, e in dlg.rows
                  if k == "line"]
        self.assertIn("O 1s", labels)
        idx = next(i for i, (k, _d, e) in enumerate(dlg.rows)
                   if k == "line" and xpslines.label_of(e) == "O 1s")
        dlg.cand_list.selection_clear(0, "end")
        dlg.cand_list.selection_set(idx)
        dlg._add()
        _name, be, label = self.added[0]
        self.assertEqual(label, "O 1s")
        self.assertAlmostEqual(be, 531.0 - 2.5)

    def test_the_default_window_is_wide_enough_for_a_chemical_shift(self):
        dlg = self.dialog(regions=[self.region(name="Si 2p")])
        dlg._on_click(102.0)           # SiO2: ~2.6 eV above Si 2p3/2 (99.4)
        labels = [xpslines.label_of(e) for k, _d, e in dlg.rows
                  if k == "line"]
        self.assertIn("Si 2p3/2", labels)

    def test_core_level_restricts_which_states_are_offered(self):
        dlg = self.dialog(regions=[self.region(name="C 1s")])
        dlg._on_click(709.9)          # near the Fe 2p fixture states
        self.assertEqual(
            [k for k, _d, _e in dlg.rows if k == "state"], [])

    def test_a_ranged_state_shows_its_range_in_the_row(self):
        with mock.patch.object(chemstates, "load_states", return_value=[
                {"core_level": "Fe 2p", "state": "Fe2p3/2 aFe2O3 peak 1",
                 "be": 709.83, "fwhm": 1.0, "model": "GL (Area)",
                 "source": "Biesinger et al.", "range": [709.5, 710.2]}]):
            dlg = self.dialog()
            dlg._on_click(709.9)
        texts = [dlg.cand_list.get(i) for i in range(dlg.cand_list.size())]
        row = next(t for t in texts if "aFe2O3" in t)
        self.assertIn("[709.5–710.2]", row)

    def test_casa_label_button_acts_on_every_predefined_region_not_just_selection(self):
        """Regression: 'Label from CasaXPS regions' used to loop over
        self.regions -- the dialog's own region list, which the caller
        (Workspace.open_identify -> calibration_regions()) scopes to
        whatever tree row is highlighted, not every ticked Survey. It must
        act on app.predefined_regions() (every ticked CasaXPS-region
        spectrum) instead, so it still labels spectra the dialog itself
        was never given."""
        region_a = self.region(name="C 1s")
        region_b = self.region(name="O 1s")
        self.predefined = [region_a, region_b]
        dlg = self.dialog(regions=[region_a])   # as if only one row selected

        dlg._casa_label()

        self.assertEqual(self.casa_labelled, ["C 1s", "O 1s"])

    def test_casa_button_enabled_state_follows_predefined_regions(self):
        """The button's enabled state must reflect every ticked CasaXPS
        region, not just the dialog's own (selection-scoped) region list."""
        dlg = self.dialog(regions=[self.region()])
        self.assertEqual(str(dlg.casa_btn.cget("state")), "disabled")

        self.predefined = [self.region(name="Ti 2p")]
        dlg._refresh_markers()

        self.assertEqual(str(dlg.casa_btn.cget("state")), "normal")


if __name__ == "__main__":
    unittest.main()
