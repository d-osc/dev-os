"""Package replacement, rollback and abrupt-exit recovery in disposable roots."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

CORE = Path(__file__).parents[1] / 'tools/dev.py'
SPEC = importlib.util.spec_from_file_location('dev_upgrade_test', CORE)
dev = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dev)

CHILD = '''import importlib.util, os, pathlib, sys
spec = importlib.util.spec_from_file_location('dev', sys.argv[1])
dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev)
def crash(label):
    if label == sys.argv[5]:
        os._exit(77)
dev.transaction_checkpoint = crash
root = pathlib.Path(sys.argv[2])
if sys.argv[3] == 'recover':
    with dev.database(root):
        pass
else:
    with dev.database(root) as (db, path):
        dev.install_locked(root, sys.argv[4], db, path, replacement='upgrade')
'''


@unittest.skipUnless(importlib.util.find_spec('packaging'), 'Upgrade tests require packaging dependency')
class Upgrades(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.old_files = {'common': 'old', 'removed': 'old-only', 'unchanged': 'same'}
        self.new_files = {'added': 'new-only', 'common': 'new', 'unchanged': 'same'}
        self.old = self.make_package('1', self.old_files)
        self.new = self.make_package('2', self.new_files)
        self.root = self.base / 'root'

    def make_package(self, version, files):
        source = self.base / ('source-' + version)
        (source / 'payload/usr/bin').mkdir(parents=True)
        for name, text in files.items():
            (source / 'payload/usr/bin' / name).write_text(text)
        (source / 'manifest.json').write_text(json.dumps({
            'name': 'hello', 'version': version, 'arch': 'all',
            'executables': ['usr/bin/' + name for name in files]}))
        package = self.base / ('hello-' + version + '.dpk')
        dev.build(source, package)
        return package

    def upgrade(self, root=None, archive=None):
        root = root or self.root
        with dev.database(root) as (db, path):
            dev.install_locked(root, archive or self.new, db, path, replacement='upgrade')

    def state(self, root, version):
        with dev.database(root) as (db, _):
            self.assertEqual(db['hello']['version'], version)
        expected = self.old_files if version == '1' else self.new_files
        actual = {p.name: p.read_text() for p in (root / 'usr/bin').iterdir() if p.is_file()}
        self.assertEqual(actual, expected)
        self.assertFalse((root / 'var/lib/dev/transaction').exists())
        self.assertFalse(list(root.rglob('.dev-*')))

    def crash(self, root, point, operation='upgrade'):
        result = subprocess.run([sys.executable, '-c', CHILD, str(CORE), str(root), operation,
                                 str(self.new), point], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 77, result.stdout + result.stderr)

    def test_upgrade_and_explicit_rollback(self):
        dev.install(self.root, self.old)
        self.upgrade()
        self.state(self.root, '2')
        dev.rollback(self.root, 'hello')
        self.state(self.root, '1')

    def test_crashes_before_and_after_commit(self):
        points = ['prepared', 'journal', 'copy:added', 'publish:added', 'file:0',
                  'replace-copy:common', 'replace-publish:common', 'file:1', 'file:2',
                  'file:3', 'commit', 'detached']
        for index, point in enumerate(points):
            with self.subTest(point=point):
                root = self.base / str(index)
                dev.install(root, self.old)
                self.crash(root, point)
                self.state(root, '2' if point in ('commit', 'detached') else '1')

    def test_recovery_can_be_killed_while_restoring(self):
        dev.install(self.root, self.old)
        self.crash(self.root, 'file:3')
        self.crash(self.root, 'replace-copy:common', 'recover')
        self.crash(self.root, 'replace-publish:common', 'recover')
        self.state(self.root, '1')

    def test_modified_file_blocks_upgrade(self):
        dev.install(self.root, self.old)
        (self.root / 'usr/bin/common').write_text('user edit')
        with self.assertRaisesRegex(ValueError, 'modified file'):
            self.upgrade()
        self.assertEqual((self.root / 'usr/bin/common').read_text(), 'user edit')

    def test_post_crash_user_edit_is_preserved(self):
        dev.install(self.root, self.old)
        self.crash(self.root, 'file:3')
        (self.root / 'usr/bin/common').write_text('user edit')
        with self.assertRaisesRegex(ValueError, 'preserve modified file'):
            with dev.database(self.root):
                pass
        self.assertEqual((self.root / 'usr/bin/common').read_text(), 'user edit')

    def test_database_failure_rolls_back(self):
        dev.install(self.root, self.old)
        with mock.patch.object(dev, 'save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.upgrade()
        self.state(self.root, '1')

    def test_error_after_commit_keeps_new_state(self):
        dev.install(self.root, self.old)
        original = dev.save
        def fail_after(db, path):
            original(db, path)
            raise OSError('after commit')
        with mock.patch.object(dev, 'save', side_effect=fail_after):
            with self.assertRaises(OSError):
                self.upgrade()
        self.state(self.root, '2')

    def test_upgrade_cannot_silently_downgrade(self):
        dev.install(self.root, self.new)
        with self.assertRaisesRegex(ValueError, 'downgrade'):
            self.upgrade(archive=self.old)
        self.state(self.root, '2')


if __name__ == '__main__':
    unittest.main()
