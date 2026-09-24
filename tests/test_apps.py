import importlib.util
from pathlib import Path
import tempfile
import unittest
import wave


def load(name, file_name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / 'tools' / file_name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


web = load('dev_web_local', 'dev_web.py')
music = load('dev_music_local', 'dev_music.py')
settings = load('dev_settings_apps', 'dev_settings.py')
shell = load('shell_apps', 'dev_shell.py')


def make_wav(path, frames=4410, rate=44100):
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(b'\x00\x00' * frames)


class WebNormalize(unittest.TestCase):
    def test_adds_scheme_and_keeps_full_urls(self):
        self.assertEqual(web.normalize('example.com'), 'http://example.com')
        self.assertEqual(web.normalize('example.com/x'), 'http://example.com/x')
        self.assertEqual(web.normalize('http://10.0.2.2:8000/'), 'http://10.0.2.2:8000/')
        self.assertEqual(web.normalize('https://a.b/c?d=e'), 'https://a.b/c?d=e')

    def test_untouched_kinds(self):
        self.assertEqual(web.normalize('file:///tmp/x.html'), 'file:///tmp/x.html')
        self.assertIsNone(web.normalize(''))
        self.assertIsNone(web.normalize('  '))


class WebFetch(unittest.TestCase):
    def test_file_url_returns_html(self):
        with tempfile.TemporaryDirectory() as directory:
            page = Path(directory) / 'page.html'
            page.write_text('<html><body><h1>Hello web</h1></body></html>')
            kind, payload = web.fetch('file://' + str(page).replace('\\', '/'))
            self.assertEqual(kind, 'html')
            self.assertIn('Hello web', payload)

    def test_plain_text_file(self):
        with tempfile.TemporaryDirectory() as directory:
            note = Path(directory) / 'note.txt'
            note.write_text('just text' + '\n' * 3)
            kind, payload = web.fetch('file://' + str(note).replace('\\', '/'))
            self.assertEqual(kind, 'text')
            self.assertIn('just text', payload)

    def test_missing_file_is_an_error_not_a_crash(self):
        kind, payload = web.fetch('file:///nonexistent/nope.html')
        self.assertEqual(kind, 'error')
        self.assertTrue(payload)


class MusicListing(unittest.TestCase):
    def test_lists_wavs_sorted_with_durations(self):
        with tempfile.TemporaryDirectory() as directory:
            make_wav(Path(directory) / 'b.wav', frames=44100)
            make_wav(Path(directory) / 'a.wav', frames=88200)
            (Path(directory) / 'readme.txt').write_text('no')
            name, rows = music.listing(directory)
            self.assertEqual(name, directory)
            self.assertEqual([row[0] for row in rows], ['a.wav', 'b.wav'])
            self.assertEqual(rows[0][1], 2.0)
            self.assertEqual(rows[1][1], 1.0)

    def test_bad_wav_has_no_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'broken.wav').write_bytes(b'not a wav')
            _, rows = music.listing(directory)
            self.assertEqual(rows[0][0], 'broken.wav')
            self.assertIsNone(rows[0][1])

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            _, rows = music.listing(directory)
            self.assertEqual(rows, [])


class MusicRows(unittest.TestCase):
    ROWS = [('a.wav', 1.0), ('b.wav', 2.0), ('c.wav', None)]

    def test_row_at_maps_clicks_to_files(self):
        self.assertEqual(music.row_at(music.LIST_TOP, self.ROWS, music.HEIGHT),
                         'a.wav')
        self.assertEqual(
            music.row_at(music.LIST_TOP + music.ROW_HEIGHT, self.ROWS, music.HEIGHT),
            'b.wav')

    def test_clicks_outside_the_list_are_ignored(self):
        self.assertIsNone(music.row_at(music.LIST_TOP - 1, self.ROWS, music.HEIGHT))
        self.assertIsNone(music.row_at(40, [], music.HEIGHT))
        self.assertIsNone(
            music.row_at(music.LIST_TOP + 10 * music.ROW_HEIGHT, self.ROWS,
                         music.HEIGHT))


class Narrator(unittest.TestCase):
    def test_announces_app_with_name(self):
        self.assertEqual(shell.narrator_text(('app', 0), ['Files', 'Edit']),
                         'App 1: Files')
        self.assertEqual(shell.narrator_text(('app', 5), []), 'App 6: application')

    def test_plain_targets_and_quiet(self):
        self.assertEqual(shell.narrator_text('menu'), 'Menu')
        self.assertEqual(shell.narrator_text(('tray', 0), ['Files']), 'Tray icon 1')
        self.assertIsNone(shell.narrator_text(None))

    def test_scaled_sizes(self):
        self.assertEqual(shell.scaled(13.0, 1.5), 19.5)
        self.assertEqual(shell.scaled(13.0), 13.0)
        self.assertEqual(shell.scaled(8.5, 2.0), 17.0)


class DisplayScaleSetting(unittest.TestCase):
    def test_scale_and_narrator_round_trip(self):
        merged = settings.resolve({'display.scale': 2.0,
                                   'accessibility.narrator': True})
        self.assertEqual(merged['display.scale'], 2.0)
        self.assertTrue(merged['accessibility.narrator'])
        self.assertEqual(settings.DEFAULTS['display.scale'], 1.0)
        self.assertFalse(settings.DEFAULTS['accessibility.narrator'])

    def test_scale_must_be_a_supported_step(self):
        for bad in (1.1, 3.0, '2', True, None):
            with self.assertRaises(ValueError):
                settings.resolve({'display.scale': bad})
        with self.assertRaises(ValueError):
            settings.resolve({'accessibility.narrator': 'on'})


if __name__ == '__main__':
    unittest.main()
