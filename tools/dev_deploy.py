"""One transaction that stages an authenticated release into the inactive slot.

Orchestrates release verification, /etc merge planning, package preservation,
rootfs extraction, machine/slot adaptation, kernel installation and the GRUB
trial schedule. Every mutation of the live system happens last: an interrupted
deployment leaves the inactive slot unreachable because nothing pointed the
bootloader at it yet. Health confirmation after a trial boot, watchdog policy
and known-good rollback are separate unimplemented work; a consumed trial
marker is not proof that the staged system is healthy.
"""
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

RELEASE_STATE = 'var/lib/dev/system/installed-release.json'
JOURNAL = 'var/lib/dev/system/deploy-journal.json'
PHASES = ('prepared', 'extracted', 'merged', 'kernel', 'published', 'scheduled')


def _module(name):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.append('/usr/lib/devos')
    return importlib.import_module(name)


def _run(*command):
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return completed.stdout


def _release_identity(manifest):
    canonical = json.dumps(manifest, sort_keys=True) + '\n'
    return {'version': manifest['version'], 'sequence': manifest['sequence'],
            'manifest_sha256': hashlib.sha256(canonical.encode()).hexdigest()}


def validate_record(record):
    if (not isinstance(record, dict) or set(record) != {'format', 'release', 'etc'}
            or record['format'] != 1):
        raise ValueError('Invalid baseline release record')
    release = record['release']
    if (not isinstance(release, dict) or set(release) != {'version', 'sequence', 'manifest_sha256'}
            or not isinstance(release['version'], str)
            or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._+-]{0,79}', release['version'])
            or type(release['sequence']) is not int or not 1 <= release['sequence'] <= 2**53 - 1
            or not isinstance(release['manifest_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', release['manifest_sha256'])):
        raise ValueError('Invalid baseline release identity')
    if not isinstance(record['etc'], dict) or record['etc'].get('etc', {}).get('type') != 'directory':
        raise ValueError('Invalid baseline configuration inventory')
    return record


def record_from_release(directory):
    """Build a baseline record from a local system-release directory."""
    directory = Path(directory)
    release = _module('dev_system_release')
    config = _module('dev_config')
    manifest = release.load(directory)
    inventory = release.inspect_rootfs(directory / 'rootfs.tar.gz')['files']
    return validate_record({'format': 1, 'release': {
        'version': manifest['version'], 'sequence': manifest['sequence'],
        'manifest_sha256': hashlib.sha256((directory / 'manifest.json').read_bytes()).hexdigest()},
        'etc': config.config_inventory(inventory)})


def baseline_record(root, override=None):
    state = Path(root) / RELEASE_STATE
    if override is not None:
        return record_from_release(override)
    if not state.is_file():
        raise ValueError('No baseline release is recorded for this system; pass --baseline DIRECTORY')
    return validate_record(json.loads(state.read_text()))


def check_sequence(manifest, record):
    if manifest['sequence'] <= record['release']['sequence']:
        raise ValueError('System release must be newer than the installed baseline')


def fstab_kept(text):
    """Lines of an fstab that are not the slot-bound system mounts."""
    kept = []
    for line in text.splitlines():
        fields = line.split()
        if line.startswith('#') or not fields:
            kept.append(line)
        elif len(fields) > 1 and fields[1] in ('/', '/boot', '/boot/efi', '/home'):
            continue
        else:
            kept.append(line)
    return kept


def _validate_observation(observation):
    if not isinstance(observation, dict):
        raise ValueError('Invalid slot observation')
    active, inactive = observation.get('active'), observation.get('inactive')
    if active not in ('A', 'B') or inactive not in ('A', 'B') or active == inactive:
        raise ValueError('Invalid slot observation')
    for key in ('target', 'partuuid', 'uuid'):
        if not isinstance(observation.get(key), str) or not observation[key]:
            raise ValueError('Invalid slot observation: ' + key)
    return observation


def _validate_metadata(metadata, observation):
    if (not isinstance(metadata, dict) or metadata.get('version') != 1 or metadata.get('layout') != 'ab'
            or not isinstance(metadata.get('partitions'), dict)):
        raise ValueError('Unsupported installed system metadata')
    parts = metadata['partitions']
    if set(parts) != {'efi', 'boot', 'A', 'B', 'home'}:
        raise ValueError('Unsupported installed partition layout')
    if parts[observation['inactive']].get('partuuid') != observation['partuuid']:
        raise ValueError('Slot observation does not match installed metadata')
    if parts[observation['inactive']].get('uuid') != observation['uuid']:
        raise ValueError('Slot filesystem identity does not match installed metadata')
    return metadata


def _phase(dev, journal_path, journal, name):
    journal['phase'] = name
    dev.write_json_atomic(journal, journal_path)


def _durable_text(dev, path, text, mode):
    dev.durable_mkdir(path.parent)
    temporary = path.parent / ('.' + path.name + '.devos-new')
    if temporary.exists():
        temporary.unlink()
    with temporary.open('w') as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
        os.fchmod(stream.fileno(), mode)
    os.replace(temporary, path)
    dev.sync_directory(path.parent)


