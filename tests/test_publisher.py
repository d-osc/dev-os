"""Exercise the real local publisher against the real TUF client on Linux."""
import functools
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from test_repository import TUF_AVAILABLE, QuietHandler, load

publisher = load('dev_publish') if TUF_AVAILABLE and os.name == 'posix' else None
dev = load('dev')
repository = load('dev_repository')


@unittest.skipUnless(publisher, 'Publisher requires Linux/WSL and TUF dependencies')
class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.public = self.base / 'public'
        self.keys = self.base / 'private'
        self.password = b'ephemeral publisher test passphrase'
        publisher.initialize(self.public, self.keys, self.password)
        self.root = self.base / 'client'
        config = self.root / 'etc/devos'
        config.mkdir(parents=True)
        (config / 'trusted-root.json').write_bytes((self.public / 'bootstrap-root.json').read_bytes())
        (config / 'package-policy.json').write_text(json.dumps({
            'version': 1, 'require_signed': True, 'allow_unsigned_override': False}))
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0),
            functools.partial(QuietHandler, directory=str(self.public)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def stop():
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        self.addCleanup(stop)
        url = f'http://127.0.0.1:{server.server_port}/current'
        (config / 'repository.json').write_text(json.dumps({
            'metadata_url': url + '/metadata', 'targets_url': url + '/targets',
            'allow_loopback_http': True}))

    def package(self, version='1', content='hello'):
        source = self.base / ('source-' + version)
        (source / 'payload/usr/bin').mkdir(parents=True, exist_ok=True)
        (source / 'payload/usr/bin/published-hello').write_text(content)
        (source / 'manifest.json').write_text(json.dumps({
            'name': 'hello', 'version': version, 'arch': 'all', 'executables': ['usr/bin/published-hello']}))
        output = self.base / ('hello-' + version + '.dpk')
        dev.build(source, output)
        return output

    def fetch(self):
        with dev.database(self.root):
            client = repository.Repository(self.root, dev)
            client.refresh()
            path, entry = client.fetch('hello')
            return Path(path).read_bytes(), entry

    def dependency_package(self, name, version, dependencies=None):
        source = self.base / (name + '-' + version)
        payload = source / 'payload/usr/share' / name
        payload.mkdir(parents=True)
        (payload / 'version').write_text(version)
        (source / 'manifest.json').write_text(json.dumps({
            'name': name, 'version': version, 'arch': 'all', 'dependencies': dependencies or {}}))
        archive = self.base / (name + '-' + version + '.dpk')
        dev.build(source, archive)
        return archive

    def cli(self, command, name):
        return subprocess.run([sys.executable, str(Path(dev.__file__).resolve()),
            '--root', str(self.root), command, name], capture_output=True, text=True, timeout=30)

    def test_signed_dependencies_install_and_upgrade_as_one_set(self):
        publisher.publish(self.keys, [self.dependency_package('lib', '1'),
            self.dependency_package('app', '1', {'lib': '==1'})], self.password)
        installed = self.cli('install', 'app')
        self.assertEqual(installed.returncode, 0, installed.stderr)
        with dev.database(self.root) as (db, _):
            self.assertEqual(set(db), {'lib', 'app'})
            self.assertTrue(all(m['installed_trust']['type'] == 'tuf' for m in db.values()))
        publisher.publish(self.keys, [self.dependency_package('lib', '2'),
            self.dependency_package('app', '2', {'lib': '==2'})], self.password)
        # Requesting the library upgrade must update its older dependent too.
        upgraded = self.cli('upgrade', 'lib')
        self.assertEqual(upgraded.returncode, 0, upgraded.stderr)
        with dev.database(self.root) as (db, _):
            self.assertEqual({name: m['version'] for name, m in db.items()}, {'lib': '2', 'app': '2'})
            self.assertTrue(all(m['installed_previous']['version'] == '1' for m in db.values()))
        for name in ('lib', 'app'):
            self.assertEqual((self.root / 'usr/share' / name / 'version').read_text(), '2')
        self.command('rollback', 'app', status=1)
        def fail_during_rollback(point):
            if point == 'file:0':
                raise OSError('injected rollback write failure')
        with mock.patch.object(dev, 'transaction_checkpoint', side_effect=fail_during_rollback):
            with self.assertRaisesRegex(OSError, 'rollback write failure'):
                dev.rollback(self.root, ['app', 'lib'])
        for name in ('lib', 'app'):
            self.assertEqual((self.root / 'usr/share' / name / 'version').read_text(), '2')
        self.command('rollback', 'app', 'lib')
        with dev.database(self.root) as (db, _):
            self.assertEqual({name: m['version'] for name, m in db.items()}, {'lib': '1', 'app': '1'})
        for name in ('lib', 'app'):
            self.assertEqual((self.root / 'usr/share' / name / 'version').read_text(), '1')

    def test_revoked_member_blocks_entire_batch_rollback(self):
        for version in ('1', '2'):
            publisher.publish(self.keys, [self.dependency_package('lib', version),
                self.dependency_package('app', version, {'lib': '==' + version})], self.password)
            self.command('install' if version == '1' else 'upgrade', 'app')
        before = (self.root / 'var/lib/dev/installed.json').read_bytes()
        publisher.publish(self.keys, [], self.password, revoke=('lib', '1'))
        self.command('rollback', 'app', 'lib', status=1)
        self.assertEqual((self.root / 'var/lib/dev/installed.json').read_bytes(), before)
        for name in ('lib', 'app'):
            self.assertEqual((self.root / 'usr/share' / name / 'version').read_text(), '2')

    def test_signed_dependency_conflict_does_not_install_partial_set(self):
        publisher.publish(self.keys, [self.dependency_package('lib', '1'),
            self.dependency_package('app', '1', {'lib': '>=2'})], self.password)
        result = self.cli('install', 'app')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Dependency conflict', result.stderr)
        with dev.database(self.root) as (db, _):
            self.assertEqual(db, {})
        self.assertFalse((self.root / 'usr/share/app').exists())
        self.assertFalse((self.root / 'usr/share/lib').exists())

    def test_signed_dependency_cycles_are_installed_together(self):
        publisher.publish(self.keys, [self.dependency_package('lib', '1', {'app': '==1'}),
            self.dependency_package('app', '1', {'lib': '==1'})], self.password)
        result = self.cli('install', 'app')
        self.assertEqual(result.returncode, 0, result.stderr)
        with dev.database(self.root) as (db, _):
            self.assertEqual(set(db), {'lib', 'app'})

    def test_missing_signed_dependency_keeps_existing_state(self):
        publisher.publish(self.keys, [self.dependency_package('app', '1')], self.password)
        result = self.cli('install', 'app')
        self.assertEqual(result.returncode, 0, result.stderr)
        before = (self.root / 'var/lib/dev/installed.json').read_bytes()
        publisher.publish(self.keys, [self.dependency_package('app', '2', {'absent': '*'})], self.password)
        result = self.cli('upgrade', 'app')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Missing repository dependency', result.stderr)
        self.assertEqual((self.root / 'var/lib/dev/installed.json').read_bytes(), before)
        self.assertEqual((self.root / 'usr/share/app/version').read_text(), '1')

    def test_publish_fetch_and_cli_install(self):
        archive = self.package()
        publisher.publish(self.keys, [archive], self.password)
        data, entry = self.fetch()
        self.assertEqual(data, archive.read_bytes())
        self.assertEqual(entry['version'], '1')
        result = subprocess.run([sys.executable, str(Path(dev.__file__).resolve()),
            '--root', str(self.root), 'install', 'hello'], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / 'usr/bin/published-hello').read_text(), 'hello')

    def system_release(self, version, sequence):
        # Minimal policy-valid rootfs; this suite does not claim these bytes can boot.
        import io
        import tarfile
        module = dev.system_release_module()
        kernel, rootfs = self.base / ('kernel-' + version), self.base / ('root-' + version)
        kernel.write_bytes(b'kernel transport fixture ' + version.encode())
        files = {'etc/passwd': b'root:x:0:0:root:/root:/bin/sh\n',
                 'etc/shadow': b'root:!:19000:0:99999:7:::\n', 'etc/fstab': b'/dev/root / ext4 defaults 0 1\n',
                 'bin/sh': b'fixture', 'sbin/init': b'fixture', 'usr/bin/dev': version.encode(),
                 'usr/lib/devos/platform.json': b'{"arch":"x86_64"}'}
        with tarfile.open(rootfs, 'w:gz') as archive:
            for name in ('etc', 'bin', 'sbin', 'usr', 'usr/bin', 'usr/lib', 'usr/lib/devos'):
                item = tarfile.TarInfo(name); item.type = tarfile.DIRTYPE; item.mode = 0o755
                archive.addfile(item)
            for name, data in files.items():
                item = tarfile.TarInfo(name); item.mode = 0o755; item.size = len(data)
                archive.addfile(item, io.BytesIO(data))
        output = self.base / ('system-' + version)
        module.build(kernel, rootfs, output, version, sequence)
        return output

    def fetch_system(self, minimum=0):
        with dev.database(self.root):
            client = repository.Repository(self.root, dev)
            return client.fetch_system(minimum_sequence=minimum)

    def test_signed_system_artifacts_and_monotonic_sequence(self):
        first = self.system_release('1', 1)
        publisher.publish(self.keys, [], self.password, system_release=first)
        manifest, artifacts = self.fetch_system()
        self.assertEqual(manifest['sequence'], 1)
        for name, path in artifacts.items():
            self.assertEqual(path.read_bytes(), (first / name).read_bytes())
        fetched = json.loads(self.command('system-fetch').stdout)
        self.assertEqual(fetched['manifest']['sequence'], 1)
        self.assertEqual(set(fetched['artifacts']), {'bzImage', 'rootfs.tar.gz'})
        second = self.system_release('2', 2)
        publisher.publish(self.keys, [], self.password, system_release=second)
        with self.assertRaisesRegex(ValueError, 'older than the active'):
            self.fetch_system(3)
        self.assertEqual(self.fetch_system()[0]['sequence'], 2)
        with self.assertRaisesRegex(ValueError, 'sequence must increase'):
            publisher.publish(self.keys, [], self.password, system_release=first)
        self.assertEqual(self.fetch_system()[0]['sequence'], 2)
        watermark = self.root / 'var/lib/dev/repository/system-sequence.json'
        known = json.loads(watermark.read_text()); known['sequence'] = 3
        watermark.write_text(json.dumps(known))
        with self.assertRaisesRegex(ValueError, 'sequence rollback'):
            self.fetch_system()

    def test_tampered_system_payload_is_refused(self):
        source = self.system_release('1', 1)
        publisher.publish(self.keys, [], self.password, system_release=source)
        manifest = dev.system_release_module().load(source)
        digest = manifest['files']['bzImage']['sha256']
        payload = self.public / 'current/targets/systems/x86_64/1' / (digest + '.bzImage')
        payload.write_bytes(b'X' * manifest['files']['bzImage']['length'])
        from tuf.api.exceptions import LengthOrHashMismatchError
        with self.assertRaises(LengthOrHashMismatchError):
            self.fetch_system()
        self.assertFalse((self.root / 'var/lib/dev/repository/system-sequence.json').exists())

    def test_system_snapshot_refuses_changed_input_and_keeps_previous_generation(self):
        source = self.system_release('1', 1)
        publisher.publish(self.keys, [], self.password, system_release=source)
        second = self.system_release('2', 2)
        (second / 'rootfs.tar.gz').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            publisher.publish(self.keys, [], self.password, system_release=second)
        self.assertEqual(self.fetch_system()[0]['sequence'], 1)

    def test_thresholds_encryption_and_public_permissions(self):
        root = json.loads((self.public / 'bootstrap-root.json').read_text())['signed']
        for role in ('root', 'targets'):
            self.assertEqual(root['roles'][role]['threshold'], 2)
            self.assertEqual(len(root['roles'][role]['keyids']), 3)
        self.assertFalse(list(self.public.rglob('*.pem')))
        for key in self.keys.glob('*.pem'):
            self.assertIn(b'ENCRYPTED PRIVATE KEY', key.read_bytes())
            self.assertEqual(key.stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.public / 'current').stat().st_mode & 0o777, 0o755)
        self.assertEqual((self.public / 'current/metadata/timestamp.json').stat().st_mode & 0o777, 0o644)

    def test_root_and_targets_rotation(self):
        archive = self.package()
        publisher.publish(self.keys, [archive], self.password)
        self.fetch()
        for role in ('targets', 'root'):
            publisher.rotate(self.keys, role, self.password)
            self.assertEqual(self.fetch()[0], archive.read_bytes())

    def test_same_version_cannot_change_content(self):
        archive = self.package()
        publisher.publish(self.keys, [archive], self.password)
        previous = self.fetch()[0]
        changed = self.package(content='replacement')
        with self.assertRaisesRegex(ValueError, 'cannot be replaced'):
            publisher.publish(self.keys, [changed], self.password)
        self.assertEqual(self.fetch()[0], previous)

    def test_failed_publication_recovers_after_each_boundary(self):
        for point in ('reserved', 'generation', 'selected'):
            with self.subTest(point=point):
                archive = self.package(version=point)
                def fail(label):
                    if label == point:
                        raise OSError('simulated publisher interruption')
                with mock.patch.object(publisher, 'checkpoint', side_effect=fail):
                    with self.assertRaises(OSError):
                        publisher.publish(self.keys, [archive], self.password)
                publisher.publish(self.keys, [archive], self.password)
                self.assertEqual(self.fetch()[0], archive.read_bytes())

    def test_previous_generation_remains_unchanged(self):
        first = self.package()
        version = publisher.publish(self.keys, [first], self.password)
        before = {p.relative_to(self.public / 'generations' / str(version)).as_posix(): p.read_bytes()
                  for p in (self.public / 'generations' / str(version)).rglob('*') if p.is_file()}
        publisher.publish(self.keys, [self.package('2', 'new content')], self.password)
        for name, data in before.items():
            self.assertEqual((self.public / 'generations' / str(version) / name).read_bytes(), data)

    def command(self, *args, status=0):
        result = subprocess.run([sys.executable, str(Path(dev.__file__).resolve()),
            '--root', str(self.root), *args], capture_output=True, text=True, timeout=25)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return result

    def test_signed_upgrade_and_rollback_end_to_end(self):
        publisher.publish(self.keys, [self.package()], self.password)
        self.command('install', 'hello')
        publisher.publish(self.keys, [self.package('2', 'upgraded')], self.password)
        self.command('upgrade', 'hello')
        self.assertEqual((self.root / 'usr/bin/published-hello').read_text(), 'upgraded')
        self.command('rollback', 'hello')
        self.assertEqual((self.root / 'usr/bin/published-hello').read_text(), 'hello')

    def test_revoked_old_version_cannot_be_rolled_back(self):
        publisher.publish(self.keys, [self.package()], self.password)
        self.command('install', 'hello')
        publisher.publish(self.keys, [self.package('2', 'upgraded')], self.password)
        self.command('upgrade', 'hello')
        publisher.publish(self.keys, [], self.password, revoke=('hello', '1'))
        self.command('rollback', 'hello', status=1)
        self.assertEqual((self.root / 'usr/bin/published-hello').read_text(), 'upgraded')

    def test_two_available_target_keys_are_sufficient(self):
        state = json.loads((self.keys / 'publisher.json').read_text())
        first, second = [self.keys / name for name in state['roles']['targets'][:2]]
        first.rename(self.base / 'offline-one.pem')
        publisher.publish(self.keys, [self.package()], self.password)
        self.assertEqual(self.fetch()[1]['version'], '1')
        second.rename(self.base / 'offline-two.pem')
        with self.assertRaisesRegex(ValueError, 'Not enough available signing keys'):
            publisher.publish(self.keys, [], self.password)

    def test_fingerprint_pinned_provisioning_and_install(self):
        import hashlib
        from types import SimpleNamespace
        destination = self.base / 'provisioned'
        config = json.loads((self.root / 'etc/devos/repository.json').read_text())
        anchor = self.public / 'bootstrap-root.json'
        args = SimpleNamespace(root_file=anchor, sha256=hashlib.sha256(anchor.read_bytes()).hexdigest(),
                               metadata_url=config['metadata_url'], targets_url=config['targets_url'],
                               allow_loopback_http=True)
        publisher.publish(self.keys, [self.package()], self.password)
        repository.provision(destination, args, dev)
        repository.provision(destination, args, dev)
        policy = json.loads((destination / 'etc/devos/package-policy.json').read_text())
        self.assertTrue(policy['require_signed'])
        self.assertFalse(policy['allow_unsigned_override'])
        result = subprocess.run([sys.executable, str(Path(dev.__file__).resolve()),
            '--root', str(destination), 'install', 'hello'], capture_output=True, text=True, timeout=25)
        self.assertEqual(result.returncode, 0, result.stderr)
        args.sha256 = '0' * 64
        with self.assertRaisesRegex(ValueError, 'fingerprint mismatch'):
            repository.provision(self.base / 'untrusted', args, dev)
        self.assertFalse((self.base / 'untrusted').exists())


if __name__ == '__main__':
    unittest.main()
