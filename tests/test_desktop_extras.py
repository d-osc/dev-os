import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

TOOLS = Path(__file__).parents[1] / 'tools'


def load(name, file_name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / file_name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shell = load('shell_x', 'dev_shell.py')
edit = load('edit_x', 'dev_edit.py')
theme = load('theme_x', 'dev_theme.py')


class BatteryState(unittest.TestCase):
    def test_reads_capacity_and_charging(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'BAT0').mkdir()
            (base / 'BAT0' / 'type').write_text('Battery\n')
            (base / 'BAT0' / 'capacity').write_text('87\n')
            (base / 'BAT0' / 'status').write_text('Charging\n')
            self.assertEqual(shell.battery_state(str(base)), (87, True))

    def test_clamps_and_ignores_mains(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'AC').mkdir()
            (base / 'AC' / 'type').write_text('Mains\n')
            (base / 'BAT0').mkdir()
            (base / 'BAT0' / 'type').write_text('Battery\n')
            (base / 'BAT0' / 'capacity').write_text('250\n')
            (base / 'BAT0' / 'status').write_text('Discharging\n')
            self.assertEqual(shell.battery_state(str(base)), (100, False))

    def test_absent_or_broken_is_none(self):
        self.assertEqual(shell.battery_state('/nonexistent'), (None, False))
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'BAT0').mkdir()      # no type file: skipped
            self.assertEqual(shell.battery_state(directory), (None, False))


class EditorModel(unittest.TestCase):
    def test_typing_and_enter(self):
        lines, row, col = edit.edit_step([''], 0, 0, 0, 'h')
        lines, row, col = edit.edit_step(lines, row, col, 0, 'i')
        self.assertEqual((lines, row, col), (['hi'], 0, 2))
        lines, row, col = edit.edit_step(lines, row, col, edit.RETURN, '')
        self.assertEqual((lines, row, col), (['hi', ''], 1, 0))

    def test_backspace_merges_lines(self):
        lines, row, col = edit.edit_step(['ab', 'cd'], 1, 0, edit.BACKSPACE, '')
        self.assertEqual((lines, row, col), (['abcd'], 0, 2))

    def test_arrows_home_end(self):
        lines = ['one', 'two']
        self.assertEqual(edit.edit_step(lines, 0, 0, edit.END, ''), (lines, 0, 3))
        self.assertEqual(edit.edit_step(lines, 1, 0, edit.UP, ''), (lines, 0, 0))
        down = edit.edit_step(lines, 0, 5, edit.DOWN, '')      # col clamped
        self.assertEqual(down, (lines, 1, 3))

    def test_visible_rows_keeps_caret(self):
        lines = [str(i) for i in range(100)]
        top, room = edit.visible_rows(lines, 50, 440)
        self.assertTrue(top <= 50 < top + room)


class HighContrastTheme(unittest.TestCase):
    def test_theme_loads_and_reaches_both_toolkits(self):
        path = Path(__file__).parents[1] / 'themes' / 'high-contrast.json'
        resolved = theme.load(path)
        self.assertEqual(resolved['name'], 'High Contrast')
        self.assertEqual(resolved['colors']['accent'], (1.0, 1.0, 0.0))
        self.assertEqual(resolved['corners']['window'], 0.0)
        gui_palette = theme.gui_palette(resolved)
        shell_design = theme.shell_design(resolved)
        self.assertEqual(gui_palette['text'], (1.0, 1.0, 1.0))
        self.assertEqual(shell_design['green'], gui_palette['accent'])


if __name__ == '__main__':
    unittest.main()
