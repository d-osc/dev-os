"""Real TUF metadata/signatures and loopback HTTP; ephemeral test keys only."""
from datetime import datetime, timedelta, timezone
import functools
import hashlib
import http.server
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest

try:
    from tuf.api.metadata import Metadata, Root, Targets, Snapshot, Timestamp, MetaFile, TargetFile
    from tuf.api.exceptions import RepositoryError
    from securesystemslib.signer import CryptoSigner
    TUF_AVAILABLE = True
except ImportError:
    TUF_AVAILABLE = False


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / 'tools' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dev = load('dev')
repo = load('dev_repository')


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


@unittest.skipUnless(TUF_AVAILABLE, 'Install config/repository-requirements.txt for TUF integration tests')
class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'client'
        self.remote = self.base / 'remote'
        self.metadata = self.remote / 'metadata'
        self.metadata.mkdir(parents=True)
        self.targets = self.remote / 'targets'
        (self.targets / 'packages/hello').mkdir(parents=True)
        self.package = self.targets / 'packages/hello/1.dpk'
        self.package.write_bytes(b'fixture package bytes')
        self.index = {'version': 1, 'packages': {'hello': {
            'version': '1', 'arch': 'all', 'target': 'packages/hello/1.dpk'}}}
        self.signers = {role: CryptoSigner.generate_ed25519() for role in ('root', 'targets', 'snapshot', 'timestamp')}
        self.expires = datetime.now(timezone.utc) + timedelta(days=1)
        self.root_md = Metadata(Root(expires=self.expires, consistent_snapshot=False))
        for role, signer in self.signers.items():
            self.root_md.signed.add_key(signer.public_key, role)
        self.root_md.sign(self.signers['root'])
        self.root_md.to_file(str(self.metadata / '1.root.json'))
        config = self.root / 'etc/devos'
        config.mkdir(parents=True)
        # This fixture tests signatures and installation, not shell execution.
        (self.root / 'bin').mkdir()
        (self.root / 'bin/sh').write_text('interpreter fixture')
        (self.root / 'bin/sh').chmod(0o755)
        (config / 'trusted-root.json').write_bytes(self.root_md.to_bytes())
        (config / 'package-policy.json').write_text(json.dumps({
            'version': 1, 'require_signed': True, 'allow_unsigned_override': False}))
        self.publish()
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0),
            functools.partial(QuietHandler, directory=str(self.remote)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def shutdown():
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        self.addCleanup(shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        (config / 'repository.json').write_text(json.dumps({
            'metadata_url': base + '/metadata', 'targets_url': base + '/targets',
            'allow_loopback_http': True}))

    def publish(self, version=1, expiry=None, targets_signer=None):
        (self.targets / 'index.json').write_text(json.dumps(self.index))
        targets = Metadata(Targets(version=version, expires=self.expires))
        for name in ('index.json', 'packages/hello/1.dpk'):
            targets.signed.targets[name] = TargetFile.from_file(name, str(self.targets / name))
        targets.sign(targets_signer or self.signers['targets'])
        targets.to_file(str(self.metadata / 'targets.json'))
        def meta(data):
            return MetaFile(version, len(data), {'sha256': hashlib.sha256(data).hexdigest()})
        snapshot = Metadata(Snapshot(version=version, expires=self.expires,
                            meta={'targets.json': meta(targets.to_bytes())}))
        snapshot.sign(self.signers['snapshot'])
        snapshot.to_file(str(self.metadata / 'snapshot.json'))
        timestamp = Metadata(Timestamp(version=version, expires=expiry or self.expires,
                                       snapshot_meta=meta(snapshot.to_bytes())))
        timestamp.sign(self.signers['timestamp'])
        timestamp.to_file(str(self.metadata / 'timestamp.json'))

    def fetch(self):
        with dev.database(self.root):
            client = repo.Repository(self.root, dev)
            client.refresh()
            path, entry = client.fetch('hello')
            self.assertEqual(entry['version'], '1')
            return Path(path).read_bytes()

    def test_verified_download(self):
        self.assertEqual(self.fetch(), b'fixture package bytes')

    def test_tampered_package_is_rejected(self):
        self.package.write_bytes(b'X' * self.package.stat().st_size)
        with self.assertRaises(RepositoryError):
            self.fetch()

    def test_expired_metadata_is_rejected(self):
        self.publish(expiry=datetime.now(timezone.utc) - timedelta(days=1))
        with self.assertRaises(RepositoryError):
            self.fetch()

    def test_unknown_signer_is_rejected(self):
        self.publish(targets_signer=CryptoSigner.generate_ed25519())
        with self.assertRaises(RepositoryError):
            self.fetch()

    def test_metadata_rollback_is_rejected(self):
        self.publish(version=2)
        self.fetch()
        self.publish(version=1)
        with self.assertRaises(RepositoryError):
            self.fetch()

    def test_key_rotation_and_revocation(self):
        self.fetch()
        old_root = self.signers['root']
        old_target = self.signers['targets']
        for role in ('root', 'targets'):
            previous = self.signers[role]
            replacement = CryptoSigner.generate_ed25519()
            self.root_md.signed.revoke_key(previous.public_key.keyid, role)
            self.root_md.signed.add_key(replacement.public_key, role)
            self.signers[role] = replacement
        self.root_md.signed.version = 2
        self.root_md.sign(old_root)
        self.root_md.sign(self.signers['root'], append=True)
        self.root_md.to_file(str(self.metadata / '2.root.json'))
        self.publish(version=2)
        self.assertEqual(self.fetch(), b'fixture package bytes')
        self.publish(version=3, targets_signer=old_target)
        with self.assertRaises(RepositoryError):
            self.fetch()

    def test_signed_index_cannot_escape_target_namespace(self):
        self.index['packages']['hello']['target'] = '../escape.dpk'
        self.publish()
        with self.assertRaisesRegex(ValueError, 'Invalid repository package target'):
            self.fetch()

    def test_clock_rollback_is_rejected(self):
        self.fetch()
        (self.root / 'var/lib/dev/repository/clock.json').write_text(json.dumps({
            'last_refresh': int(datetime.now(timezone.utc).timestamp()) + 1000}))
        with self.assertRaisesRegex(ValueError, 'clock moved backwards'):
            self.fetch()

    def make_installable(self, name='hello'):
        source = self.base / 'source'
        (source / 'payload/usr/bin').mkdir(parents=True, exist_ok=True)
        (source / 'payload/usr/bin/signed-hello').write_text('#!/bin/sh\necho signed\n')
        (source / 'manifest.json').write_text(json.dumps({
            'name': name, 'version': '1', 'arch': 'all', 'executables': ['usr/bin/signed-hello']}))
        dev.build(source, self.package)
        self.publish()

    def test_signed_local_install_records_trust(self):
        self.make_installable()
        dev.install(self.root, self.package)
        db = json.loads((self.root / 'var/lib/dev/installed.json').read_text())
        self.assertEqual(db['hello']['installed_trust']['type'], 'tuf')
        self.assertEqual(db['hello']['installed_trust']['sha256'], dev.digest(self.package))
        self.assertTrue((self.root / 'usr/bin/signed-hello').exists())

    def test_signed_index_must_match_actual_manifest(self):
        self.make_installable('other')
        with self.assertRaisesRegex(ValueError, 'not in the signed repository index'):
            dev.install(self.root, self.package)
        self.assertFalse((self.root / 'usr/bin/signed-hello').exists())

    def test_repackaged_local_archive_is_rejected(self):
        self.make_installable()
        self.package.write_bytes(self.package.read_bytes() + b'unsigned suffix')
        with self.assertRaisesRegex(ValueError, 'signature verification failed'):
            dev.install(self.root, self.package)
        self.assertFalse((self.root / 'usr/bin/signed-hello').exists())

    def test_unsigned_override_cannot_bypass_production_policy(self):
        self.make_installable()
        with self.assertRaisesRegex(ValueError, 'override is disabled'):
            dev.install(self.root, self.package, allow_unsigned=True)
        self.assertFalse((self.root / 'usr/bin/signed-hello').exists())

    def test_install_uses_private_verified_snapshot(self):
        from unittest import mock
        self.make_installable()
        original = dev.unpack
        def swap_original(archive, stage, **kwargs):
            self.package.write_bytes(b'replaced after snapshot')
            return original(archive, stage, **kwargs)
        with mock.patch.object(dev, 'unpack', side_effect=swap_original):
            dev.install(self.root, self.package)
        self.assertEqual((self.root / 'usr/bin/signed-hello').read_text(), '#!/bin/sh\necho signed\n')


class RepositoryURLTests(unittest.TestCase):
    def test_remote_http_and_embedded_credentials_rejected(self):
        for value in ('http://example.org', 'http://localhost', 'https://user:password@example.org',
                      'https://example.org/?secret=x', 'https://example.org/#fragment'):
            with self.subTest(url=value), self.assertRaises(ValueError):
                repo.validate_url(value, True)
        self.assertEqual(repo.validate_url('https://example.org'), 'https://example.org/')


class GithubAssets(unittest.TestCase):
    def test_release_base_detection(self):
        latest = 'https://github.com/d-osc/dev-os/releases/latest/download/'
        tagged = 'https://github.com/d-osc/dev-os/releases/download/tuf-20260920/'
        self.assertEqual(repo.github_release_base(latest), latest)
        self.assertEqual(repo.github_release_base(tagged.rstrip('/')), tagged)
        self.assertIsNone(repo.github_release_base('https://packages.example.org/current/metadata/'))
        self.assertIsNone(repo.github_release_base('https://github.com/d-osc/dev-os/releases/'))
        self.assertIsNone(repo.github_release_base('https://example.org/github.com/a/b/releases/latest/download/'))

    def test_asset_names_are_flat_and_lossless(self):
        self.assertEqual(repo.github_asset_name('metadata/root.json'), 'metadata__root.json')
        self.assertEqual(repo.github_asset_name('targets/packages/hello/1.0.0.dpk'),
                         'targets__packages__hello__1.0.0.dpk')
        for bad in ('a__b.json', '', 'a b', 'dir/a__b', None, 'a/../escape'):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    repo.github_asset_name(bad)

    def test_asset_urls_route_metadata_roles_and_target_paths(self):
        base = 'https://github.com/o/r/releases/latest/download/'
        for path in ('root.json', '2.root.json', 'timestamp.json', 'targets.json',
                     '15.snapshot.json'):
            with self.subTest(path=path):
                self.assertEqual(repo.github_asset_url(base, path),
                                 base + 'metadata__' + path)
        for path in ('index.json', 'system-index.json', 'packages/hello/1.0.0.dpk',
                     'systems/x86_64/0.1.2/bzImage', 'packages/targets.json'):
            with self.subTest(path=path):
                self.assertEqual(repo.github_asset_url(base, path),
                                 base + 'targets__' + path.replace('/', '__'))
        for bad in ('a b',):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    repo.github_asset_url(base, bad)


if __name__ == '__main__':
    unittest.main()