def _apply_packages(dev, live, staged, plan):
    """Transfer the planned package state and re-materialize owned files."""
    database = live / 'var/lib/dev/installed.json'
    if database.is_file():
        dev.durable_copy(database, staged / 'var/lib/dev/installed.json', 0o644)
    archives = 0
    for path, sha in sorted(plan['state'].items()):
        if sha is None: continue
        source = live / path
        dev.require(source.is_file() and dev.digest(source) == sha,
                    'Cached package archive drifted: ' + path)
        dev.durable_copy(source, staged / path, 0o644)
        archives += 1
    files = 0
    for name in sorted(plan['packages']):
        for path, spec in sorted(plan['packages'][name]['files'].items()):
            source = live / path
            dev.require(source.is_file() and dev.digest(source) == spec['sha256'],
                        'Installed package file drifted: ' + path)
            if os.name == 'posix':
                dev.require(os.stat(source).st_mode & 0o7777 == spec['mode'],
                            'Installed package mode drifted: ' + path)
            dev.durable_copy(source, staged / path, spec['mode'])
            files += 1
    return archives, files


def _adapt_slot(dev, live, staged, metadata, observation):
    """Bind the staged root to this machine's inactive slot.

    The release is sanitized and machine-independent; fstab, system metadata
    and the installation record are exactly the state it must not carry.
    """
    parts = metadata['partitions']
    inactive = observation['inactive']
    fstab = staged / 'etc/fstab'
    dev.require(fstab.is_file(), 'Release root filesystem has no /etc/fstab')
    lines = fstab_kept(fstab.read_text())
    lines += [f'UUID={parts[inactive]["uuid"]} / ext4 defaults,noatime 0 1',
              f'UUID={parts["boot"]["uuid"]} /boot ext4 defaults,noatime 0 2',
              f'PARTUUID={parts["efi"]["partuuid"]} /boot/efi vfat defaults,umask=0077 0 2',
              f'UUID={parts["home"]["uuid"]} /home ext4 defaults,noatime 0 2']
    _durable_text(dev, fstab, '\n'.join(lines) + '\n', 0o644)
    _durable_text(dev, staged / 'etc/devos-system.json', json.dumps({
        'version': 1, 'layout': 'ab', 'slot': inactive, 'partitions': parts,
        'shared_mounts': metadata.get('shared_mounts', ['/home']),
        'slots': {'A': {'initialized': True}, 'B': {'initialized': True}}}, indent=2) + '\n', 0o644)
    installed = live / 'etc/devos-install.json'
    if installed.is_file():
        record = json.loads(installed.read_text())
        dev.require(isinstance(record, dict) and isinstance(record.get('root_partuuid'), str)
                    and isinstance(record.get('root_uuid'), str),
                    'Unrecognized installed-system record')
        record['root_partuuid'] = parts[inactive]['partuuid']
        record['root_uuid'] = parts[inactive]['uuid']
        _durable_text(dev, staged / 'etc/devos-install.json',
                      json.dumps(record, indent=2) + '\n', 0o644)


def _install_kernel(dev, source, boot, slot, item):
    """Publish the verified kernel for one slot through a temporary name."""
    directory = Path(boot) / 'devos' / slot
    dev.durable_mkdir(directory)
    temporary = directory / '.vmlinuz.devos-new'
    if temporary.exists():
        temporary.unlink()
    digest, length = hashlib.sha256(), 0
    with Path(source).open('rb') as inp, temporary.open('xb') as out:
        while chunk := inp.read(1024 * 1024):
            length += len(chunk)
            if length > item['length']:
                raise ValueError('Kernel artifact length changed')
            digest.update(chunk)
            out.write(chunk)
    if length != item['length'] or digest.hexdigest() != item['sha256']:
        raise ValueError('Kernel artifact checksum mismatch')
    with temporary.open('ab') as stream:
        os.fsync(stream.fileno())
    os.chmod(temporary, 0o644)
    os.replace(temporary, directory / 'vmlinuz')
    dev.sync_directory(directory)


