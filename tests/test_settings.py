import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


def load_module(name, file_name):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).parents[1] / 'tools' / file_name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


settings = load_module('dev_settings', 'dev_settings.py')
gui = load_module('dev_gui_local', 'dev_gui.py')
shell = load_module('dev_shell_local', 'dev_shell.py')


class Validation(unittest.TestCase):
    def test_partial_settings_merge_over_defaults(self):
        resolved = settings.resolve({'theme': 'terminal-amber'})
        self.assertEqual(resolved['theme'], 'terminal-amber')
        self.assertTrue(resolved['clock.showSeconds'])
        self.assertEqual(resolved['font.family'], 'DejaVu Sans')

    def test_unknown_or_badly_typed_settings_are_rejected(self):
        for raw in ({'nope': 1}, {'clock.hour12': 'yes'}, {'clock.showSeconds': 0},
                    {'theme': ''}, {'theme': 'a' * 129}, {'font.family': 'bad\x1fname'},
                    {'clock.dateFormat': 'x' * 49}, {'theme': 7}, []):
            with self.assertRaises(ValueError):
                settings.resolve(raw)

    def test_load_reads_and_caps_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            path.write_text(json.dumps({'clock.hour12': True}))
            self.assertTrue(settings.load(path)['clock.hour12'])
            big = path.with_name('big.json')
            big.write_text(' ' * (settings.LIMIT + 1))
            with self.assertRaises(ValueError):
                settings.load(big)

    def test_active_layers_later_files_win(self):
        with tempfile.TemporaryDirectory() as directory:
            system = Path(directory) / 'system.json'
            user = Path(directory) / 'user.json'
            override = Path(directory) / 'override.json'
            system.write_text(json.dumps({'theme': 'a', 'clock.showSeconds': False}))
            user.write_text(json.dumps({'theme': 'b'}))
            previous = (settings.SYSTEM, settings.USER)
            settings.SYSTEM, settings.USER = system, user
            try:
                merged = settings.active()
                self.assertEqual(merged['theme'], 'b')
                self.assertFalse(merged['clock.showSeconds'])
                override.write_text(json.dumps({'theme': 'c'}))
                self.assertEqual(settings.active(override)['theme'], 'c')
            finally:
                settings.SYSTEM, settings.USER = previous


class ThemeNames(unittest.TestCase):
    def test_theme_path_by_name_directory_and_path(self):
        with tempfile.TemporaryDirectory() as directory:
            themes = Path(directory) / 'themes'
            themes.mkdir()
            (themes / 'night.json').write_text('{}')
            self.assertEqual(settings.theme_path('night', (themes,)),
                             themes / 'night.json')
            self.assertEqual(settings.theme_path('sub/night.json', (themes,)),
                             Path('sub/night.json'))
            self.assertIsNone(settings.theme_path('default', (themes,)))
            with self.assertRaises(ValueError):
                settings.theme_path('missing', (themes,))


class ClockAndFont(unittest.TestCase):
    def test_time_text_follows_clock_settings(self):
        import re as regex
        moment = 0
        self.assertRegex(shell.time_text(moment), r'\d{2}:\d{2}:\d{2}')
        without_seconds = shell.time_text(moment, {'clock.showSeconds': False})
        self.assertRegex(without_seconds, r'^\d{2}:\d{2}$')
        hour12 = shell.time_text(moment, {'clock.hour12': True})
        self.assertRegex(hour12, r'\d{2}:\d{2}:\d{2} [AP]M')
        self.assertRegex(
            shell.time_text(moment, {'clock.hour12': True, 'clock.showSeconds': False}),
            r'\d{2}:\d{2} [AP]M')

    def test_date_text_follows_the_format_setting(self):
        self.assertRegex(shell.date_text(0), r'^[A-Z]{3} \d{2}, \d{4}$')
        self.assertRegex(shell.date_text(0, {'clock.dateFormat': '%Y/%m/%d'}),
                         r'^\d{4}/\d{2}/\d{2}$')

    def test_set_font_reaches_the_toolkit(self):
        previous = gui.FONT
        try:
            gui.set_font('DejaVu Serif')
            self.assertEqual(gui.FONT, b'DejaVu Serif')
        finally:
            gui.set_font(previous.decode('ascii'))


if __name__ == '__main__':
    unittest.main()
