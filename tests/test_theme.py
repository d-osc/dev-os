import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    'dev_theme', Path(__file__).parents[1] / 'tools/dev_theme.py')
theme = importlib.util.module_from_spec(spec)
spec.loader.exec_module(theme)


class Colors(unittest.TestCase):
    def test_parse_color_forms(self):
        self.assertEqual(theme.parse_color('#0b0f16'), (0x0b / 255, 0x0f / 255, 0x16 / 255))
        self.assertEqual(theme.parse_color('#ABC'), theme.parse_color('#AABBCC'))
        for bad in ('0b0f16', '#GGGGGG', '#12345', '#1234567', '', '#', 'red', None, 5):
            with self.assertRaises(ValueError):
                theme.parse_color(bad)

    def test_default_colors_parse(self):
        for token, value in theme.DEFAULT_COLORS.items():
            self.assertEqual(len(theme.parse_color(value)), 3, token)


class Resolving(unittest.TestCase):
    def test_partial_theme_merges_over_defaults(self):
        resolved = theme.resolve({'name': 'Amber', 'colors': {'accent': '#FFB000'}})
        self.assertEqual(resolved['name'], 'Amber')
        self.assertEqual(resolved['colors']['accent'], theme.parse_color('#FFB000'))
        self.assertEqual(resolved['colors']['bg'], theme.parse_color('#0b0f16'))
        self.assertIn('wifi', resolved['icons'])

    def test_unknown_sections_and_tokens_are_rejected(self):
        for raw in ({'nope': 1}, {'colors': {'nope': '#000000'}}, {'icons': {'nope': {}}},
                    {'name': 5}, {'colors': []}):
            with self.assertRaises(ValueError):
                theme.resolve(raw)

    def test_icon_validation(self):
        good = {'view': [16, 16], 'elements': [{'kind': 'line', 'x1': 1, 'y1': 1,
                                                'x2': 2, 'y2': 2}]}
        theme.validate_icon('start', good)
        bad = [
            {'view': [16], 'elements': good['elements']},
            {'view': [16, 16]},
            {'view': [16, 16], 'elements': []},
            {'view': [16, 16], 'elements': [{'kind': 'triangle'}]},
            {'view': [16, 16], 'elements': [{'kind': 'rect', 'x': 0, 'y': 0, 'w': 0, 'h': 5}]},
            {'view': [16, 16], 'elements': [{'kind': 'circle', 'cx': 1, 'cy': 1, 'r': 0}]},
            {'view': [16, 16], 'elements': [{'kind': 'arc', 'cx': 1, 'cy': 1, 'r': 2,
                                             'from': 0, 'to': 0}]},
            {'view': [16, 16], 'elements': [{'kind': 'poly', 'points': [[1, 1]]}]},
            {'view': [16, 16], 'elements': [{'kind': 'line', 'x1': 1, 'y1': 1, 'x2': 2,
                                             'y2': 2, 'color': 'mauve'}]},
            {'view': [16, 16], 'elements': [{'kind': 'line', 'x1': 1, 'y1': 1, 'x2': 2,
                                             'y2': 2, 'width': 99}]},
            {'view': [16, 16], 'elements': [{'kind': 'line', 'x1': 1, 'y1': 1, 'x2': 2,
                                             'y2': 2, 'surprise': 1}]},
        ]
        for icon in bad:
            with self.assertRaises(ValueError):
                theme.validate_icon('start', icon)

    def test_the_built_in_icons_are_valid(self):
        for name, icon in theme.DEFAULT_ICONS.items():
            theme.validate_icon(name, icon)
            resolved = theme.resolve({'icons': {name: icon}})
            self.assertIs(resolved['icons'][name], icon)

    def test_load_reads_and_caps_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'amber.json'
            path.write_text(json.dumps({'name': 'Amber', 'colors': {'accent': '#FFB000'}}))
            self.assertEqual(theme.load(path)['name'], 'Amber')
            big = Path(directory) / 'big.json'
            big.write_text(' ' * (theme.LIMIT + 1))
            with self.assertRaises(ValueError):
                theme.load(big)


class Corners(unittest.TestCase):
    def test_partial_corners_merge_and_validate(self):
        resolved = theme.resolve({'corners': {'window': 0, 'start': 3.5}})
        self.assertEqual(resolved['corners']['window'], 0.0)
        self.assertEqual(resolved['corners']['start'], 3.5)
        self.assertEqual(resolved['corners']['menu'], 12.0)
        for raw in ({'corners': {'nope': 1}}, {'corners': {'window': -1}},
                    {'corners': {'window': 25}}, {'corners': []},
                    {'corners': {'window': True}}):
            with self.assertRaises(ValueError):
                theme.resolve(raw)

    def test_corner_radius_clamps_to_half_the_box(self):
        corners = theme.resolve({})['corners']
        self.assertEqual(theme.corner_radius(corners, 'chip', 64, 22), 11.0)
        self.assertEqual(theme.corner_radius(corners, 'chip', 20, 22), 10.0)
        self.assertEqual(theme.corner_radius(corners, 'window', 40, 12), 6.0)
        self.assertEqual(theme.corner_radius({'window': 0}, 'window', 40, 40), 0.0)


class Palettes(unittest.TestCase):
    def test_one_theme_reaches_both_toolkits(self):
        resolved = theme.resolve({'colors': {'accent': '#FFB000', 'chrome': '#1C1914'}})
        gui = theme.gui_palette(resolved)
        design = theme.shell_design(resolved)
        self.assertEqual(gui['accent'], theme.parse_color('#FFB000'))
        self.assertEqual(design['green'], gui['accent'])
        self.assertEqual(gui['chrome'], design['button'])
        self.assertEqual(gui['accent_dark'], theme.parse_color('#0b0f16'))
        self.assertEqual(design['sep'], design['line'])


if __name__ == '__main__':
    unittest.main()
