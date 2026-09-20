import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import uuid

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'tools'))

import dev_boot
import dev_deploy
import dev_rootfs
import dev_system_release

spec = importlib.util.spec_from_file_location('dev', HERE / 'tools/dev.py')
dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev)


def build_archive(path, files):
    """A minimal sanitized release rootfs; mirrors the dev_rootfs test fixture."""
    with tarfile.open(path, 'w:gz') as archive:
        for directory in ('etc', 'bin', 'sbin', 'usr', 'usr/bin', 'usr/lib', 'usr/lib/devos',
                          'home', 'var', 'var/lib', 'var/lib/dev'):
            info = tarfile.TarInfo(directory)
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            archive.addfile(info)
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755 if name in ('bin/busybox', 'usr/bin/dev') else 0o644
            archive.addfile(info, io.BytesIO(data))
        for name, target in (('bin/sh', 'busybox'), ('sbin/init', '/bin/busybox')):
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            info.mode = 0o777
            archive.addfile(info)


def base_files():
    return {'etc/passwd': b'root:x:0:0:root:/root:/bin/sh\nnobody:x:65534:65534:nobody:/:/bin/false\n',
            'etc/shadow': b'root:!:19000:0:99999:7:::\n',
            'etc/fstab': b'/dev/root / ext4 defaults 0 1\n',
            'usr/lib/devos/platform.json': b'{"arch":"x86_64"}',
            'bin/busybox': b'executable fixture', 'usr/bin/dev': b'#!/bin/sh\n'}


def build_release(directory, kernel_bytes, files, version, sequence):
    directory = Path(directory)
    source = directory.parent / (directory.name + '-src')
    source.mkdir()
    (source / 'bzImage').write_bytes(kernel_bytes)
    build_archive(source / 'rootfs.tar.gz', files)
    dev_system_release.build(source / 'bzImage', source / 'rootfs.tar.gz', directory, version, sequence)
    shutil.rmtree(source)
    return directory


def releases(temp):
    kernel_a, kernel_b = b'kernel-a-payload\n', b'kernel-b-payload\n'
    files_a = dict(base_files(), **{'etc/config': b'original\n', 'etc/obsolete': b'old\n'})
    files_b = dict(base_files(), **{'etc/config': b'updated\n', 'etc/new-upstream': b'fresh\n'})
    return (build_release(temp / 'release-a', kernel_a, files_a, '0.1.1', 1),
            build_release(temp / 'release-b', kernel_b, files_b, '0.1.2', 2))


def layout():
    parts, number = {}, 0
    for name in ('efi', 'boot', 'A', 'B', 'home'):
        number += 1
        parts[name] = {'number': number, 'partuuid': str(uuid.uuid4())}
        if name != 'efi':
            parts[name]['uuid'] = str(uuid.uuid4())
    metadata = {'version': 1, 'layout': 'ab', 'slot': 'A', 'partitions': parts,
                'shared_mounts': ['/home'], 'slots': {'A': {'initialized': True},
                                                      'B': {'initialized': False}}}
    observation = {'active': 'A', 'inactive': 'B', 'disk': '/dev/fakedisk',
                   'target': '/dev/fakedisk4', 'device': '259:4',
                   'partuuid': parts['B']['partuuid'], 'uuid': parts['B']['uuid']}
    return metadata, observation


class Baseline(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_record_round_trip_and_missing_baseline(self):
        release_a, _ = releases(self.root)
        record = dev_deploy.record_from_release(release_a)
        with self.assertRaisesRegex(ValueError, 'baseline'):
            dev_deploy.baseline_record(self.root)
        state = self.root / 'var/lib/dev/system'
        state.mkdir(parents=True)
        (state / 'installed-release.json').write_text(json.dumps(record))
        self.assertEqual(dev_deploy.baseline_record(self.root), record)
        self.assertEqual(dev_deploy.baseline_record(self.root, release_a), record)

    def test_record_validation_rejects_bad_shapes(self):
        release_a, _ = releases(self.root)
        record = dev_deploy.record_from_release(release_a)
        broken = [dict(record, format=2), dict(record, extra=1),
                  dict(record, release={'version': '-invalid', 'sequence': 1,
                                        'manifest_sha256': 'a' * 64}),
                  dict(record, etc={})]
        for candidate in broken:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    dev_deploy.validate_record(candidate)

    def test_sequence_must_strictly_increase(self):
        release_a, release_b = releases(self.root)
        record = dev_deploy.record_from_release(release_a)
        manifest_b = json.loads((release_b / 'manifest.json').read_text())
        manifest_a = json.loads((release_a / 'manifest.json').read_text())
        dev_deploy.check_sequence(manifest_b, record)
        with self.assertRaisesRegex(ValueError, 'newer'):
            dev_deploy.check_sequence(manifest_a, record)

    def test_release_identity_binds_canonical_manifest(self):
        _, release_b = releases(self.root)
        manifest = json.loads((release_b / 'manifest.json').read_text())
        identity = dev_deploy._release_identity(manifest)
        expected = hashlib.sha256((json.dumps(manifest, sort_keys=True) + '\n').encode()).hexdigest()
        self.assertEqual(identity['manifest_sha256'], expected)
        self.assertEqual(identity['version'], '0.1.2')

    def test_fstab_filter_keeps_unrelated_lines(self):
        text = ('# comment\n/dev/root / ext4 defaults 0 1\n'
                'UUID=old /boot ext4 defaults 0 2\n'
                'tmpfs /tmp tmpfs mode=0755 0 0\n')
        self.assertEqual(dev_deploy.fstab_kept(text), ['# comment', 'tmpfs /tmp tmpfs mode=0755 0 0'])


@unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0 and
                     shutil.which('grub-editenv'), 'Linux root with grub-editenv')
