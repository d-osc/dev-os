import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

DEV = [sys.executable, str(Path(__file__).parents[1] / 'tools/dev.py')]

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


class JsProtocol(unittest.TestCase):
    class Recorder:
        def __init__(self):
            self.calls = []

        def __getattr__(self, name):
            def call(*arguments, **keywords):
                self.calls.append((name, arguments, keywords))
            return call

    def test_manifest_accepts_a_javascript_main(self):
        self.assertEqual(extensions.validate(dict(GOOD_MANIFEST, main='extension.js'))
                         ['main'], 'extension.js')
        with self.assertRaises(ValueError):
            extensions.validate(dict(GOOD_MANIFEST, main='extension.rs'))

    def test_ops_validation(self):
        extensions.validate_ops([{'op': 'text', 'value': 'hi', 'x': 1, 'y': 2}])
        for bad in ('nope', [[]], [{'op': 'hexagon'}],
                    [{'op': 'rect', 'x': 0, 'y': 0, 'w': 99**9, 'h': 1}],
                    [{'op': 'rect', 'color': 'mauve'}],
                    [{'op': 'text', 'value': 'x' * 81}],
                    [{'op': 'text', 'value': 5}],
                    [{'op': 'icon', 'icon': 7}]):
            with self.assertRaises(ValueError):
                extensions.validate_ops(bad)

    def test_messages_register_update_and_dispatch(self):
        notes = []
        themes = []
        host = extensions.Host({'settings': lambda: {}, 'theme': lambda: {'name': 'x'},
                                'screen': lambda: [800, 600],
                                'notify': lambda *a: notes.append(a),
                                'set_theme': themes.append})
        session = extensions.JsSession('devos.js', host, 'runner.js', '.')
        session.handle_line('{"type":"command","id":"c1","title":"Run","detail":"d"}')
        self.assertEqual(host.commands[0]['id'], 'c1')
        session.handle_line('{"type":"widget","id":"w1","zone":"left","width":80,'
                            '"ops":[{"op":"rect","x":0,"y":0,"w":80,"h":40,'
                            '"color":"blue"}],"click":true}')
        self.assertEqual(host.widgets[0]['width'], 80)
        first = self.Recorder()
        host.widgets[0]['draw'](first)
        self.assertTrue(any(name == 'rect' for name, *_ in first.calls))
        session.handle_line('{"type":"update","target":"widget","id":"w1",'
                            '"ops":[{"op":"text","value":"hi","x":1,"y":2}]}')
        second = self.Recorder()
        host.widgets[0]['draw'](second)
        self.assertTrue(any(name == 'text' for name, *_ in second.calls))
        session.handle_line('{"type":"panel","id":"p1","width":200,"height":80,"x":8,'
                            '"ops":[]}')
        session.handle_line('{"type":"panel_cmd","id":"p1","cmd":"show"}')
        self.assertEqual(host.panels[0].slot['request'], 'show')
        session.handle_line('{"type":"clock_override","width":120,'
                            '"ops":[{"op":"text","value":"OVR","x":4,"y":24}]}')
        self.assertEqual(host.clock_override['width'], 120)
        session.handle_line('{"type":"clock_restore"}')
        self.assertIsNone(host.clock_override)
        session.handle_line('{"type":"hide","section":"tray"}')
        self.assertIn('tray', host.hidden)
        session.handle_line('{"type":"notify","title":"T","body":"B"}')
        self.assertEqual(notes, [('T', 'B')])
        session.handle_line('{"type":"set_theme","path":"/tmp/x.json"}')
        self.assertEqual(themes, ['/tmp/x.json'])
        session.handle_line('{"type":"ready"}')
        with self.assertRaises(ValueError):
            session.handle_line('{"type":"surprise"}')

    def test_bad_ops_in_a_message_are_rejected(self):
        host = extensions.Host(provides())
        session = extensions.JsSession('devos.js', host, 'runner.js', '.')
        with self.assertRaises(ValueError):
            session.handle_line('{"type":"widget","id":"w2","zone":"left","width":80,'
                                '"ops":[{"op":"hexagon"}]}')


GOOD_SOURCE_CODE = '''
def activate(api):
    api.register_command('devos.demo.run', 'Run demo', lambda: None)
'''


