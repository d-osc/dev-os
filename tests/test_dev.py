import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('dev', Path(__file__).parents[1] / 'tools/dev.py')
dev = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dev)


class Packages(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'root'
        self.src = self.base / 'source'
        self.file = self.src / 'payload/usr/bin/hello'
        self.file.parent.mkdir(parents=True)
        self.file.write_text('hello')
        (self.src / 'manifest.json').write_text(json.dumps({
            'name': 'hello', 'version': '1', 'arch': 'all',
            'executables': ['usr/bin/hello']}))
        self.pkg = self.base / 'hello.dpk'
        dev.build(self.src, self.pkg)

    def test_manifest_is_first_and_source_is_preserved(self):
        source = json.loads((self.src / 'manifest.json').read_text())
        self.assertNotIn('files', source)
        with tarfile.open(self.pkg, 'r:gz') as tar:
            first = tar.next()
            self.assertEqual(first.name, 'manifest.json')
            manifest = json.load(tar.extractfile(first))
        self.assertEqual(manifest['name'], source['name'])
        self.assertEqual(manifest['format'], 1)
        self.assertEqual(manifest['files']['usr/bin/hello']['sha256'], dev.digest(self.file))

    def test_manifest_is_required_even_with_package_json(self):
        (self.src / 'manifest.json').rename(self.src / 'package.json')
        output = self.base / 'missing-manifest.dpk'
        with self.assertRaisesRegex(ValueError, 'Missing manifest.json'):
            dev.build(self.src, output)
        self.assertFalse(output.exists())

    def test_chrome_style_metadata_roundtrip(self):
        path = self.src / 'manifest.json'
        manifest = json.loads(path.read_text())
        icon = self.src / 'payload/usr/share/hello/icon.svg'
        icon.parent.mkdir(parents=True)
        icon.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        manifest.update(manifest_version=1, display_name='Hello Tool',
                        icons={'128': 'usr/share/hello/icon.svg'})
        path.write_text(json.dumps(manifest))
        dev.build(self.src, self.pkg)
        dev.install(self.root, self.pkg)
        db = json.loads((self.root / 'var/lib/dev/installed.json').read_text())
        self.assertEqual(db['hello']['display_name'], 'Hello Tool')
        self.assertEqual(db['hello']['icons'], manifest['icons'])
        self.assertTrue((self.root / 'usr/share/hello/icon.svg').is_file())

    def test_unsupported_or_broken_manifest_metadata(self):
        path = self.src / 'manifest.json'
        original = json.loads(path.read_text())
        for update, message in (
            ({'manifest_version': 3}, 'manifest_version'),
            ({'manifest_version': True}, 'manifest_version'),
            ({'icons': {'128': 'usr/share/missing.png'}}, 'Icon is missing'),
            ({'icons': {'128': '../outside.png'}}, 'Unsafe package path'),
            ({'executables': ['usr/bin/missing']}, 'Executable is missing'),
            ({'permissions': ['network']}, 'require manifest_version 2'),
            ({'display_name': []}, 'display_name'),
        ):
            with self.subTest(update=update):
                path.write_text(json.dumps(dict(original, **update)))
                with self.assertRaisesRegex(ValueError, message):
                    dev.build(self.src, self.base / 'invalid.dpk')

    def test_install_remove(self):
        dev.install(self.root, self.pkg)
        self.assertEqual((self.root / 'usr/bin/hello').read_text(), 'hello')
        dev.remove(self.root, 'hello')
        self.assertFalse((self.root / 'usr/bin/hello').exists())

    def test_tar_gz_build_install_remove(self):
        archive = self.base / 'hello package.tar.gz'
        dev.build(self.src, archive)
        dev.install(self.root, archive)
        self.assertEqual((self.root / 'usr/bin/hello').read_text(), 'hello')
        db = json.loads((self.root / 'var/lib/dev/installed.json').read_text())
        self.assertIn('hello', db)
        dev.remove(self.root, 'hello')
        self.assertFalse((self.root / 'usr/bin/hello').exists())

    def test_tar_gz_checksum_failure_writes_nothing(self):
        self.rewrite(lambda m, d: (m, b'wrong' if m.name.startswith('payload/') else d))
        archive = self.pkg.with_suffix('.tar.gz')
        self.pkg.rename(archive)
        with self.assertRaisesRegex(ValueError, 'Checksum'):
            dev.install(self.root, archive)
        self.assertFalse((self.root / 'usr').exists())

    def test_tar_gz_traversal_is_rejected(self):
        def unsafe(member, data):
            if member.name.startswith('payload/'):
                member.name = 'payload/usr/../../escape'
            return member, data
        self.rewrite(unsafe)
        archive = self.pkg.with_suffix('.tar.gz')
        self.pkg.rename(archive)
        with self.assertRaisesRegex(ValueError, 'Unsafe package path'):
            dev.install(self.root, archive)
        self.assertFalse((self.root / 'usr').exists())
        self.assertFalse((self.base / 'escape').exists())

    def test_generic_tar_gz_imports_data_without_command(self):
        archive = self.base / 'source.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            member = tarfile.TarInfo('source/README.md')
            member.size = 5
            tar.addfile(member, io.BytesIO(b'hello'))
        dev.install(self.root, archive)
        self.assertEqual((self.root / 'opt/source/README.md').read_text(), 'hello')
        self.assertFalse((self.root / 'usr').exists())
        dev.remove(self.root, 'source')
        self.assertFalse((self.root / 'opt/source/README.md').exists())

    def plain_archive(self, entries, filename='my-app-1.2.3.tar.gz'):
        archive = self.base / filename
        with tarfile.open(archive, 'w:gz') as tar:
            for name, data, mode in entries:
                member = tarfile.TarInfo(name)
                member.mode = mode
                member.size = len(data)
                tar.addfile(member, io.BytesIO(data))
        return archive

    def test_auto_tarball_identity_command_and_remove(self):
        archive = self.plain_archive([
            ('release/bin/my-app', b'#!/bin/sh\necho hello\n', 0o755),
            ('release/data.txt', b'data', 0o644)])
        dev.install(self.root, archive)
        self.assertEqual((self.root / 'usr/bin/my-app').read_text(),
                         '#!/bin/sh\nexec /opt/my-app/bin/my-app "$@"\n')
        manifest = json.loads((self.root / 'var/lib/dev/installed.json').read_text())['my-app']
        self.assertEqual(manifest['version'], '1.2.3')
        self.assertEqual(manifest['auto_command'], 'my-app')
        dev.remove(self.root, 'my-app')
        self.assertFalse((self.root / 'usr/bin/my-app').exists())
        self.assertFalse((self.root / 'opt/my-app/data.txt').exists())

    def test_auto_tarball_does_not_guess_ambiguous_or_source_commands(self):
        for entries in (
            [('release/a', b'#!/bin/sh\n', 0o755), ('release/b', b'#!/bin/sh\n', 0o755)],
            [('release/my-app', b'#!/bin/sh\n', 0o755), ('release/Makefile', b'all:', 0o644)],
            [('release/install.sh', b'#!/bin/sh\nexit 99\n', 0o755)],
        ):
            with self.subTest(entries=entries):
                dev.install(self.root, self.plain_archive(entries))
                self.assertFalse((self.root / 'usr/bin/my-app').exists())
                dev.remove(self.root, 'my-app')

    def test_auto_tarball_rejects_unsafe_members(self):
        for name in ('../escape', '/etc/passwd', 'root/../../escape', 'root\\escape'):
            with self.subTest(name=name):
                archive = self.plain_archive([(name, b'bad', 0o644)])
                with self.assertRaisesRegex(ValueError, 'Unsafe tarball path'):
                    dev.install(self.root, archive)
                self.assertFalse((self.root / 'opt').exists())
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE):
            archive = self.base / 'link.tar.gz'
            with tarfile.open(archive, 'w:gz') as tar:
                member = tarfile.TarInfo('bad'); member.type = kind; member.linkname = '/etc/passwd'
                tar.addfile(member)
            with self.assertRaisesRegex(ValueError, 'no links'):
                dev.install(self.root, archive)

    def test_auto_tarball_refuses_conflict_and_preserves_existing_command(self):
        existing = self.root / 'usr/bin/my-app'
        existing.parent.mkdir(parents=True); existing.write_text('existing')
        archive = self.plain_archive([('release/my-app', b'#!/bin/sh\n', 0o755)])
        with self.assertRaisesRegex(ValueError, 'conflict'):
            dev.install(self.root, archive)
        self.assertEqual(existing.read_text(), 'existing')
        self.assertFalse((self.root / 'opt/my-app').exists())

    def test_auto_tarball_never_bypasses_misordered_manifest(self):
        archive = self.plain_archive([('readme', b'text', 0o644), ('manifest.json', b'{}', 0o644)])
        with self.assertRaisesRegex(ValueError, 'must be the first'):
            dev.install(self.root, archive)

    def test_plain_tarball_not_accepted_by_strict_sdk_reader(self):
        archive = self.plain_archive([('release/data', b'data', 0o644)])
        with self.assertRaisesRegex(ValueError, 'Invalid manifest'):
            dev.unpack(archive, self.base / 'stage')

    @unittest.skipIf(os.name == 'nt', 'POSIX permission bits required')
    def test_database_is_readable_by_non_root_users(self):
        dev.install(self.root, self.pkg)
        mode = (self.root / 'var/lib/dev/installed.json').stat().st_mode & 0o777
        self.assertEqual(mode, 0o644)

    def test_conflict_preserves_file(self):
        path = self.root / 'usr/bin/hello'
        path.parent.mkdir(parents=True)
        path.write_text('existing')
        with self.assertRaisesRegex(ValueError, 'conflict'):
            dev.install(self.root, self.pkg)
        self.assertEqual(path.read_text(), 'existing')

    def test_modified_file_is_not_removed(self):
        dev.install(self.root, self.pkg)
        (self.root / 'usr/bin/hello').write_text('modified')
        with self.assertRaisesRegex(ValueError, 'modified'):
            dev.remove(self.root, 'hello')

    def rewrite(self, transform):
        with tarfile.open(self.pkg) as tar:
            entries = [(x, tar.extractfile(x).read()) for x in tar]
        with tarfile.open(self.pkg, 'w:gz') as tar:
            for member, data in entries:
                member, data = transform(member, data)
                member.size = len(data)
                tar.addfile(member, io.BytesIO(data))

    def test_checksum_failure_writes_nothing(self):
        self.rewrite(lambda m, d: (m, b'wrong' if m.name.startswith('payload/') else d))
        with self.assertRaisesRegex(ValueError, 'Checksum'):
            dev.install(self.root, self.pkg)
        self.assertFalse((self.root / 'usr').exists())

    def test_traversal_is_rejected(self):
        for name in ('../escape', '/etc/passwd', 'usr/../../escape',
                     'usr\\bin\\escape', 'usr//bin/escape', 'usr/bin/dev', 'C:/escape'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                dev.safe_path(name)

    def test_archive_symlink_is_rejected(self):
        def change(m, d):
            if m.name.startswith('payload/'):
                m.type, m.linkname = tarfile.SYMTYPE, '/etc/passwd'
                d = b''
            return m, d
        self.rewrite(change)
        with self.assertRaisesRegex(ValueError, 'regular'):
            dev.install(self.root, self.pkg)

    def test_symlink_destination(self):
        self.root.mkdir()
        outside = self.base / 'outside'
        outside.mkdir()
        try:
            (self.root / 'usr').symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Host does not permit symlinks')
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            dev.install(self.root, self.pkg)
        self.assertEqual(list(outside.iterdir()), [])

    def test_database_failure_rolls_back_install(self):
        with mock.patch.object(dev, 'save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                dev.install(self.root, self.pkg)
        self.assertFalse((self.root / 'usr/bin/hello').exists())

    def test_database_failure_restores_remove(self):
        dev.install(self.root, self.pkg)
        with mock.patch.object(dev, 'save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                dev.remove(self.root, 'hello')
        self.assertEqual((self.root / 'usr/bin/hello').read_text(), 'hello')

    def test_lock(self):
        with dev.database(self.root):
            with self.assertRaisesRegex(ValueError, 'locked'):
                dev.install(self.root, self.pkg)

    def test_lock_released_after_process_killed(self):
        script = '''import importlib.util, pathlib, sys, time
spec = importlib.util.spec_from_file_location('dev', sys.argv[1])
dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev)
with dev.database(pathlib.Path(sys.argv[2])):
    print('locked', flush=True)
    time.sleep(30)
'''
        process = subprocess.Popen([sys.executable, '-u', '-c', script,
                                    str(Path(dev.__file__).resolve()), str(self.root)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), 'locked')
            with self.assertRaisesRegex(ValueError, 'locked'):
                dev.install(self.root, self.pkg)
            process.kill()
            process.communicate(timeout=10)
            dev.install(self.root, self.pkg)
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)

    def test_legacy_lock_is_not_silently_removed(self):
        state = self.root / 'var/lib/dev'
        state.mkdir(parents=True)
        (state / 'lock').touch()
        with self.assertRaisesRegex(ValueError, 'legacy'):
            dev.install(self.root, self.pkg)
        self.assertTrue((state / 'lock').exists())

    def test_verify_detects_modified_and_missing_files(self):
        dev.install(self.root, self.pkg)
        dev.verify_installed(self.root, 'hello')
        installed = self.root / 'usr/bin/hello'
        installed.write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            dev.verify_installed(self.root)
        installed.unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            dev.verify_installed(self.root)

    @unittest.skipIf(os.name == 'nt', 'POSIX modes')
    def test_verify_detects_privileged_mode(self):
        dev.install(self.root, self.pkg)
        (self.root / 'usr/bin/hello').chmod(0o4755)
        with self.assertRaisesRegex(ValueError, 'mode mismatch'):
            dev.verify_installed(self.root)


if __name__ == '__main__':
    unittest.main()
