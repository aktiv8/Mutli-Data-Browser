"""FlowFrame (the wrapping button rows) must not keep re-arming itself while
it has no width. It used to reschedule its reflow on idle until it was mapped,
which spun the event loop for as long as a frame sat in a hidden tab and made
update_idletasks() on a withdrawn root never return (that hung the app-level
tests of the Report generator, covers, the report spec and the workbook
cache). <Map> and <Configure> call it again once it has a size.

Run:  python -m unittest discover tests
"""

import os
import sys
import tkinter as tk
import unittest
from tkinter import ttk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import spectradeck as ee
    HAVE = True
except Exception:                                   # pragma: no cover
    ee, HAVE = None, False


@unittest.skipUnless(HAVE, "spectradeck could not be imported")
class TestFlowFrame(unittest.TestCase):
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

    def frame(self, n=3):
        f = ee.FlowFrame(self.root)
        self.addCleanup(f.destroy)
        for i in range(n):
            f.add(ttk.Label(f, text=f"item {i}"))
        return f

    def test_an_unmapped_frame_does_not_keep_rescheduling(self):
        f = self.frame()
        self.assertTrue(f._pending)                  # add() asked for one
        self.root.update_idletasks()                 # used to never return
        self.assertFalse(f._pending)                 # ran once and stopped

    def test_it_lays_out_once_it_has_a_width(self):
        f = self.frame(4)
        f.pack(fill="x")
        f.configure(width=60)                        # narrow: forces wrapping
        self.root.update_idletasks()
        f._last_width = -1
        f.winfo_width = lambda: 60
        f._schedule_reflow()
        self.root.update_idletasks()
        ys = {w.winfo_y() for w, _px, _py in f._items}
        self.assertGreater(len(ys), 1, "the chunks should wrap onto rows")

    def test_a_late_add_still_reflows(self):
        f = self.frame(1)
        self.root.update_idletasks()
        self.assertFalse(f._pending)
        f.add(ttk.Label(f, text="late"))
        self.assertTrue(f._pending)
        self.root.update_idletasks()
        self.assertFalse(f._pending)


if __name__ == "__main__":
    unittest.main()
