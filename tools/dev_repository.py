"""TUF-backed repository downloads. Call only while holding dev.database's lock.

The bootstrap root is provisioned by the administrator, never fetched on trust.
This module does not grant permission to install arbitrary local archives.
"""
import json
import hashlib
import re
import time
from pathlib import Path
from urllib.parse import urlsplit


def validate_url(value, allow_loopback=False):
    if not isinstance(value, str):
        raise ValueError('Repository URL must be a string')
    parsed = urlsplit(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
        raise ValueError('Invalid repository URL')
    loopback = parsed.hostname in ('127.0.0.1', '::1')
    if parsed.scheme != 'https' and not (allow_loopback and loopback and parsed.scheme == 'http'):
        raise ValueError('Repository requires HTTPS (explicit loopback HTTP is for tests only)')
    return value.rstrip('/') + '/'


class Repository:
    def __init__(self, root, dev):
        try:
            from tuf.ngclient import Updater
            from tuf.ngclient.config import UpdaterConfig
        except ImportError as exc:
            raise ValueError('Repository support requires the pinned TUF runtime dependencies') from exc
        self.dev = dev
        self.root = root
        config_path = dev.target(root, 'etc/devos/repository.json')
        dev.require(config_path.is_file(), 'Repository is not configured')
        config = json.loads(config_path.read_text())
        dev.require(isinstance(config, dict) and set(config) <= {
            'metadata_url', 'targets_url', 'allow_loopback_http'}, 'Invalid repository configuration')
        allow = config.get('allow_loopback_http', False)
        dev.require(type(allow) is bool, 'Invalid loopback setting')
        metadata_url = validate_url(config.get('metadata_url'), allow)
        targets_url = validate_url(config.get('targets_url'), allow)
        anchor = dev.target(root, 'etc/devos/trusted-root.json')
        dev.require(anchor.is_file() and anchor.stat().st_size <= 512000,
                    'Provision a trusted TUF root before using the repository')
        self.state = dev.target(root, 'var/lib/dev/repository')
        for name in ('metadata', 'targets'):
            dev.durable_mkdir(dev.target(root, 'var/lib/dev/repository/' + name))
        self.clock = self.state / 'clock.json'
        self.started = int(time.time())
        if self.clock.exists():
            previous = json.loads(self.clock.read_text())['last_refresh']
            dev.require(type(previous) is int and self.started >= previous,
                        'System clock moved backwards; repository refresh refused')
        self.updater = Updater(str(self.state / 'metadata'), metadata_url,
                               str(self.state / 'targets'), targets_url,
                               config=UpdaterConfig(app_user_agent='DevOS/0.1',
                                                    max_delegations=16),
                               bootstrap=anchor.read_bytes())
        self.anchor_hash = hashlib.sha256(anchor.read_bytes()).hexdigest()
        self.packages = None

    def refresh(self):
        self.updater.refresh()
        info = self.updater.get_targetinfo('index.json')
        self.dev.require(info is not None and 0 < info.length <= 2 * 1024 * 1024,
                         'Missing or oversized signed package index')
        path = self.updater.download_target(info)
        with open(path, encoding='utf-8') as stream:
            index = json.load(stream)
        self.dev.require(isinstance(index, dict) and index.get('version') == 1 and
                         isinstance(index.get('packages'), dict) and len(index['packages']) <= 10000,
                         'Invalid signed package index')
        token = r'[a-zA-Z0-9][a-zA-Z0-9._+-]{0,79}'
        for name, item in index['packages'].items():
            self.dev.require(re.fullmatch(token, name) and isinstance(item, dict), 'Invalid repository package')
            version = item.get('version')
            self.dev.require(isinstance(version, str) and re.fullmatch(token, version) and
                             item.get('arch') in ('all', 'x86_64') and
                             item.get('target') == f'packages/{name}/{version}.dpk',
                             'Invalid repository package target')
        # Flush cached version history before reporting a successful refresh.
        # A trustworthy clock and durable local cache remain deployment requirements.
        import os
        for cached in (self.state / 'metadata').rglob('*.json'):
            with cached.open('r+b') as stream:
                os.fsync(stream.fileno())
            self.dev.sync_directory(cached.parent)
        self.dev.write_json_atomic({'last_refresh': self.started}, self.clock)
        self.packages = index['packages']
        return self.packages

    def fetch(self, name):
        if self.packages is None:
            self.refresh()
        self.dev.require(name in self.packages, 'Package is not in the signed repository index')
        entry = self.packages[name]
        info = self.updater.get_targetinfo(entry['target'])
        self.dev.require(info is not None and 0 < info.length <= 300 * 1024 * 1024,
                         'Missing or oversized signed package target')
        # Always verify a freshly downloaded target. Never return a user-named path.
        return self.updater.download_target(info), entry

    def fetch_system(self, *, minimum_sequence=0):
        """Authenticate all system artifacts; caller still must safely stage/deploy them."""
        dev_system_release = self.dev.system_release_module()
        if self.packages is None:
            self.refresh()
        self.dev.require(type(minimum_sequence) is int and minimum_sequence >= 0,
                         'Invalid minimum system sequence')
        info = self.updater.get_targetinfo('system-index.json')
        self.dev.require(info is not None and 0 < info.length <= 65536, 'Missing or oversized signed system index')
        index = json.loads(Path(self.updater.download_target(info)).read_text())
        self.dev.require(isinstance(index, dict) and set(index) == {'format', 'arch', 'version', 'sequence', 'target'}
                         and type(index['format']) is int and index['format'] == 1 and index['arch'] == 'x86_64',
                         'Invalid signed system index')
        version, sequence = index['version'], index['sequence']
        self.dev.require(isinstance(version, str) and re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._+-]{0,79}', version)
                         and type(sequence) is int and 1 <= sequence <= 2**53 - 1, 'Invalid system identity')
        prefix = f'systems/x86_64/{version}/'
        self.dev.require(index['target'] == prefix + 'manifest.json', 'Invalid system manifest target')
        manifest_info = self.updater.get_targetinfo(index['target'])
        self.dev.require(manifest_info is not None and 0 < manifest_info.length <= 65536,
                         'Missing or oversized signed system manifest')
        manifest_path = Path(self.updater.download_target(manifest_info))
        manifest = dev_system_release.validate(json.loads(manifest_path.read_text()))
        self.dev.require(manifest['version'] == version and manifest['sequence'] == sequence,
                         'System manifest identity mismatch')
        watermark = self.dev.target(self.root, 'var/lib/dev/repository/system-sequence.json')
        identity = {'sequence': sequence, 'version': version, 'manifest_sha256': self.dev.digest(manifest_path)}
        self.dev.require(sequence >= minimum_sequence, 'System release is older than the active system')
        if watermark.exists():
            previous = json.loads(watermark.read_text())
            self.dev.require(sequence >= previous['sequence'], 'System release sequence rollback refused')
            self.dev.require(sequence != previous['sequence'] or identity == previous,
                             'System release sequence was reused with different content')
        artifacts = {}
        for name, item in manifest['files'].items():
            target = self.updater.get_targetinfo(prefix + name)
            self.dev.require(target is not None and target.length == item['length'] and
                             target.hashes.get('sha256') == item['sha256'],
                             'System artifact differs from signed manifest: ' + name)
            artifacts[name] = Path(self.updater.download_target(target))
        dev_system_release.inspect_rootfs(artifacts['rootfs.tar.gz'])
        self.dev.write_json_atomic(identity, watermark)
        return manifest, artifacts

    def verify_archive(self, archive, manifest, *, historical=False):
        if self.packages is None:
            self.refresh()
        name = manifest['name']
        self.dev.require(name in self.packages, 'Package is not in the signed repository index')
        entry = self.packages[name]
        if historical:
            target = f"packages/{name}/{manifest['version']}.dpk"
        else:
            self.dev.require(all(manifest.get(field) == entry[field] for field in ('version', 'arch')),
                             'Archive identity does not match the signed repository index')
            target = entry['target']
        info = self.updater.get_targetinfo(target)
        self.dev.require(info is not None and 0 < info.length <= 300 * 1024 * 1024,
                         'Missing or oversized signed package target')
        with open(archive, 'rb') as stream:
            info.verify_length_and_hashes(stream)
        return {'type': 'tuf', 'target': target, 'sha256': self.dev.digest(archive),
                'bootstrap_sha256': self.anchor_hash, 'verified_at': self.started}


