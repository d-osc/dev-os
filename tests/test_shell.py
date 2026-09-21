import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import sys
sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
import dev_gui
spec = importlib.util.spec_from_file_location('dev_shell', Path(__file__).parents[1] / 'tools/dev_shell.py')
shell = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shell)


def app(name, **fields):
    record = {'name': name, 'version': '1.0', 'window': {'type': 'desktop'}, 'permissions': ['window']}
    record.update(fields)
    return record


class Applications(unittest.TestCase):
    def test_menu_lists_window_apps_sorted_with_launcher_defaults(self):
        database = {'beta': app('beta', display_name='Beta Tool', permissions=['window', 'storage']),
                    'alpha': app('alpha', launcher={'name': 'Alpha App', 'comment': 'Counts'},
                                 permissions=['window', 'storage', 'background']),
                    'cli-only': {'name': 'cli-only', 'version': '2.0', 'permissions': []},
                    'not-a-dict': None}
        items = shell.applications(database)
        self.assertEqual([item['name'] for item in items], ['alpha', 'beta'])
        self.assertEqual(items[0]['label'], 'Alpha App')
        self.assertEqual(items[0]['comment'], 'Counts')
        self.assertEqual(items[1]['label'], 'Beta Tool')
        self.assertEqual(items[1]['categories'], ['Utility'])

    def test_grant_is_exactly_the_declared_permission_set(self):
        item = shell.applications({'x': app('x', permissions=['background', 'window'])})[0]
        self.assertEqual(shell.grant_for(item), 'background,window')
        self.assertEqual(shell.grant_for({'permissions': []}), '')

    def test_launch_command_uses_root_override_only_for_a_dev_path(self):
        item = {'name': 'hello', 'permissions': ['window']}
        self.assertEqual(shell.launch_command('dev', '/', item),
                         ['dev', 'launch', 'hello', '--allow', 'window'])
        self.assertEqual(shell.launch_command('tools/dev.py', 'out/demo', item)[:4],
                         [shell.sys.executable, 'tools/dev.py', '--root', 'out/demo'])

    def test_database_loading_from_a_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(shell.load_database(root), {})
            (root / 'var/lib/dev').mkdir(parents=True)
            (root / 'var/lib/dev/installed.json').write_text(json.dumps({'hello': app('hello')}))
            self.assertEqual(list(shell.load_database(root)), ['hello'])


class Layout(unittest.TestCase):
    def test_clock_text_shape(self):
        import re as regex
        self.assertRegex(shell.time_text(0), r'\d{2}:\d{2}:\d{2}')
        self.assertRegex(shell.date_text(0), r'^[A-Z]{3} \d{2}, \d{4}$')

    def test_truncate_with_fake_metrics(self):
        measure = lambda text: len(text) * 6
        self.assertEqual(shell.truncate('short', measure, 60), 'short')
        self.assertEqual(shell.truncate('a-very-long-title', measure, 54), 'a-very...')
        self.assertEqual(shell.truncate('abcdef', measure, 12), '...')

    def test_monogram_takes_the_first_letter(self):
        self.assertEqual(shell.monogram({'label': 'Alpha App'}), 'A')
        self.assertEqual(shell.monogram({'label': 'desktop-counter'}), 'D')
        self.assertEqual(shell.monogram({'label': '... '}), '>')

    def test_pinned_icons_are_capped_and_centered(self):
        self.assertEqual(shell.pinned_count(12, 1024), 9)
        self.assertEqual(shell.pinned_count(3, 1024), 3)
        self.assertEqual(shell.pinned_count(3, 300), 0)
        left = shell.pin_left(1024, 2)
        self.assertEqual(left, (1024 - (2 * shell.PIN_SIZE + shell.PIN_GAP)) // 2)

    def test_pinned_states_match_windows_by_title(self):
        item = {'label': 'Alpha App', 'name': 'alpha'}
        running, active = shell.pinned_states(
            [item, {'label': 'Beta', 'name': 'beta'}],
            [('other window', 7), ('alpha app', 9)])
        self.assertEqual(running, [True, False])
        self.assertEqual(active, 0)
        self.assertEqual(shell.window_for(item, [('Alpha App', 5)]), 5)
        self.assertIsNone(shell.window_for({'label': 'X', 'name': 'x'}, [('Y', 1)]))

    def test_bar_hit_regions(self):
        self.assertEqual(shell.bar_hit(1024, 3, 2), ('menu', None))
        self.assertEqual(shell.bar_hit(1024, 100, 2), ('menu', None))
        first = shell.pin_left(1024, 2)
        self.assertEqual(shell.bar_hit(1024, first + 5, 2), ('app', 0))
        self.assertEqual(shell.bar_hit(1024, first + shell.PIN_SIZE + shell.PIN_GAP + 5, 2),
                         ('app', 1))
        self.assertEqual(shell.bar_hit(1024, 1020, 2), ('clock', None))
        self.assertEqual(shell.bar_hit(1024, 200, 0), (None, None))

    def test_bar_hover_follows_the_same_layout(self):
        self.assertEqual(shell.hover_key('bar', 30, 12, width=1024, app_count=0), 'menu')
        first = shell.pin_left(1024, 2)
        self.assertEqual(shell.hover_key('bar', first + 5, 10, width=1024, app_count=2),
                         ('app', 0))
        self.assertIsNone(shell.hover_key('bar', 700, 5, width=1024, app_count=2))
        self.assertIsNone(shell.hover_key('bar', 1020, 5, width=1024, app_count=2))

    def test_menu_geometry_and_item_hits(self):
        geometry = shell.menu_geometry(1024, 768, 3)
        self.assertEqual((geometry['x'], geometry['width']), (2, 320))
        self.assertEqual(geometry['height'], 26 + 3 * 36)
        self.assertEqual(geometry['y'], 768 - shell.BAR_HEIGHT - geometry['height'] - 2)
        self.assertEqual(shell.item_at(3, 26 + 17), 0)
        self.assertEqual(shell.item_at(3, 26 + 2 * 36 + 17), 2)
        self.assertIsNone(shell.item_at(3, 26 + 3 * 36 + 20))
        clamped = shell.menu_geometry(1024, 100, 40)
        self.assertLessEqual(clamped['height'], 100 - shell.BAR_HEIGHT - 2)

    def test_consent_choice_zones(self):
        rows = 26 + 2 * 36
        self.assertIsNone(shell.consent_choice(240, rows + 5, 2, False))
        self.assertEqual(shell.consent_choice(240, rows + 5, 2, True), 'allow')
        self.assertEqual(shell.consent_choice(300, rows + 5, 2, True), 'cancel')
        self.assertIsNone(shell.consent_choice(30, rows + 5, 2, True))
        self.assertIsNone(shell.consent_choice(240, rows - 5, 2, True))

    def test_png_writer_produces_a_valid_header(self):
        import struct
        import zlib
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'x.png'
            dev_gui.write_png(path, 2, 1, [bytearray((255, 0, 0, 0, 255, 0))])
            data = path.read_bytes()
        self.assertTrue(data.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertIn(b'IDAT', data)
        self.assertEqual(zlib.crc32(b'IEND') > 0, True)
        width, height = struct.unpack('>II', data[16:24])
        self.assertEqual((width, height), (2, 1))
