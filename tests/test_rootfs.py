import io
import importlib.util
import json
import hashlib
import os
from pathlib import Path
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('dev_rootfs', Path(__file__).parents[1] / 'tools/dev_rootfs.py')
rootfs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rootfs)


class Rootfs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'rootfs.tar.gz'

    def archive(self, extra=(), overrides=None):
        files = {'etc/passwd': b'root:x:0:0:root:/root:/bin/sh\nnobody:x:65534:65534:nobody:/:/bin/false\n',
                 'etc/shadow': b'root:!:19000:0:99999:7:::\n', 'etc/fstab': b'/dev/root / ext4 defaults 0 1\n',
                 'usr/lib/devos/platform.json': b'{"arch":"x86_64"}',
                 'bin/busybox': b'executable fixture', 'usr/bin/dev': b'#!/bin/sh\n'}
        files.update(overrides or {})
        with tarfile.open(self.path, 'w:gz') as archive:
            for directory in ('etc', 'bin', 'sbin', 'usr', 'usr/bin', 'usr/lib', 'usr/lib/devos', 'home', 'var', 'var/lib', 'var/lib/dev'):
                info = tarfile.TarInfo(directory); info.type = tarfile.DIRTYPE; info.mode = 0o755
                archive.addfile(info)
            for name, data in files.items():
                info = tarfile.TarInfo(name); info.size = len(data)
                info.mode = 0o755 if name in ('bin/busybox', 'usr/bin/dev') else 0o644
                archive.addfile(info, io.BytesIO(data))
            for name, target in (('bin/sh', 'busybox'), ('sbin/init', '/bin/busybox')):
                info = tarfile.TarInfo(name); info.type = tarfile.SYMTYPE; info.linkname = target
                info.mode = 0o777; archive.addfile(info)
            for info, data in extra:
                archive.addfile(info, io.BytesIO(data) if data is not None else None)

    def test_minimal_sanitized_archive_and_root_relative_links(self):
        self.archive()
        result = rootfs.inspect(self.path)
        self.assertEqual(result['files']['sbin/init']['target'], 'bin/busybox')
        self.assertEqual(result['arch'], 'x86_64')

    def test_traversal_duplicate_and_link_parent_are_rejected(self):
        for name in ('../escape', '/etc/outside', 'etc/passwd', 'bin/sh/child'):
            with self.subTest(name=name):
                info = tarfile.TarInfo(name); info.size = 1
                self.archive([(info, b'x')])
                with self.assertRaises(ValueError): rootfs.inspect(self.path)

    def test_devices_and_escaping_links_are_rejected(self):
        for kind, target in ((tarfile.CHRTYPE, ''), (tarfile.SYMTYPE, '../../escape'),
                             (tarfile.LNKTYPE, 'missing')):
            with self.subTest(kind=kind):
                info = tarfile.TarInfo('bin/unsafe'); info.type = kind; info.linkname = target
                self.archive([(info, None)])
                with self.assertRaises(ValueError): rootfs.inspect(self.path)

    def test_personal_accounts_unlocked_passwords_and_installed_state_are_rejected(self):
        for overrides in ({'etc/passwd': b'dev:x:1000:1000:dev:/home/dev:/bin/sh\n'},
                          {'etc/shadow': b'root::19000:0:99999:7:::\n'},
                          {'usr/lib/devos/platform.json': b'{"arch":"aarch64"}'},
                          {'etc/devos-install.json': b'{}'}):
            with self.subTest(overrides=overrides):
                self.archive(overrides=overrides)
                with self.assertRaises(ValueError): rootfs.inspect(self.path)

    def test_large_extension_header_is_rejected_before_body_allocation(self):
        import gzip
        info = tarfile.TarInfo('pax'); info.type = tarfile.XHDTYPE; info.size = 1024**3
        with gzip.open(self.path, 'wb') as stream: stream.write(info.tobuf())
        with self.assertRaisesRegex(ValueError, 'Oversized'):
            rootfs.inspect(self.path)

    def test_extended_security_metadata_is_not_silently_discarded(self):
        info = tarfile.TarInfo('etc/extra'); info.size = 1
        info.pax_headers = {'SCHILY.xattr.security.capability': 'unsupported'}
        self.archive([(info, b'x')])
        with self.assertRaisesRegex(ValueError, 'extended metadata'): rootfs.inspect(self.path)

    def test_hardlink_cannot_change_shared_inode_permissions(self):
        info = tarfile.TarInfo('bin/alias'); info.type = tarfile.LNKTYPE
        info.linkname = 'bin/busybox'; info.mode = 0o4755
        self.archive([(info, None)])
        with self.assertRaisesRegex(ValueError, 'hardlink metadata'): rootfs.inspect(self.path)

    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'geteuid') and os.geteuid() == 0, 'Linux root required')
    def test_authenticated_extraction_preserves_links_modes_and_ownership(self):
        info = tarfile.TarInfo('bin/alias'); info.type = tarfile.LNKTYPE
        info.linkname = 'bin/busybox'; info.mode = 0o755
        self.archive([(info, None)])
        destination = Path(self.temp.name) / 'stage'; destination.mkdir()
        data = self.path.read_bytes()
        rootfs.extract(self.path, destination, length=len(data), sha256=hashlib.sha256(data).hexdigest())
        self.assertEqual((destination / 'bin/busybox').read_bytes(), b'executable fixture')
        self.assertEqual((destination / 'bin/busybox').stat().st_ino, (destination / 'bin/alias').stat().st_ino)
        self.assertEqual(os.readlink(destination / 'sbin/init'), '/bin/busybox')
        self.assertEqual((destination / 'usr/bin/dev').stat().st_mode & 0o7777, 0o755)
        self.assertEqual((destination / 'etc/shadow').stat().st_uid, 0)

    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'geteuid') and os.geteuid() == 0, 'Linux root required')
    def test_bad_auth_archive_or_destination_never_writes_payload(self):
        destination = Path(self.temp.name) / 'stage'; destination.mkdir()
        self.archive()
        data = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'authentication'):
            rootfs.extract(self.path, destination, length=len(data), sha256='0' * 64)
        self.assertEqual(list(destination.iterdir()), [])
        info = tarfile.TarInfo('../outside'); info.size = 1
        self.archive([(info, b'x')]); data = self.path.read_bytes()
        with self.assertRaises(ValueError):
            rootfs.extract(self.path, destination, length=len(data), sha256=hashlib.sha256(data).hexdigest())
        self.assertEqual(list(destination.iterdir()), [])
        self.archive(); data = self.path.read_bytes()
        (destination / 'sentinel').write_text('keep')
        with self.assertRaisesRegex(ValueError, 'destination'):
            rootfs.extract(self.path, destination, length=len(data), sha256=hashlib.sha256(data).hexdigest())
        self.assertEqual((destination / 'sentinel').read_text(), 'keep')
        alias = Path(self.temp.name) / 'alias'; alias.symlink_to(destination, target_is_directory=True)
        with self.assertRaises(OSError):
            rootfs.extract(self.path, alias, length=len(data), sha256=hashlib.sha256(data).hexdigest())
