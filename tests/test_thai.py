import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    'dev_gui_thai', Path(__file__).parents[1] / 'tools/dev_gui.py')
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)

shell_spec = importlib.util.spec_from_file_location(
    'dev_shell_toast', Path(__file__).parents[1] / 'tools/dev_shell.py')
shell = importlib.util.module_from_spec(shell_spec)
shell_spec.loader.exec_module(shell)

files_spec = importlib.util.spec_from_file_location(
    'dev_files_mod', Path(__file__).parents[1] / 'tools/dev_files.py')
files = importlib.util.module_from_spec(files_spec)
files_spec.loader.exec_module(files)


class ThaiInput(unittest.TestCase):
    def test_kedmanee_base_layer(self):
        self.assertEqual(gui.thai_char('a'), '\u0e1f')       # ฟ
        self.assertEqual(gui.thai_char('s'), '\u0e2b')       # ห
        self.assertEqual(gui.thai_char('g'), '\u0e49')       # ้
        self.assertEqual(gui.thai_char('/'), '\u0e1d')       # ผ
        self.assertEqual(gui.thai_char('e'), '\u0e33')       # ำ

    def test_kedmanee_shift_layer(self):
        self.assertEqual(gui.thai_char('A'), '\u0e24')       # ฤ
        self.assertEqual(gui.thai_char('F'), '\u0e26')       # ฦ
        self.assertEqual(gui.thai_char('~'), '\u0e4f')       # ฿
        self.assertIsNone(gui.thai_char(' '))

    def test_entry_thai_mode(self):
        entry = gui.Entry(0, 0, 100, 30, thai=True)
        for character in 'gdk;xa':
            entry.feed(0, character)
        self.assertEqual(entry.text, '\u0e49\u0e01\u0e2a\u0e07\u0e1b\u0e1f')
        plain = gui.Entry(0, 0, 100, 30)
        plain.feed(0, 'a')
        self.assertEqual(plain.text, 'a')

    def test_backspace_and_submit_work_in_thai_mode(self):
        entry = gui.Entry(0, 0, 100, 30, thai=True)
        entry.feed(0, 'a')
        entry.feed(gui.KEYSYM_BACKSPACE, '')
        self.assertEqual(entry.text, '')
        self.assertEqual(entry.feed(gui.KEYSYM_RETURN, ''), 'submit')


class Toasts(unittest.TestCase):
    def test_layout_stacks_expires_and_fades(self):
        now = 100.0
        messages = [{'title': 'one', 'body': 'a', 'at': now - 0.5},
                    {'title': 'two', 'body': 'b', 'at': now - 4.2},
                    {'title': 'old', 'body': 'c', 'at': now - 9.0}]
        cards = shell.toast_layout(messages, now, 1280, 800)
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0][0], 1280 - 296)
        self.assertEqual(cards[0][2], 'one')
        self.assertEqual(cards[1][2], 'two')
        self.assertLess(cards[1][4], 1.0)          # fading out
        self.assertEqual(shell.toast_layout([], now, 100, 100), [])


class FilesLogic(unittest.TestCase):
    def test_human_sizes(self):
        self.assertEqual(files.human(0), '0 B')
        self.assertEqual(files.human(2048), '2 KiB')
        self.assertEqual(files.human(5 * 1024 * 1024), '5 MiB')

    def test_entries_directories_first(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'zebra.txt').write_text('x')
            (base / 'alpha').mkdir()
            (base / 'beta.txt').write_text('y' * 10)
            _path, rows = files.entries(base)
            self.assertEqual(rows[0][0], 'alpha')
            self.assertTrue(rows[0][1])
            self.assertEqual([row[0] for row in rows[1:]], ['beta.txt', 'zebra.txt'])
            self.assertEqual(rows[2][2], '1 B')

    def test_room_scales_with_height(self):
        self.assertGreater(files.room_for(460), files.room_for(300))


if __name__ == '__main__':
    unittest.main()
