import importlib.util
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'tools'))


def load(name, path=None):
    spec = importlib.util.spec_from_file_location(name, path or (HERE / 'tools' / (name + '.py')))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gui = load('dev_gui')
shell = load('dev_shell')
info = load('desktop_info', HERE / 'examples/desktop-info/payload/opt/apps/desktop-info/window.py')


class Widgets(unittest.TestCase):
    def test_button_click_fires_only_when_press_and_release_both_hit(self):
        fired = []
        button = gui.Button('OK', 10, 10, 80, 26, lambda: fired.append(1), primary=True)
        button.press(50, 20)
        button.release(5, 5)  # dragged out before release
        self.assertEqual(fired, [])
        button.press(50, 20)
        button.release(50, 20)
        self.assertEqual(fired, [1])

    def test_button_hover_and_press_states(self):
        button = gui.Button('OK', 0, 0, 100, 30)
        self.assertEqual(button.state, 'normal')
        self.assertTrue(button.motion(50, 15))
        self.assertEqual(button.state, 'hover')
        self.assertFalse(button.motion(50, 15))  # no change, no redraw needed
        self.assertTrue(button.motion(200, 15))   # leaving is also a change
        self.assertEqual(button.state, 'normal')
        self.assertTrue(button.press(10, 10))
        self.assertEqual(button.state, 'pressed')
        button.motion(200, 15)  # sliding off cancels the press visual
        self.assertEqual(button.state, 'normal')

    def test_rect_hit_edges(self):
        self.assertTrue(gui.rect_hit(0, 0, 0, 0, 10, 10))
        self.assertTrue(gui.rect_hit(9, 9, 0, 0, 10, 10))
        self.assertFalse(gui.rect_hit(10, 5, 0, 0, 10, 10))

    def test_window_geometry_and_chrome(self):
        self.assertEqual(gui.TITLE_HEIGHT, 30)
        toolkit = type('T', (), {})  # only constants are exercised here
        self.assertGreater(gui.PALETTE['accent'][1], gui.PALETTE['accent'][0] + 0.4)


class ShellHover(unittest.TestCase):
    def test_hover_key_on_bar(self):
        self.assertEqual(shell.hover_key('bar', 3, 10, width=1024), 'menu')
        first = shell.PIN_START
        self.assertEqual(shell.hover_key('bar', first + 5, 10, width=1024, app_count=2),
                         ('app', 0))
        self.assertEqual(shell.hover_key('bar', first + shell.PIN_SIZE + shell.PIN_GAP + 5, 10,
                                         width=1024, app_count=2), ('app', 1))
        self.assertIsNone(shell.hover_key('bar', 700, 10, width=1024, app_count=2))
        self.assertIsNone(shell.hover_key('bar', 700, 10, width=1024))

    def test_hover_key_on_menu_items_and_consent(self):
        first = shell.MENU_HEADER_HEIGHT + 17
        self.assertEqual(shell.hover_key('menu', 30, first, item_count=3), ('item', 0))
        self.assertEqual(shell.hover_key('menu', 30, first + 2 * shell.MENU_ITEM_HEIGHT,
                                         item_count=3), ('item', 2))
        self.assertIsNone(shell.hover_key('menu', 30, 5, item_count=3))
        consent_top = shell.MENU_HEADER_HEIGHT + 2 * shell.MENU_ITEM_HEIGHT + 10
        self.assertEqual(shell.hover_key('menu', 240, consent_top, item_count=2, consent=True),
                         'allow')
        self.assertEqual(shell.hover_key('menu', 300, consent_top, item_count=2, consent=True),
                         'cancel')
        self.assertIsNone(shell.hover_key('menu', 30, consent_top, item_count=2, consent=True))
        # Without a consent row, that area is inert.
        self.assertIsNone(shell.hover_key('menu', 240, consent_top, item_count=2))


class DesktopInfo(unittest.TestCase):
    def test_meminfo_and_uptime_formatting(self):
        self.assertEqual(info.parse_meminfo('MemTotal:       2048000 kB\nMemFree: 1 kB\n'),
                         '2000 MiB')
        self.assertEqual(info.uptime_text(90), '1m')
        self.assertEqual(info.uptime_text(3700), '1h 1m')
        self.assertEqual(info.uptime_text(2 * 86400 + 3 * 3600 + 5 * 60), '2d 3h 5m')
        self.assertEqual(info.os_release('NAME="Dev OS"\nPRETTY_NAME="Dev OS 0.1"\n',
                                         'PRETTY_NAME'), 'Dev OS 0.1')

    def test_collect_rows_use_provided_sources(self):
        rows = info.collect(platform='DevOS 6.18.7 test', meminfo='MemTotal: 512000 kB\n',
                            release='PRETTY_NAME="Dev OS QA"\n', uptime=3660)
        self.assertEqual(rows, [('Version', 'Dev OS QA'), ('Kernel', 'DevOS 6.18.7 test'),
                                ('Memory', '500 MiB'), ('Uptime', '1h 1m')])


if __name__ == '__main__':
    unittest.main()
