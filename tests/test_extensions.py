import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    'dev_extensions', Path(__file__).parents[1] / 'tools/dev_extensions.py')
extensions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extensions)

GOOD_MANIFEST = {'id': 'devos.demo', 'name': 'Demo', 'version': '1.0.0',
                 'engine': 1, 'main': 'extension.py'}
GOOD_CODE = '''
STATE = []

def activate(api):
    STATE.append('activated')
    api.register_command('devos.demo.run', 'Run demo', lambda: STATE.append('ran'))
    api.register_tray('demo', 'wifi', command_id='devos.demo.run')

def deactivate():
    STATE.append('deactivated')
'''


def provides():
    return {'settings': lambda: {}, 'theme': lambda: {'name': 'x'},
            'screen': lambda: [800, 600], 'notify': lambda *a: None,
            'set_theme': lambda p: None}


class Manifests(unittest.TestCase):
    def test_valid_manifest_passes(self):
        self.assertEqual(extensions.validate(dict(GOOD_MANIFEST))['id'], 'devos.demo')

    def test_bad_manifests_are_rejected(self):
        bad = [
            dict(GOOD_MANIFEST, engine=2),
            dict(GOOD_MANIFEST, main='other.py'),
            dict(GOOD_MANIFEST, id='Bad Id'),
            dict(GOOD_MANIFEST, id='x' * 65),
            dict(GOOD_MANIFEST, version='1.0'),
            dict(GOOD_MANIFEST, name=''),
            dict(GOOD_MANIFEST, extra=1),
            {'id': 'devos.demo'},
            [],
        ]
        for manifest in bad:
            with self.assertRaises(ValueError):
                extensions.validate(manifest)


class HostLifecycle(unittest.TestCase):
    def write(self, directory, code=GOOD_CODE, manifest=None):
        path = Path(directory) / 'demo'
        path.mkdir()
        (path / 'manifest.json').write_text(json.dumps(manifest or GOOD_MANIFEST))
        (path / 'extension.py').write_text(code)
        return path

    def test_activate_register_and_run(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write(directory)
            host = extensions.Host(provides()).load([directory])
            self.assertEqual(host.loaded, ['devos.demo'])
            self.assertEqual(host.report, [])
            self.assertEqual([command['id'] for command in host.commands],
                             ['devos.demo.run'])
            self.assertEqual(host.command_entries()[0]['kind'], 'command')
            self.assertEqual(host.tray[0]['icon'], 'wifi')
            self.assertTrue(host.run_command('devos.demo.run'))
            module = host.modules[0]
            self.assertIn('ran', module.STATE)
            host.unload()
            self.assertIn('deactivated', module.STATE)
            self.assertEqual((host.commands, host.tray), ([], []))

    def test_broken_extension_is_reported_not_fatal(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write(directory, manifest=dict(GOOD_MANIFEST, version='oops'))
            host = extensions.Host(provides()).load([directory])
            self.assertEqual(host.loaded, [])
            self.assertEqual(len(host.report), 1)
            self.assertIn('version', host.report[0]['error'])

            bad_code = Path(directory) / 'crash' / 'extension.py'
            bad_code.parent.mkdir()
            (bad_code.parent / 'manifest.json').write_text(json.dumps(GOOD_MANIFEST))
            bad_code.write_text('raise RuntimeError("boom")\n')
            host = extensions.Host(provides()).load([directory])
            self.assertEqual(host.loaded, [])
            self.assertEqual(len(host.report), 2)

    def test_tray_icons_are_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'demo'
            path.mkdir()
            (path / 'manifest.json').write_text(json.dumps(GOOD_MANIFEST))
            (path / 'extension.py').write_text(
                'def activate(api):\n'
                '    api.register_tray("bad", "nonexistent-icon")\n')
            host = extensions.Host(provides()).load([directory])
            self.assertEqual(host.tray, [])
            self.assertIn('icon', host.report[0]['error'])


class PainterAndWidgets(unittest.TestCase):
    class Stub:
        def __init__(self, chain):
            self.chain = chain

        def __getattr__(self, name):
            def call(*arguments):
                self.chain.append((name,) + arguments)
            return call

    def test_painter_helpers_translate_to_cairo_calls(self):
        import ctypes as c
        chain = []
        stub = self.Stub(chain)
        painter = extensions.Painter(stub, None, 100, 6, 40, 28,
                                     {'text': (1, 1, 1), 'accent': (0, 1, 0.6)}, None)
        painter.text('hi', 2, 3, 'text')
        painter.rect(0, 0, 10, 10, 'accent', radius=2)
        painter.line(0, 0, 5, 5)
        painter.circle(4, 4, 2)
        calls = [name for name, *_ in chain]
        self.assertIn('show_text', calls)
        self.assertIn('rounded', calls)
        self.assertIn('stroke', calls)
        self.assertIn('arc', calls)
        moved = [arguments for name, *arguments in chain if name == 'move_to']
        self.assertIn([None, 102.0, 9.0], moved)
        colors = [arguments for name, *arguments in chain if name == 'set_rgba']
        self.assertIn([None, 0, 1, 0.6, 1.0], colors)

    def test_widget_panel_and_override_validation(self):
        host = extensions.Host(provides())
        host.add_widget('devos.demo', 'left', 64, lambda painter: None, None, 'w')
        self.assertEqual(host.widgets[0]['width'], 64)
        handle = host.add_panel('devos.demo', 'p', 240, 100, lambda painter: None,
                                None, 8)
        self.assertIsInstance(handle, extensions.PanelHandle)
        handle.show()
        self.assertEqual(handle.slot['request'], 'show')
        host.set_clock_override('devos.demo', 120, lambda painter: None)
        self.assertEqual(host.clock_override['width'], 120)
        host.set_hidden('tray', True)
        self.assertEqual(host.hidden, {'tray'})
        host.set_hidden('tray', False)
        self.assertEqual(host.hidden, set())
        for bad in (('middle', 64, lambda p: None), ('left', 4, lambda p: None),
                    ('left', 64, 'nope')):
            with self.assertRaises(ValueError):
                host.add_widget('devos.demo', bad[0], bad[1], bad[2], None, 'w')
        with self.assertRaises(ValueError):
            host.add_panel('devos.demo', 'p', 10, 100, lambda p: None, None, 8)
        with self.assertRaises(ValueError):
            host.set_clock_override('devos.demo', 10, lambda p: None)
        with self.assertRaises(ValueError):
            host.set_hidden('everything', True)


if __name__ == '__main__':
    unittest.main()