def provision(root, args, dev):
    """Pin an out-of-band trust root. Never replace an existing trust identity."""
    try:
        from tuf.api.metadata import Metadata, Root
    except ImportError as exc:
        raise ValueError('Trust provisioning requires TUF runtime dependencies') from exc
    dev.require(re.fullmatch('[0-9a-fA-F]{64}', args.sha256) is not None, 'Invalid root fingerprint')
    with open(args.root_file, 'rb') as stream:
        data = stream.read(512001)
    dev.require(len(data) <= 512000 and hashlib.sha256(data).hexdigest() == args.sha256.lower(),
                'Trust root fingerprint mismatch')
    try:
        metadata = Metadata.from_bytes(data)
        dev.require(isinstance(metadata.signed, Root) and not metadata.signed.is_expired(),
                    'Trust root must be current root metadata')
        metadata.verify_delegate('root', metadata)
    except Exception as exc:
        raise ValueError('Invalid trust root: ' + str(exc)) from exc
    config = {'metadata_url': validate_url(args.metadata_url, args.allow_loopback_http),
              'targets_url': validate_url(args.targets_url, args.allow_loopback_http),
              'allow_loopback_http': args.allow_loopback_http}
    with dev.database(root):
        anchor = dev.target(root, 'etc/devos/trusted-root.json')
        config_path = dev.target(root, 'etc/devos/repository.json')
        dev.require(not anchor.exists() or anchor.read_bytes() == data,
                    'A different trust root is already provisioned; use authenticated TUF rotation')
        dev.require(not config_path.exists() or json.loads(config_path.read_text()) == config,
                    'Different repository endpoints are already configured')
        dev.durable_mkdir(anchor.parent)
        # Enforce the policy first: an interrupted initial setup remains fail-closed.
        dev.write_json_atomic({'version': 1, 'require_signed': True, 'allow_unsigned_override': False},
                              dev.target(root, 'etc/devos/package-policy.json'))
        if not anchor.exists():
            # Preserve exact bootstrap bytes so the operator's fingerprint remains valid.
            import os
            import tempfile
            fd, temp = tempfile.mkstemp(dir=anchor.parent)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(data)
                    os.chmod(temp, 0o644)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp, anchor)
                dev.sync_directory(anchor.parent)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
        dev.write_json_atomic(config, config_path)
    print('Provisioned trusted root: ' + args.sha256.lower())
    return 0


