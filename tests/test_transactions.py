"""Run destructive fault injection only in disposable package roots."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

CORE = Path(__file__).parents[1] / 'tools/dev.py'
SPEC = importlib.util.spec_from_file_location('dev_transaction_test', CORE)
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
if sys.argv[3] == 'install':
    dev.install(root, sys.argv[4])
elif sys.argv[3] == 'remove':
    dev.remove(root, 'sample')
else:
    with dev.database(root):
        pass
'''


class Transactions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'root'
        src = self.base / 'src'
        (src / 'payload/usr/bin').mkdir(parents=True)
        (src / 'payload/usr/bin/first').write_bytes(b'first content')
        (src / 'payload/usr/bin/second').write_bytes(b'second content')
        (src / 'manifest.json').write_text(json.dumps({
            'name': 'sample', 'version': '1', 'arch': 'all',
            'executables': ['usr/bin/first', 'usr/bin/second']}))
        self.pkg = self.base / 'sample.dpk'
        dev.build(src, self.pkg)

    def crash(self, operation, checkpoint, root=None):
        result = subprocess.run([sys.executable, '-c', CHILD, str(CORE),
                                 str(root or self.root), operation, str(self.pkg), checkpoint],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 77, result.stdout + result.stderr)

    def assert_state(self, root, installed):
        with dev.database(root) as (db, _):
            self.assertEqual('sample' in db, installed)
        self.assertFalse((root / 'var/lib/dev/transaction').exists())
        self.assertFalse(list(root.rglob('.dev-*')))
        state = root / 'var/lib/dev'
        for pattern in ('prepare-*', 'unpack-*', 'gc-*'):
            self.assertFalse(list(state.glob(pattern)))
        for name in ('first', 'second'):
            path = root / 'usr/bin' / name
            self.assertEqual(path.exists(), installed)
            if installed:
                self.assertEqual(path.read_bytes(), (name + ' content').encode())

    def test_install_crashes_recover_before_or_after_commit(self):
        points = ['prepared', 'journal', 'copy:first', 'publish:first', 'file:0',
                  'copy:second', 'publish:second', 'file:1', 'commit', 'detached']
        for i, point in enumerate(points):
            with self.subTest(point=point):
                root = self.base / str(i)
                self.crash('install', point, root)
                self.assert_state(root, point in ('commit', 'detached'))

    def test_remove_crashes_recover_before_or_after_commit(self):
        for i, point in enumerate(['prepared', 'journal', 'file:0', 'file:1', 'commit', 'detached']):
            with self.subTest(point=point):
                root = self.base / str(i)
                dev.install(root, self.pkg)
                self.crash('remove', point, root)
                self.assert_state(root, point not in ('commit', 'detached'))

    def test_recovery_can_itself_be_interrupted(self):
        for operation in ('install', 'remove'):
            with self.subTest(operation=operation):
                root = self.base / operation
                if operation == 'remove':
                    dev.install(root, self.pkg)
                self.crash(operation, 'file:1', root)
                self.crash('recover', 'recover:0', root)
                self.assert_state(root, operation == 'remove')

    def test_partial_restore_publish_can_be_retried(self):
        dev.install(self.root, self.pkg)
        self.crash('remove', 'file:1')
        self.crash('recover', 'copy:first')
        self.crash('recover', 'publish:first')
        self.assert_state(self.root, True)

    def test_preserve_user_changes_after_interruption(self):
        self.crash('install', 'file:0')
        path = self.root / 'usr/bin/first'
        path.write_text('user change')
        with self.assertRaisesRegex(ValueError, 'preserve modified file'):
            with dev.database(self.root):
                pass
        self.assertEqual(path.read_text(), 'user change')
        self.assertTrue((self.root / 'var/lib/dev/transaction/journal.json').exists())

    def test_preserve_replacement_even_when_bytes_match(self):
        self.crash('install', 'file:0')
        path = self.root / 'usr/bin/first'
        path.unlink()
        path.write_bytes(b'first content')
        path.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'preserve unowned file'):
            with dev.database(self.root):
                pass
        self.assertEqual(path.read_bytes(), b'first content')

    def test_failure_while_copying_scratch_leaves_no_partial_file(self):
        original = dev.durable_copy
        def no_space(src, dest, mode):
            if dest.name.startswith('.dev-'):
                dev.durable_mkdir(dest.parent)
                dest.write_bytes(b'partial')
                raise OSError('simulated disk full')
            return original(src, dest, mode)
        with mock.patch.object(dev, 'durable_copy', side_effect=no_space):
            with self.assertRaisesRegex(OSError, 'disk full'):
                dev.install(self.root, self.pkg)
        self.assert_state(self.root, False)

    def test_preserve_conflicting_file_during_remove_recovery(self):
        dev.install(self.root, self.pkg)
        self.crash('remove', 'file:0')
        path = self.root / 'usr/bin/first'
        path.write_text('user replacement')
        with self.assertRaisesRegex(ValueError, 'preserve modified file'):
            with dev.database(self.root):
                pass
        self.assertEqual(path.read_text(), 'user replacement')

    def test_error_after_database_commit_keeps_committed_files(self):
        original = dev.save
        def committed_then_error(db, path):
            original(db, path)
            raise OSError('simulated error after commit')
        with mock.patch.object(dev, 'save', side_effect=committed_then_error):
            with self.assertRaises(OSError):
                dev.install(self.root, self.pkg)
        self.assert_state(self.root, True)

    def test_corrupt_backup_fails_without_deleting_remaining_files(self):
        dev.install(self.root, self.pkg)
        self.crash('remove', 'file:0')
        backup = self.root / 'var/lib/dev/transaction/payload/usr/bin/first'
        backup.write_text('corrupt')
        with self.assertRaisesRegex(ValueError, 'corrupt recovery backup'):
            with dev.database(self.root):
                pass
        self.assertEqual((self.root / 'usr/bin/second').read_bytes(), b'second content')


if __name__ == '__main__':
    unittest.main()
