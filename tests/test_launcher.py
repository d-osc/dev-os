import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / 'tools' / file)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


dev = load('launcher_dev_test', 'dev.py')
runtime = load('launcher_runtime_test', 'dev_runtime.py')


class Launcher(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source, self.root = self.base / 'source', self.base / 'root'
        self.entry = 'opt/apps/launcher-demo/window.sh'
        self.icon = 'opt/apps/launcher-demo/icon.svg'
        path = self.source / 'payload' / self.entry
        path.parent.mkdir(parents=True); path.write_text('exit 0\n')
        (self.source / 'payload' / self.icon).write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        self.manifest = {'manifest_version': 2, 'name': 'launcher-demo', 'version': '1', 'arch': 'all',
                         'permissions': ['window'], 'window': {'type': 'desktop', 'runtime': 'sh', 'entry_point': self.entry},
                         'launcher': {'name': 'Dev แอป', 'comment': 'Open app', 'icon': self.icon, 'categories': ['Utility']}}
        self.package = self.base / 'demo.dpk'
        self.desktop = self.root / 'usr/share/applications/devos-launcher-demo.desktop'

    def build(self):
        (self.source / 'manifest.json').write_text(json.dumps(self.manifest))
        dev.build(self.source, self.package)

    def test_installed_desktop_tracks_hash_and_removes(self):
        self.build(); dev.install(self.root, self.package)
        text = self.desktop.read_text(encoding='utf-8')
        self.assertIn('Name=Dev\\sแอป\n', text)
        self.assertIn('Exec=/usr/bin/dev launch launcher-demo\n', text)
        self.assertIn('Terminal=true\n', text)
        self.assertNotIn('--allow', text)
        self.assertIn('Icon=/'+self.icon, text)
        db = json.loads((self.root / 'var/lib/dev/installed.json').read_text())
        dev.manifest_check(db['launcher-demo'])
        self.assertIn('usr/share/applications/devos-launcher-demo.desktop', db['launcher-demo']['installed_launchers'])
        dev.remove(self.root, 'launcher-demo'); self.assertFalse(self.desktop.exists())

    def test_launcher_rejects_injection_missing_window_and_icon(self):
        original = copy.deepcopy(self.manifest)
        for config in ({'name': 'App\nExec=bad'}, {'comment': '\x1b[2J'}, {'icon': 'opt/missing'},
                       {'icon': '../escape'}, {'categories': ['Utility;System']}, {'categories': []},
                       {'exec': 'sh -c anything'}, {'terminal': False}, {'name': ''}):
            self.manifest = dict(original, launcher=config)
            with self.subTest(config=config), self.assertRaises(ValueError): self.build()
        self.manifest = copy.deepcopy(original); del self.manifest['window']
        with self.assertRaisesRegex(ValueError, 'requires a format 2 window'): self.build()
        self.manifest = copy.deepcopy(original); self.manifest['installed_launchers'] = {}
        with self.assertRaisesRegex(ValueError, 'reserved'): self.build()

    def test_conflicts_preserve_existing_desktop(self):
        self.build(); self.desktop.parent.mkdir(parents=True); self.desktop.write_text('existing')
        with self.assertRaisesRegex(ValueError, 'conflict'): dev.install(self.root, self.package)
        self.assertEqual(self.desktop.read_text(), 'existing')
        self.assertFalse((self.root / self.entry).exists())

    def test_launcher_execution_fields_are_rejected(self):
        for key, value in (('runtime', 'sh'), ('entry_point', self.entry), ('args', [])):
            self.manifest['launcher'][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'under window, not launcher'):
                self.build()
            del self.manifest['launcher'][key]

    def test_window_remains_the_validated_execution_config(self):
        self.manifest['window']['runtime'] = 'native'
        with self.assertRaisesRegex(ValueError, 'Native entry point'): self.build()
        self.manifest['executables'] = [self.entry]
        self.build()
        self.manifest['window']['entry_point'] = 'opt/missing'
        with self.assertRaisesRegex(ValueError, 'Entry point'): self.build()

    def test_modified_desktop_blocks_removal(self):
        self.build(); dev.install(self.root, self.package); self.desktop.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'modified'): dev.remove(self.root, 'launcher-demo')
        self.assertTrue((self.root / self.entry).exists())

    def test_rollback_removes_desktop(self):
        self.build()
        with mock.patch.object(dev, 'save', side_effect=OSError('failed')):
            with self.assertRaises(OSError): dev.install(self.root, self.package)
        self.assertFalse(self.desktop.exists()); self.assertFalse((self.root / self.entry).exists())

    def test_permissions_require_explicit_consent(self):
        with mock.patch.object(runtime.sys.stdin, 'isatty', return_value=True), mock.patch.object(runtime.sys, 'stdout', io.StringIO()):
            with mock.patch('builtins.input', return_value='no'):
                self.assertIsNone(runtime.launcher_grants(self.manifest, None))
            with mock.patch('builtins.input', return_value='yes'):
                self.assertEqual(runtime.launcher_grants(self.manifest, None), 'window')
        with mock.patch.object(runtime.sys.stdin, 'isatty', return_value=False):
            with self.assertRaisesRegex(ValueError, 'interactive terminal'):
                runtime.launcher_grants(self.manifest, None)
        self.assertEqual(runtime.launcher_grants(self.manifest, 'window'), 'window')
        with self.assertRaises(ValueError): runtime.launcher_grants(self.manifest, '')

    def test_dispatch_opens_window_only_after_consent(self):
        for allowed in (None, 'window'):
            args = SimpleNamespace(command='launch', name='launcher-demo', allow=None)
            with mock.patch.object(runtime.sys, 'platform', 'linux'), \
                 mock.patch.object(runtime.os, 'getuid', return_value=1000, create=True), \
                 mock.patch.object(runtime, 'locations', return_value=(self.base/'socket', self.base/'data')), \
                 mock.patch.object(runtime, 'metadata', return_value=self.manifest), \
                 mock.patch.object(runtime, 'launcher_grants', return_value=allowed), \
                 mock.patch.object(runtime, 'runtime_command'), \
                 mock.patch.object(runtime, 'application') as app:
                app.return_value.__enter__.return_value.wait.return_value = 0
                self.assertEqual(runtime.dispatch(args, self.root, dev), 1 if allowed is None else 0)
                if allowed is None: app.assert_not_called()
                else: self.assertEqual(app.call_args.args[2], 'window')

    def test_launcher_and_open_use_same_window_and_preserve_metadata(self):
        self.manifest['window']['args'] = ['--mode', 'test value']
        before = copy.deepcopy(self.manifest)
        with mock.patch.object(runtime.sys, 'platform', 'linux'), \
             mock.patch.object(runtime.os, 'getuid', return_value=1000, create=True), \
             mock.patch.object(runtime, 'locations', return_value=(self.base/'socket', self.base/'data')), \
             mock.patch.object(runtime, 'metadata', return_value=self.manifest), \
             mock.patch.object(runtime, 'runtime_command') as preflight, \
             mock.patch.object(runtime, 'application') as app:
            app.return_value.__enter__.return_value.wait.return_value = 0
            for command, point in (('launch', self.entry), ('open', self.entry)):
                args = SimpleNamespace(command=command, name='launcher-demo', allow='window')
                self.assertEqual(runtime.dispatch(args, self.root, dev), 0)
                selected = app.call_args.args[1]['window']
                self.assertEqual(selected['entry_point'], point)
                self.assertEqual(selected['runtime'], 'sh')
                self.assertEqual(selected['args'], ['--mode', 'test value'])
                self.assertEqual(preflight.call_args.args[0], selected)
            self.assertEqual(self.manifest, before)
