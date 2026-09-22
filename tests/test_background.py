import importlib.util
from pathlib import Path
import unittest

TOOLS = Path(__file__).parents[1] / 'tools'
spec = importlib.util.spec_from_file_location('dev_background', TOOLS / 'dev_background.py')
background = importlib.util.module_from_spec(spec)
spec.loader.exec_module(background)


class Stub:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*arguments, **keywords):
            self.calls.append((name, arguments, keywords))
            if name == 'surface_from_png':
                return None
            if name in ('image_width', 'image_height'):
                return 4
            if name == 'pattern_linear':
                return object()
            return None
        return call


class Kinds(unittest.TestCase):
    def test_dispatch(self):
        cases = {'none': 'none', '': 'none', '#0b0f16': 'color',
                 'a.png': 'png', 'a.PNG': 'png', 'a.jpg': 'jpg',
                 'a.jpeg': 'jpg', 'a.svg': 'svg', 'a.html': 'html'}
        for value, kind in cases.items():
            self.assertEqual(background.background_kind(value), kind, value)
        with self.assertRaises(ValueError):
            background.background_kind('wallpaper.bmp')

    def test_colors(self):
        self.assertEqual(background.parse_color('#ABC'),
                         background.parse_color('#AABBCC'))
        self.assertEqual(background.parse_color(' red '), (1.0, 0.0, 0.0))
        self.assertEqual(background.parse_color('green'), (0.0, 0x80 / 255, 0.0))
        for bad in ('blueish', '#12345', '#GGGGGG', 5, '#1234567'):
            with self.assertRaises(ValueError):
                background.parse_color(bad)


class Svg(unittest.TestCase):
    SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
           '<rect x="0" y="0" width="100" height="100" fill="#008000"/>'
           '<circle cx="50" cy="50" r="20" fill="#ffffff" stroke="#000000" '
           'stroke-width="2"/>'
           '<path d="M10 10 L90 10 L90 90 C50 50 20 20 10 10 Z" fill="#ff0000"/>'
           '</svg>')

    def test_parse_extracts_shapes_and_viewbox(self):
        view, shapes = background.parse_svg(self.SVG)
        self.assertEqual(view, [0.0, 0.0, 100.0, 100.0])
        tags = [shape[0] for shape in shapes]
        self.assertEqual(tags, ['rect', 'circle', 'polyline'])
        self.assertEqual(shapes[0][2], (0, 128 / 255, 0))
        self.assertEqual(shapes[2][1][:3], [(10.0, 10.0), (90.0, 10.0), (90.0, 90.0)])

    def test_rejects_bad_documents(self):
        with self.assertRaises(ValueError):
            background.parse_svg('<html></html>')
        with self.assertRaises(ValueError):
            background.parse_svg('x' * (background.FILE_LIMIT + 1))

    def test_path_skeleton_with_relative_commands(self):
        points = background._path_points('M10 10 l20 0 h5 v5 L50 50 z')
        self.assertEqual(points, [(10, 10), (30, 10), (35, 10), (35, 15),
                                  (50, 50), (10, 10)])


class Html(unittest.TestCase):
    PAGE = ('<html><body style="background:linear-gradient(#102030,#3060a0)">'
            '<h1 style="left:40px; top:120px; font-size:48px; font-weight:bold; color:#ffffff">'
            'Hello</h1>'
            '<img src="art/logo.png">'
            '</body></html>')

    def test_parse_background_text_and_image(self):
        page_background, items = background.parse_html(self.PAGE)
        self.assertEqual(page_background[0], 'gradient')
        self.assertEqual(page_background[1],
                         ((0x10 / 255, 0x20 / 255, 0x30 / 255),
                          (0x30 / 255, 0x60 / 255, 0xA0 / 255)))
        self.assertEqual(items[0][0], 'text')
        self.assertEqual(items[0][1], 'Hello')
        self.assertTrue(items[0][5])
        self.assertEqual(items[1], ('image', 'art/logo.png'))

    def test_bad_styles_are_ignored(self):
        _, items = background.parse_html(
            '<body style="background-color:#zzzzzz"><p style="left:x">ok</p>')
        self.assertEqual(len(items), 1)


class Render(unittest.TestCase):
    def test_none_and_color_paint_flat(self):
        stub = Stub()
        background.render(stub, None, 100, 100, 'none', (0.1, 0.2, 0.3))
        background.render(stub, None, 100, 100, '#336699', (0, 0, 0))
        paints = [call for call in stub.calls if call[0] == 'paint']
        self.assertEqual(len(paints), 2)

    def test_broken_files_fall_back_without_raising(self):
        stub = Stub()
        background.render(stub, None, 100, 100, '/nonexistent/dir/bg.svg',
                          (0.1, 0.2, 0.3))
        self.assertTrue(any(call[0] == 'paint' for call in stub.calls))
        stub2 = Stub()
        background.render(stub2, None, 100, 100, '/nonexistent/x.png',
                          (0.1, 0.2, 0.3))
        self.assertTrue(any(call[0] == 'paint' for call in stub2.calls))

    def test_svg_paints_shapes(self):
        stub = Stub()
        view, shapes = background.parse_svg(Svg.SVG)
        background._paint_svg(stub, None, 200, 100, view, shapes)
        self.assertTrue(any(call[0] == 'fill' for call in stub.calls))
        self.assertTrue(any(call[0] == 'stroke' for call in stub.calls))


if __name__ == '__main__':
    unittest.main()