def deploy(dev, observation, metadata, *, live, boot, staged, artifacts, manifest,
           baseline, serial):
    """Run the complete staging transaction against one inactive slot.

    staged must be an empty, root-owned, caller-mounted view of the inactive
    partition; this function never mounts, formats or authenticates releases
    itself. All live-system writes (kernel, GRUB configuration, trial marker)
    happen after the staged root is complete, and the journal on the live root
    records the last completed phase.
    """
    _validate_observation(observation)
    _validate_metadata(metadata, observation)
    check_sequence(manifest, baseline)
    rootfs = _module('dev_rootfs')
    config = _module('dev_config')
    preserve = _module('dev_preserve')
    boot_policy = _module('dev_boot')
    release_files = rootfs.inspect(artifacts['rootfs.tar.gz'])['files']
    incoming = config.config_inventory(release_files)
    base = baseline['etc']
    current = config.snapshot(live)
    config_plan = config.plan(base, current, incoming)
    dev.require(config_plan['ready'], 'Configuration conflicts: ' +
                '; '.join(item['path'] for item in config_plan['conflicts']))
    database_path = live / 'var/lib/dev/installed.json'
    database = json.loads(database_path.read_text()) if database_path.is_file() else {}
    dev.require(isinstance(database, dict), 'Invalid installed package database')
    package_plan = preserve.plan(database, release_files)
    dev.require(package_plan['ready'], 'Package preservation conflicts: ' +
                '; '.join(item.get('package', '?') + ': ' + item['reason']
                          for item in package_plan['conflicts']))
    state = live / 'var/lib/dev/system'
    dev.durable_mkdir(state)
    journal_path = state / 'deploy-journal.json'
    journal = {'format': 1, 'slot': observation['inactive'],
               'release': _release_identity(manifest), 'phase': 'prepared'}
    dev.write_json_atomic(journal, journal_path)
    item = manifest['files']['rootfs.tar.gz']
    inventory = rootfs.extract(artifacts['rootfs.tar.gz'], staged,
                               length=item['length'], sha256=item['sha256'])
    _phase(dev, journal_path, journal, 'extracted')
    config.apply(live, staged, base, current, incoming)
    archives, files = _apply_packages(dev, live, staged, package_plan)
    _adapt_slot(dev, live, staged, metadata, observation)
    _durable_text(dev, staged / RELEASE_STATE, json.dumps(
        {'format': 1, 'release': _release_identity(manifest), 'etc': incoming}, indent=2) + '\n', 0o644)
    _phase(dev, journal_path, journal, 'merged')
    kernel = manifest['files']['bzImage']
    _install_kernel(dev, artifacts['bzImage'], boot, observation['inactive'], kernel)
    _phase(dev, journal_path, journal, 'kernel')
    parts = metadata['partitions']
    boot_policy.publish_config(boot, parts['boot']['uuid'],
                               {'A': parts['A']['partuuid'], 'B': parts['B']['partuuid']},
                               observation['active'], serial=serial)
    _phase(dev, journal_path, journal, 'published')
    boot_policy.environment(boot, trial=observation['inactive'])
    journal_path.unlink()
    dev.sync_directory(state)
    return {'slot': observation['inactive'], 'release': _release_identity(manifest),
            'config_entries': len(config_plan['entries']),
            'packages': len(package_plan['packages']), 'package_files': files,
            'archives_copied': archives, 'rootfs_files': len(inventory['files']),
            'kernel_sha256': kernel['sha256'], 'scheduled': True}


def dispatch(root, args, dev):
    """Live-system entry point: mount, stage, schedule, unmount."""
    if os.name != 'posix' or os.geteuid() != 0:
        raise ValueError('System deployment requires Linux root')
    import fcntl
    import shutil
    import tempfile
    slots = _module('dev_slots')
    state = Path(root) / 'var/lib/dev/system'
    dev.durable_mkdir(state)
    lock = os.open(state / 'deploy.lock',
                   os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError('Another system deployment is already running') from exc
        if args.cancel:
            slots.observe()
            _module('dev_boot').environment(Path('/boot'), trial=None)
            (state / 'deploy-journal.json').unlink(missing_ok=True)
            dev.sync_directory(state)
            print('Cancelled the scheduled trial boot and cleared the deploy journal')
            return None
        if (state / 'deploy-journal.json').exists():
            print('Overriding the journal of an interrupted deployment')
        observation = slots.observe()
        metadata = json.loads(Path('/etc/devos-system.json').read_text())
        baseline = baseline_record(root, args.baseline)
        with dev.database(Path(root)) as (_, __):
            repository = dev.repository_module().Repository(Path(root), dev)
            manifest, artifacts = repository.fetch_system(
                minimum_sequence=baseline['release']['sequence'] + 1)
            # Revalidate identity immediately before the destructive step.
            dev.require(slots.observe() == observation,
                        'Slot identity changed during deployment preparation')
            dev.require(shutil.which('mkfs.ext4') is not None,
                        'mkfs.ext4 is required on the target to rebuild the inactive slot')
            _run('mkfs.ext4', '-F', '-U', observation['uuid'], observation['target'])
            mountpoint = Path(tempfile.mkdtemp(prefix='devos-deploy-', dir='/mnt'))
            try:
                _run('mount', observation['target'], str(mountpoint))
                try:
                    report = deploy(dev, observation, metadata, live=Path('/'), boot=Path('/boot'),
                                    staged=mountpoint, artifacts=artifacts, manifest=manifest,
                                    baseline=baseline,
                                    serial='console=ttyS0' in Path('/proc/cmdline').read_text())
                finally:
                    _run('umount', str(mountpoint))
            finally:
                mountpoint.rmdir()
        release = report['release']
        print(f"Staged release {release['version']} (sequence {release['sequence']}) "
              f"into slot {report['slot']}")
        print(f"Trial boot scheduled: the next reboot starts slot {report['slot']} once, "
              'then returns to the confirmed slot')
        print('Health confirmation after the trial is not implemented; inspect the trial manually')
        return report
    finally:
        os.close(lock)