def dispatch(root, args, dev):
    try:
        with dev.database(root) as (db, dbpath):
            repository = Repository(root, dev)
            packages = repository.refresh()
            if args.command == 'update':
                print('Verified repository metadata: ' + str(len(packages)) + ' packages')
            elif args.command == 'system-fetch':
                manifest, artifacts = repository.fetch_system(minimum_sequence=args.minimum_sequence)
                print(json.dumps({'manifest': manifest, 'artifacts': {name: str(path) for name, path in artifacts.items()}}, indent=2))
            elif args.command == 'fetch':
                path, entry = repository.fetch(args.name)
                print('Verified download: ' + args.name + ' ' + entry['version'])
                print(path)
            elif args.command == 'install':
                import dev_plan
                dev_plan.install(root, args.package, db, dbpath, repository, dev)
            elif args.command == 'upgrade':
                dev.require(args.name in db, 'Package is not installed')
                dev.require(args.name in packages, 'Package is not in the signed repository index')
                if packages[args.name]['version'] == db[args.name]['version']:
                    print('Already up to date: ' + args.name)
                else:
                    import dev_plan
                    dev_plan.install(root, args.name, db, dbpath, repository, dev, upgrade=True)
        return 0
    except ImportError as exc:
        raise ValueError('Missing repository runtime dependency') from exc
    except Exception as exc:
        # TUF exposes several dedicated verification/download exceptions. Convert
        # them to the CLI's standard failure without falling back to unsigned data.
        if type(exc).__module__.startswith(('tuf.', 'securesystemslib.', 'urllib3.')):
            raise ValueError('Repository verification failed: ' + str(exc)) from exc
        raise