class Transaction(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.release_a, self.release_b = releases(self.root)
        self.live = self.root / 'live'
        self.live.mkdir()
        manifest_a = json.loads((self.release_a / 'manifest.json').read_text())
        item = manifest_a['files']['rootfs.tar.gz']
        dev_rootfs.extract(self.release_a / 'rootfs.tar.gz', self.live,
                           length=item['length'], sha256=item['sha256'])
        (self.live / 'etc/devos-local').write_text('keep-me\n')
        hello = b'#!/bin/sh\necho hello\n'
        (self.live / 'usr/bin/hello').write_bytes(hello)
        (self.live / 'usr/bin/hello').chmod(0o755)
        sha = hashlib.sha256(hello).hexdigest()
        archive = self.live / 'var/lib/dev/archives' / sha
        archive.mkdir(parents=True)
        (archive / 'hello-1.0.0.dpk').write_bytes(hello)
        (self.live / 'var/lib/dev/installed.json').write_text(json.dumps({'hello': {
            'name': 'hello', 'version': '1.0.0',
            'files': {'usr/bin/hello': {'mode': 0o755, 'sha256': sha}},
            'installed_trust': {'type': 'unsigned',
                                'archive': f'var/lib/dev/archives/{sha}/hello-1.0.0.dpk',
                                'sha256': sha}}}))
        self.record = dev_deploy.record_from_release(self.release_a)
        system = self.live / 'var/lib/dev/system'
        system.mkdir()
        (system / 'installed-release.json').write_text(json.dumps(self.record))
        self.metadata, self.observation = layout()
        (self.live / 'etc/devos-install.json').write_text(json.dumps({
            'version': '0.1', 'firmware': 'UEFI',
            'root_partuuid': self.metadata['partitions']['A']['partuuid'],
            'root_uuid': self.metadata['partitions']['A']['uuid'],
            'username': 'tester', 'hostname': 'dev-os-test'}))
        self.boot = self.root / 'boot'
        (self.boot / 'devos/A').mkdir(parents=True)
        (self.boot / 'devos/A/vmlinuz').write_bytes(b'kernel-a-old\n')
        dev_boot.publish_config(self.boot, self.metadata['partitions']['boot']['uuid'],
                                {slot: self.metadata['partitions'][slot]['partuuid']
                                 for slot in ('A', 'B')}, 'A', serial=False)
        dev_boot.environment(self.boot, initialize=True)
        self.staged = self.root / 'staged'
        self.staged.mkdir()

    def arguments(self, release=None):
        release = release or self.release_b
        manifest = json.loads((release / 'manifest.json').read_text())
        return {'live': self.live, 'boot': self.boot, 'staged': self.staged,
                'artifacts': {'bzImage': release / 'bzImage',
                              'rootfs.tar.gz': release / 'rootfs.tar.gz'},
                'manifest': manifest, 'baseline': self.record, 'serial': False}

    def test_full_transaction_stages_merges_and_schedules(self):
        report = dev_deploy.deploy(dev, self.observation, self.metadata, **self.arguments())
        self.assertEqual((report['slot'], report['scheduled']), ('B', True))
        self.assertEqual((report['packages'], report['package_files'], report['archives_copied']),
                         (1, 1, 1))
        # Configuration merge: upstream update applies, deletions propagate,
        # upstream additions appear and the local addition survives.
        self.assertEqual((self.staged / 'etc/config').read_text(), 'updated\n')
        self.assertFalse((self.staged / 'etc/obsolete').exists())
        self.assertEqual((self.staged / 'etc/new-upstream').read_text(), 'fresh\n')
        self.assertEqual((self.staged / 'etc/devos-local').read_text(), 'keep-me\n')
        # Package preservation: state and owned bytes transfer with identities.
        hello = self.staged / 'usr/bin/hello'
        self.assertEqual(hello.read_bytes(), b'#!/bin/sh\necho hello\n')
        self.assertEqual(os.stat(hello).st_mode & 0o777, 0o755)
        self.assertEqual(json.loads((self.staged / 'var/lib/dev/installed.json').read_text()),
                         json.loads((self.live / 'var/lib/dev/installed.json').read_text()))
        sha = json.loads((self.live / 'var/lib/dev/installed.json').read_text())['hello'][
            'installed_trust']['sha256']
        staged_archive = self.staged / 'var/lib/dev/archives' / sha / 'hello-1.0.0.dpk'
        self.assertTrue(staged_archive.is_file())
        self.assertEqual(hashlib.sha256(staged_archive.read_bytes()).hexdigest(), sha)
        # Slot adaptation binds the staged root to this machine's slot B.
        fstab = (self.staged / 'etc/fstab').read_text().splitlines()
        parts = self.metadata['partitions']
        self.assertIn(f'UUID={parts["B"]["uuid"]} / ext4 defaults,noatime 0 1', fstab)
        self.assertIn(f'UUID={parts["boot"]["uuid"]} /boot ext4 defaults,noatime 0 2', fstab)
        self.assertIn(f'PARTUUID={parts["efi"]["partuuid"]} /boot/efi vfat defaults,umask=0077 0 2', fstab)
        self.assertIn(f'UUID={parts["home"]["uuid"]} /home ext4 defaults,noatime 0 2', fstab)
        self.assertNotIn('/dev/root / ext4 defaults 0 1', fstab)
        system = json.loads((self.staged / 'etc/devos-system.json').read_text())
        self.assertEqual((system['slot'], system['partitions']), ('B', parts))
        self.assertEqual(system['slots'], {'A': {'initialized': True}, 'B': {'initialized': True}})
        self.assertEqual(json.loads((self.staged / 'etc/devos-install.json').read_text())
                         ['root_partuuid'], parts['B']['partuuid'])
        # The staged baseline record chains the next deployment.
        self.assertEqual(json.loads((self.staged / dev_deploy.RELEASE_STATE).read_text()),
                         dev_deploy.record_from_release(self.release_b))
        # Boot policy: verified kernel installed for B, confirmed default kept,
        # and a real GRUB environment holds exactly the one-shot trial.
        self.assertEqual((self.boot / 'devos/B/vmlinuz').read_bytes(), b'kernel-b-payload\n')
        config = (self.boot / 'grub/grub.cfg').read_text()
        self.assertIn('set default=devos-A', config)
        self.assertIn(f'PARTUUID={parts["B"]["partuuid"]}', config)
        listed = subprocess.run(['grub-editenv', str(self.boot / 'grub/devos.env'), 'list'],
                                capture_output=True, text=True, check=True).stdout
        self.assertIn('next_entry=devos-B', listed)
        # Completion removes the journal.
        self.assertFalse((self.live / 'var/lib/dev/system/deploy-journal.json').exists())

    def test_configuration_conflict_aborts_before_any_write(self):
        (self.live / 'etc/config').write_text('local-edit\n')
        with self.assertRaisesRegex(ValueError, 'Configuration conflicts'):
            dev_deploy.deploy(dev, self.observation, self.metadata, **self.arguments())
        self.assertEqual(os.listdir(self.staged), [])
        self.assertFalse((self.live / 'var/lib/dev/system/deploy-journal.json').exists())

    def test_package_release_overlap_aborts_before_any_write(self):
        overlapping = dict(base_files(), **{'etc/config': b'updated\n',
                                            'usr/bin/hello': b'from the release\n'})
        release = build_release(self.root / 'release-overlap', b'kernel-c\n', overlapping, '0.1.3', 3)
        with self.assertRaisesRegex(ValueError, 'Package preservation conflicts'):
            dev_deploy.deploy(dev, self.observation, self.metadata, **self.arguments(release))
        self.assertEqual(os.listdir(self.staged), [])
        self.assertFalse((self.live / 'var/lib/dev/system/deploy-journal.json').exists())

    def test_observation_must_match_installed_metadata(self):
        broken = dict(self.observation, partuuid=str(uuid.uuid4()))
        with self.assertRaisesRegex(ValueError, 'does not match installed metadata'):
            dev_deploy.deploy(dev, broken, self.metadata, **self.arguments())

    def test_older_release_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'newer'):
            dev_deploy.deploy(dev, self.observation, self.metadata,
                              **self.arguments(release=self.release_a))
