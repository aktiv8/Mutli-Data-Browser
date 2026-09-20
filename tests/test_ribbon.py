"""The tabbed toolbar: its button table, the icons it draws and how they look
on every theme. The buttons are data, so most of this needs no window.

Run:  python -m unittest discover tests
"""

import inspect
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import icons  # noqa: E402
import ribbon  # noqa: E402
import themes  # noqa: E402

try:
    from PIL import Image  # noqa: F401
    HAVE_PIL = True
except Exception:
    HAVE_PIL = False


def buttons(spec):
    """Every ordinary button and dropdown of a page: (label, icon, tip)."""
    out = []
    for it in spec:
        if it[0] == "|" or it[0] == "@theme":
            continue
        if it[0] == "v":
            out.append((it[1], it[2], it[4]))
        elif it[0] == "@pane":
            out.append((it[2], it[3], it[4]))
        else:
            out.append((it[0], it[1], it[3]))
    return out


class TestButtonTable(unittest.TestCase):
    def test_tabs_and_pages_agree(self):
        self.assertEqual(tuple(ribbon.PAGES), ribbon.TABS)
        for tab in ribbon.TABS:
            self.assertGreaterEqual(len(buttons(ribbon.PAGES[tab])), 3, tab)

    def test_every_button_has_a_known_icon_and_a_tip(self):
        for tab, spec in ribbon.PAGES.items():
            labels = []
            for label, icon, tip in buttons(spec):
                self.assertIn(icon, icons.NAMES, f"{tab}/{label}")
                self.assertGreater(len(tip), 10, f"{tab}/{label} has no tip")
                labels.append(label)
            self.assertEqual(len(labels), len(set(labels)),
                             f"duplicate labels on {tab}")

    def test_every_target_is_a_workspace_method(self):
        import spectradeck
        for name in ribbon.targets():
            self.assertTrue(callable(getattr(spectradeck.Workspace, name,
                                             None)), name)

    def test_the_menu_bar_keeps_every_function(self):
        """The buttons are shortcuts: nothing may be reachable only from
        them, so keyboard users lose nothing."""
        import spectradeck
        menu = inspect.getsource(spectradeck.Workspace._build_menu)
        for name in ribbon.targets():
            if name in ("_toggle_pane", "set_theme", "show_about"):
                continue
            self.assertIn(name, menu, f"{name} is not in the menu bar")

    def test_dropdown_items_have_targets(self):
        for spec in ribbon.PAGES.values():
            for it in spec:
                if it[0] == "v" and isinstance(it[3], list):
                    for sub in it[3]:
                        if sub is not None:
                            self.assertEqual(len(sub), 2)


@unittest.skipUnless(HAVE_PIL, "Pillow not installed")
class TestIcons(unittest.TestCase):
    def test_every_icon_draws_at_several_sizes(self):
        for name in icons.NAMES:
            for size in (16, 22, 32):
                im = icons.draw(name, size, "#202020", "#0F6B8C")
                self.assertEqual(im.size, (size, size), name)
                self.assertEqual(im.mode, "RGBA")
                solid = sum(im.getchannel("A").histogram()[129:])
                self.assertGreater(solid, size // 2,
                                   f"{name} looks empty at {size}")

    def test_icons_stay_inside_the_canvas(self):
        for name in icons.NAMES:
            im = icons.draw(name, 32, "#000000")
            edge = [im.getpixel((x, y))[3] for x in range(32)
                    for y in (0, 31)] + [im.getpixel((x, y))[3]
                                         for y in range(32) for x in (0, 31)]
            self.assertLess(max(edge), 60, f"{name} is clipped")

    def test_accent_colour_is_used_where_the_icon_asks_for_it(self):
        im = icons.draw("export", 32, "#000000", "#ff0000")
        raw = im.tobytes()
        colours = {tuple(raw[i:i + 3]) for i in range(0, len(raw), 4)
                   if raw[i + 3] > 200}
        self.assertIn((255, 0, 0), colours)
        self.assertIn((0, 0, 0), colours)

    def test_unknown_icon_is_an_error(self):
        with self.assertRaises(KeyError):
            icons.draw("nope")

    def test_colour_names_from_tk_are_resolved(self):
        self.assertEqual(icons.resolve_colour("#0F6B8C"), "#0F6B8C")
        try:
            import tkinter
            root = tkinter.Tk()
        except Exception:
            self.skipTest("no display")
        try:
            root.withdraw()
            got = icons.resolve_colour("systemwindowtext", root)
            self.assertRegex(got, r"^#[0-9a-f]{6}$")
            self.assertIn(icons.resolve_colour("red", root), ("red", "#ff0000"))
        finally:
            root.destroy()

    def test_icon_colours_read_on_the_toolbar_of_every_theme(self):
        """Main colour and accent against the toolbar's own background
        (about 3:1, the WCAG figure for graphics)."""
        for name, pal in themes.PALETTES.items():
            if name == themes.NATIVE:
                continue            # colours come from the operating system
            for key in ("fg", "accent"):
                ratio = themes.contrast(pal[key], pal["panel"])
                self.assertGreaterEqual(ratio, 2.95, f"{name}/{key} {ratio}")


if __name__ == "__main__":
    unittest.main()
