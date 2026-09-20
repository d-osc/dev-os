#!/usr/bin/env python3
"""Offline TUF publisher for Dev OS. Run on Linux/WSL with encrypted signing keys.

Public generations are immutable. Switching `current` is an atomic symlink rename.
No network upload, repository deployment, or production trust provisioning occurs.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import uuid

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    BestAvailableEncryption, Encoding, PrivateFormat, load_pem_private_key)
from securesystemslib.signer import CryptoSigner
from tuf.api.metadata import Metadata, Root, Targets, Snapshot, Timestamp, MetaFile, TargetFile

SPEC = importlib.util.spec_from_file_location('dev_publisher_core', Path(__file__).with_name('dev.py'))
dev = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dev)
COUNTS = {'root': 3, 'targets': 3, 'snapshot': 1, 'timestamp': 1}


def checkpoint(label):
    """Fault-injection seam; no environment-controlled hooks."""


def secure_write(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    dev.sync_directory(path.parent)


def create_role(keys, role, password):
    result = []
    for _ in range(COUNTS[role]):
        private = Ed25519PrivateKey.generate()
        signer = CryptoSigner(private)
        filename = role + '-' + signer.public_key.keyid + '.pem'
        data = private.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, BestAvailableEncryption(password))
        secure_write(keys / filename, data)
        result.append(filename)
    return result


def signers(keys, state, role, password):
    result = []
    for name in state['roles'][role]:
        path = keys / name
        dev.require(path.parent.resolve() == keys.resolve() and not path.is_symlink(), 'Invalid private key path')
        if not path.exists():
            continue
        dev.require(path.stat().st_mode & 0o077 == 0, 'Private key permissions must be 0600')
        result.append(CryptoSigner(load_pem_private_key(path.read_bytes(), password)))
    required = 2 if role in ('root', 'targets') else 1
    dev.require(len(result) >= required, 'Not enough available signing keys for role: ' + role)
    return result


def sign(metadata, keys, state, role, password):
    for i, signer in enumerate(signers(keys, state, role, password)):
        metadata.sign(signer, append=i > 0)


def atomic_bytes(path, data):
    dev.durable_mkdir(path.parent)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.write-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            os.chmod(temp, 0o644)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        dev.sync_directory(path.parent)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def immutable(path, data):
    if path.exists():
        dev.require(path.read_bytes() == data, 'Attempt to change an immutable repository object')
    else:
        atomic_bytes(path, data)


def paths(keys):
    dev.require(os.name == 'posix', 'Publisher requires Linux/WSL filesystem semantics')
    keys = Path(keys).resolve()
    dev.require(keys.is_dir() and keys.stat().st_mode & 0o077 == 0,
                'Signing directory must have mode 0700')
    state = json.loads((keys / 'publisher.json').read_text())
    public = Path(state['public']).resolve()
    return keys, public, state


def save_state(keys, state):
    dev.write_json_atomic(state, keys / 'publisher.json')


def select_generation(public, version):
    link = public / ('.current-' + uuid.uuid4().hex)
    try:
        os.symlink('generations/' + str(version), link)
        os.replace(link, public / 'current')
        dev.sync_directory(public)
    finally:
        if link.is_symlink():
            link.unlink()


def recover(keys, public, state):
    current = public / 'current'
    actual = os.readlink(current) if current.is_symlink() else None
    expected = 'generations/' + str(state['current']) if state['current'] else None
    pending = state.get('pending')
    if pending is not None:
        dev.require(actual in (expected, 'generations/' + str(pending)), 'Publisher pointer changed unexpectedly')
        candidate = public / 'generations' / str(pending)
        if candidate.is_dir():
            # Only complete, flushed generations are renamed to a numeric path.
            select_generation(public, pending)
            state['current'] = pending
        else:
            dev.require(actual == expected, 'Published generation is missing')
        state['pending'] = None
        save_state(keys, state)
    else:
        dev.require(actual == expected, 'Publisher pointer changed unexpectedly')


def initialize(public, keys, password):
    dev.require(os.name == 'posix', 'Publisher requires Linux/WSL')
    public, keys = Path(public).resolve(), Path(keys).resolve()
    dev.require(len(password) >= 16, 'Signing passphrase must contain at least 16 bytes')
    dev.require(not public.exists() and not keys.exists(), 'Use new public and signing directories')
    dev.require(not keys.is_relative_to(public) and not public.is_relative_to(keys),
                'Public repository and signing directory must be separate')
    keys.mkdir(parents=True, mode=0o700)
    (keys / 'roots').mkdir(mode=0o700)
    public.mkdir(parents=True)
    (public / 'generations').mkdir()
    state = {'version': 1, 'public': str(public), 'roles': {}, 'root_version': 1,
             'next_version': 1, 'current': None, 'pending': None}
    root = Metadata(Root(expires=datetime.now(timezone.utc) + timedelta(days=365), consistent_snapshot=True))
    for role in COUNTS:
        state['roles'][role] = create_role(keys, role, password)
        for signer in signers(keys, state, role, password):
            root.signed.add_key(signer.public_key, role)
        root.signed.roles[role].threshold = 2 if role in ('root', 'targets') else 1
    sign(root, keys, state, 'root', password)
    atomic_bytes(keys / 'roots/1.root.json', root.to_bytes())
    atomic_bytes(public / 'bootstrap-root.json', root.to_bytes())
    save_state(keys, state)
    publish(keys, [], password)
    return hashlib.sha256(root.to_bytes()).hexdigest()


def old_content(keys, public, state):
    if state['current'] is None:
        return {}, {}
    previous = public / 'generations' / str(state['current'])
    root = Metadata.from_file(str(previous / 'metadata/root.json'))
    trusted = keys / 'roots' / (str(root.signed.version) + '.root.json')
    dev.require(trusted.read_bytes() == root.to_bytes(), 'Untrusted publisher generation root')
    targets = Metadata.from_file(str(previous / 'metadata/targets.json'))
    root.verify_delegate('targets', targets)
    info = targets.signed.targets['index.json']
    index = previous / 'targets' / (info.hashes['sha256'] + '.index.json')
    with index.open('rb') as stream:
        info.verify_length_and_hashes(stream)
    return json.loads(index.read_text())['packages'], dict(targets.signed.targets)


def publish(keys, archives, password, *, revoke=None, system_release=None):
    keys, public, _ = paths(keys)
    with dev.database(keys):
        _, _, state = paths(keys)
        recover(keys, public, state)
        packages, target_files = old_content(keys, public, state)
        if revoke is not None:
            name, release = revoke
            target = f'packages/{name}/{release}.dpk'
            dev.require(target in target_files, 'Package version is not published')
            del target_files[target]
            if packages.get(name, {}).get('version') == release:
                del packages[name]
        version = state['next_version']
        state['next_version'] += 1
        state['pending'] = version
        save_state(keys, state)
        checkpoint('reserved')
        generations = public / 'generations'
        work = Path(tempfile.mkdtemp(prefix='.prepare-', dir=generations))
        try:
            if state['current'] is not None:
                shutil.copytree(generations / str(state['current']), work, dirs_exist_ok=True,
                                copy_function=os.link)
            metadata = work / 'metadata'
            targets_dir = work / 'targets'
            metadata.mkdir(exist_ok=True)
            targets_dir.mkdir(exist_ok=True)
            if system_release is not None:
                sys.path.insert(0, str(Path(__file__).resolve().parent))
                import dev_system_release
                with tempfile.TemporaryDirectory(dir=keys) as temporary:
                    stage = Path(temporary)
                    release = dev_system_release.snapshot(system_release, stage)
                    if 'system-index.json' in target_files:
                        previous = target_files['system-index.json']
                        old_index = targets_dir / (previous.hashes['sha256'] + '.system-index.json')
                        with old_index.open('rb') as stream:
                            previous.verify_length_and_hashes(stream)
                        dev.require(release['sequence'] > json.loads(old_index.read_text())['sequence'],
                                    'System release sequence must increase')
                    prefix = f"systems/x86_64/{release['version']}/"
                    for name in ('bzImage', 'rootfs.tar.gz', 'manifest.json'):
                        source = stage / name
                        target = prefix + name
                        info = TargetFile.from_file(target, str(source), ['sha256'])
                        dev.require(target not in target_files or target_files[target].to_dict() == info.to_dict(),
                                    'A published system release cannot be replaced')
                        dest = targets_dir / prefix / (info.hashes['sha256'] + '.' + name)
                        if not dest.exists():
                            dev.durable_copy(source, dest, 0o644)
                        else:
                            with dest.open('rb') as stream:
                                info.verify_length_and_hashes(stream)
                        target_files[target] = info
                    index = json.dumps({'format': 1, 'arch': 'x86_64', 'version': release['version'],
                                        'sequence': release['sequence'], 'target': prefix + 'manifest.json'},
                                       sort_keys=True).encode()
                    checksum = hashlib.sha256(index).hexdigest()
                    immutable(targets_dir / (checksum + '.system-index.json'), index)
                    target_files['system-index.json'] = TargetFile(len(index), {'sha256': checksum}, 'system-index.json')
            for archive in archives:
                with tempfile.TemporaryDirectory(dir=keys) as unpack_dir:
                    # Immutable private snapshot binds validated manifest to published bytes.
                    temporary = Path(unpack_dir)
                    snapshot = dev.archive_snapshot(archive, temporary)
                    m = dev.unpack(snapshot, temporary)
                    target = f"packages/{m['name']}/{m['version']}.dpk"
                    info = TargetFile.from_file(target, str(snapshot), ['sha256'])
                    if target in target_files:
                        dev.require(target_files[target].to_dict() == info.to_dict(),
                                    'A published package version cannot be replaced; bump its version')
                    dest = targets_dir / Path(target).parent / (info.hashes['sha256'] + '.' + Path(target).name)
                    immutable(dest, snapshot.read_bytes())
                    target_files[target] = info
                    packages[m['name']] = {'version': m['version'], 'arch': m['arch'], 'target': target}
            index_data = json.dumps({'version': 1, 'packages': packages}, sort_keys=True).encode()
            index_hash = hashlib.sha256(index_data).hexdigest()
            immutable(targets_dir / (index_hash + '.index.json'), index_data)
            target_files['index.json'] = TargetFile(len(index_data), {'sha256': index_hash}, 'index.json')
            now = datetime.now(timezone.utc)
            targets = Metadata(Targets(version=version, expires=now + timedelta(days=30), targets=target_files))
            sign(targets, keys, state, 'targets', password)
            target_bytes = targets.to_bytes()
            def meta(data):
                return MetaFile(version, len(data), {'sha256': hashlib.sha256(data).hexdigest()})
            snapshot = Metadata(Snapshot(version=version, expires=now + timedelta(days=7),
                                        meta={'targets.json': meta(target_bytes)}))
            sign(snapshot, keys, state, 'snapshot', password)
            snapshot_bytes = snapshot.to_bytes()
            timestamp = Metadata(Timestamp(version=version, expires=now + timedelta(days=1),
                                           snapshot_meta=meta(snapshot_bytes)))
            sign(timestamp, keys, state, 'timestamp', password)
            for role, data in [('targets', target_bytes), ('snapshot', snapshot_bytes)]:
                immutable(metadata / f'{version}.{role}.json', data)
                atomic_bytes(metadata / (role + '.json'), data)
            atomic_bytes(metadata / 'timestamp.json', timestamp.to_bytes())
            for root_version in range(1, state['root_version'] + 1):
                root = keys / 'roots' / f'{root_version}.root.json'
                immutable(metadata / root.name, root.read_bytes())
            atomic_bytes(metadata / 'root.json', (keys / 'roots' / f"{state['root_version']}.root.json").read_bytes())
            # Persist hardlink directory entries inherited from the old generation too.
            for directory in sorted((p for p in work.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
                dev.sync_directory(directory)
            dev.sync_directory(work)
            work.chmod(0o755)
            dev.sync_directory(work)
            os.rename(work, generations / str(version))
            dev.sync_directory(generations)
            checkpoint('generation')
            select_generation(public, version)
            checkpoint('selected')
            state['current'], state['pending'] = version, None
            save_state(keys, state)
            return version
        finally:
            if work.exists():
                shutil.rmtree(work)


def rotate(keys, role, password):
    dev.require(role in COUNTS, 'Invalid role')
    keys, public, _ = paths(keys)
    with dev.database(keys):
        _, _, state = paths(keys)
        recover(keys, public, state)
        root = Metadata.from_file(str(keys / 'roots' / f"{state['root_version']}.root.json"))
        old_root_signers = signers(keys, state, 'root', password)
        for keyid in list(root.signed.roles[role].keyids):
            root.signed.revoke_key(keyid, role)
        state['roles'][role] = create_role(keys, role, password)
        for signer in signers(keys, state, role, password):
            root.signed.add_key(signer.public_key, role)
        root.signed.version += 1
        root.signed.expires = datetime.now(timezone.utc) + timedelta(days=365)
        for i, signer in enumerate(old_root_signers):
            root.sign(signer, append=i > 0)
        for signer in signers(keys, state, 'root', password):
            root.sign(signer, append=True)
        state['root_version'] = root.signed.version
        # An earlier failed rotation can leave an unpublished root at this version.
        # Publication includes only versions committed in publisher.json.
        atomic_bytes(keys / 'roots' / f"{root.signed.version}.root.json", root.to_bytes())
        save_state(keys, state)
    return publish(keys, [], password)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--keys', type=Path, required=True)
    parser.add_argument('--passphrase-file', type=Path, required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('init'); p.add_argument('--public', type=Path, required=True)
    p = commands.add_parser('publish'); p.add_argument('archives', nargs='*', type=Path)
    p.add_argument('--system-release', type=Path)
    p = commands.add_parser('rotate'); p.add_argument('role', choices=list(COUNTS))
    p = commands.add_parser('revoke'); p.add_argument('name'); p.add_argument('version')
    args = parser.parse_args()
    try:
        dev.require(args.passphrase_file.stat().st_mode & 0o077 == 0,
                    'Passphrase file must have mode 0600')
        password = args.passphrase_file.read_bytes().rstrip(b'\r\n')
        if args.command == 'init':
            print('Bootstrap root SHA-256: ' + initialize(args.public, args.keys, password))
        elif args.command == 'publish':
            print('Published local generation ' + str(publish(args.keys, args.archives, password, system_release=args.system_release)))
        elif args.command == 'rotate':
            print('Rotated role in local generation ' + str(rotate(args.keys, args.role, password)))
        else:
            print('Revoked package in local generation ' + str(publish(args.keys, [], password,
                                                                       revoke=(args.name, args.version))))
    except Exception as exc:
        print('dev-publish: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
