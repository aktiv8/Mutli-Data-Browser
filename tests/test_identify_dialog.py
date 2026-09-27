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

    def fake_app(self):
        return SimpleNamespace(
            root=self.root,
            palette={"bg": "#fff", "fg": "#000", "panel": "#eee",
                     "entry": "#fff", "select_bg": "#ccc",
                     "select_fg": "#000"},
            themes=SimpleNamespace(recolor_tk=lambda w: None),
            element_lines=lambda: xpslines.load_lines(),
            calibration_label=lambda r: r.name,
            identify_markers=lambda r: self.markers,
            identify_add=self._fake_add,
            identify_remove=lambda r, m: None,
            identify_clear=lambda r: None,
            identify_auto=lambda r: 0)

    def _fake_add(self, region, be, label):
        self.added.append((region.name, be, label))

    def region(self, name="Fe 2p", hv=1486.6):
        return SimpleNamespace(name=name, photon_energy=hv)

    def dialog(self, regions=None):
        dlg = workbook_ui.IdentifyDialog(
            self.root, self.fake_app(), regions or [self.region()])
        self.addCleanup(dlg.destroy)
        return dlg

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

    def test_core_level_restricts_which_states_are_offered(self):
        dlg = self.dialog(regions=[self.region(name="C 1s")])
        dlg._on_click(709.9)          # near the Fe 2p fixture states
        self.assertEqual(
            [k for k, _d, _e in dlg.rows if k == "state"], [])


if __name__ == "__main__":
    unittest.main()