class Lifecycle(unittest.TestCase):
    def write_source(self, directory, code=GOOD_SOURCE_CODE,
                     manifest=None):
        path = Path(directory) / 'source'
        path.mkdir(parents=True)
        (path / 'manifest.json').write_text(json.dumps(manifest or GOOD_MANIFEST))
        (path / 'extension.py').write_text(code)
        return path

    def setUp(self):
        self._previous = os.environ.get(extensions.USER_ENV)
        self.home = tempfile.TemporaryDirectory()
        os.environ[extensions.USER_ENV] = str(Path(self.home.name) / 'extensions')
        self.addCleanup(self.home.cleanup)
        if self._previous is None:
            self.addCleanup(os.environ.pop, extensions.USER_ENV, None)
        else:
            self.addCleanup(os.environ.__setitem__, extensions.USER_ENV, self._previous)

    def dirs(self):
        return extensions.extension_dirs()

    def test_full_lifecycle_with_the_loader(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_source(directory)
            self.assertEqual(extensions.install(source, self.dirs()), 'devos.demo')
            entries = {entry['id']: entry for entry in extensions.scan(self.dirs())}
            self.assertTrue(entries['devos.demo']['disabled'] is False)
            self.assertEqual(entries['devos.demo']['source'], 'user')

            host = extensions.Host(provides()).load(self.dirs())
            self.assertEqual(host.loaded, ['devos.demo'])
            host.unload()

            extensions.set_state('devos.demo', self.dirs(), True)
            entries = {entry['id']: entry for entry in extensions.scan(self.dirs())}
            self.assertTrue(entries['devos.demo']['disabled'])
            host = extensions.Host(provides()).load(self.dirs())
            self.assertEqual(host.loaded, [])          # the loader skips disabled ones
            host.unload()

            extensions.set_state('devos.demo', self.dirs(), False)
            host = extensions.Host(provides()).load(self.dirs())
            self.assertEqual(host.loaded, ['devos.demo'])
            host.unload()

            extensions.uninstall('devos.demo', self.dirs())
            self.assertEqual([entry['id'] for entry in extensions.scan(self.dirs())], [])
            with self.assertRaises(ValueError):
                extensions.uninstall('devos.demo', self.dirs())

    def test_install_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_source(directory)
            self.assertEqual(extensions.install(source, self.dirs()), 'devos.demo')
            with self.assertRaises(ValueError):        # already installed
                extensions.install(source, self.dirs())
        with tempfile.TemporaryDirectory() as directory:
            broken = Path(directory) / 'broken'
            broken.mkdir()
            with self.assertRaises(ValueError):        # no manifest
                extensions.install(broken, self.dirs())
            nested = self.write_source(directory) / 'payload'
            nested.mkdir()
            with self.assertRaises(ValueError):        # subdirectory
                extensions.install(nested.parent, self.dirs())

    def test_system_extensions_cannot_be_uninstalled(self):
        with tempfile.TemporaryDirectory() as directory:
            system = Path(directory) / 'system'
            self.write_source(directory)
            system_source = Path(directory) / 'source'
            system.mkdir()
            shutil.copytree(system_source, system / 'devos.demo')
            previous = os.environ.get(extensions.USER_ENV)
            os.environ[extensions.USER_ENV] = str(Path(directory) / 'empty-user')
            try:
                with self.assertRaises(ValueError) as caught:
                    extensions.uninstall('devos.demo', [Path(directory) / 'empty-user',
                                                        system])
                self.assertIn('system image', str(caught.exception))
            finally:
                os.environ[extensions.USER_ENV] = previous

    def test_cli_manages_extensions(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_source(directory)
            environment = dict(os.environ)
            run = lambda *arguments: subprocess.run(
                DEV + ['ext'] + list(arguments), capture_output=True, text=True,
                env=environment)
            self.assertIn('No extensions installed', run('list').stdout)
            result = run('install', str(source))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Installed devos.demo', result.stdout)
            listing = run('list').stdout
            self.assertIn('devos.demo', listing)
            self.assertIn('enabled', listing)
            self.assertEqual(run('disable', 'devos.demo').returncode, 0)
            self.assertIn('disabled', run('list').stdout)
            self.assertIn('now enabled', run('enable', 'devos.demo').stdout)
            self.assertEqual(run('uninstall', 'devos.demo').returncode, 0)
            self.assertIn('No extensions installed', run('list').stdout)
            self.assertNotEqual(run('disable', 'devos.demo').returncode, 0)
            self.assertNotEqual(run('disable').returncode, 0)


class ZoneLayout(unittest.TestCase):
    def test_widths_fit_as_declared_when_there_is_room(self):
        self.assertEqual(extensions.zone_layout(400, [80, 120]), [80, 120])
        self.assertEqual(extensions.zone_layout(400, []), [])

    def test_overflow_shrinks_proportionally_then_drops(self):
        fitted = extensions.zone_layout(200, [80, 80])
        self.assertEqual(len(fitted), 2)
        visible = [width for width in fitted if width is not None]
        used = sum(visible) + extensions.ZONE_GAP * (len(visible) - 1)
        self.assertLessEqual(used, 200 - extensions.ZONE_PAD)
        self.assertGreaterEqual(min(visible), extensions.ZONE_MINIMUM)
        dropped = extensions.zone_layout(120, [80, 80, 80])
        self.assertIn(None, dropped)
        visible = [width for width in dropped if width is not None]
        self.assertLessEqual(sum(visible)
                             + extensions.ZONE_GAP * (len(visible) - 1),
                             120 - extensions.ZONE_PAD)

    def test_tiny_zone_drops_everything(self):
        self.assertEqual(extensions.zone_layout(50, [80]), [None])
        self.assertEqual(extensions.zone_layout(50, [80, 80]), [None, None])


class Dedup(unittest.TestCase):
    def setUp(self):
        self._previous = os.environ.get(extensions.USER_ENV)
        self.home = tempfile.TemporaryDirectory()
        os.environ[extensions.USER_ENV] = str(Path(self.home.name) / 'user')
        self.addCleanup(self.home.cleanup)
        if self._previous is None:
            self.addCleanup(os.environ.pop, extensions.USER_ENV, None)
        else:
            self.addCleanup(os.environ.__setitem__, extensions.USER_ENV, self._previous)

    def write_copy(self, base, source, version):
        path = Path(base) / 'devos.demo'
        path.mkdir(parents=True)
        (path / 'manifest.json').write_text(json.dumps(
            dict(GOOD_MANIFEST, version=version)))
        (path / 'extension.py').write_text(source)
        return path

    def test_older_system_copy_is_disabled_by_the_newer_user_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            system = self.write_copy(Path(directory) / 'system', GOOD_CODE, '1.0.0')
            user = self.write_copy(Path(self.home.name) / 'user', GOOD_CODE, '2.0.0')
            actions = extensions.resolve_duplicates([user.parent, system.parent])
            self.assertEqual(len(actions), 1)
            self.assertIn('disabled devos.demo 1.0.0 (system copy)', actions[0])
            states = {str(entry['path']): entry['disabled']
                      for entry in extensions.scan([user.parent, system.parent])}
            self.assertFalse(states[str(user)])     # winner stays enabled
            self.assertTrue(states[str(system)])    # older copy is disabled
            host = extensions.Host(provides()).load([user.parent, system.parent])
            self.assertEqual(host.loaded, ['devos.demo'])   # loaded exactly once
            self.assertEqual(len(host.commands), 1)
            host.unload()

    def test_higher_version_wins_even_when_it_is_the_system_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            system = self.write_copy(Path(directory) / 'system', GOOD_CODE, '3.0.0')
            user = self.write_copy(Path(self.home.name) / 'user', GOOD_CODE, '2.0.0')
            actions = extensions.resolve_duplicates([user.parent, system.parent])
            self.assertIn('disabled devos.demo 2.0.0 (user copy)', actions[0])
            host = extensions.Host(provides()).load([user.parent, system.parent])
            self.assertEqual(host.loaded, ['devos.demo'])
            self.assertEqual(len(host.commands), 1)
            host.unload()

    def test_cli_dedup_reports_and_settles(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write_copy(Path(directory) / 'usr/share/devos/extensions',
                            GOOD_CODE, '1.0.0')
            self.write_copy(Path(self.home.name) / 'user', GOOD_CODE, '1.0.0')
            environment = dict(os.environ)
            first = subprocess.run(DEV + ['--root', directory, 'ext', 'dedup'],
                                   capture_output=True, text=True, env=environment)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn('disabled devos.demo', first.stdout)
            again = subprocess.run(DEV + ['--root', directory, 'ext', 'dedup'],
                                   capture_output=True, text=True, env=environment)
            self.assertIn('No duplicate extensions found', again.stdout)


if __name__ == '__main__':
    unittest.main()
