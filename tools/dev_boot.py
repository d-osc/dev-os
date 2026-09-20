"""GRUB configuration for two root slots and a one-boot trial.

This is the boot-policy component, not a system-image installer. The caller must
authenticate/stage the inactive root and kernel before scheduling its trial.
"""
from pathlib import Path
import os
import subprocess
import tempfile
import uuid


def identifier(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('Expected a canonical filesystem/partition UUID')
    return value


def render(boot_uuid, roots, confirmed, *, serial=False):
    """Only the confirmed slot is default if the environment cannot be read/written."""
    boot_uuid = identifier(boot_uuid)
    if not isinstance(roots, dict) or set(roots) != {'A', 'B'} or confirmed not in roots:
        raise ValueError('Exactly two root slots and one confirmed slot are required')
    roots = {slot: identifier(value) for slot, value in roots.items()}
    if roots['A'] == roots['B']:
        raise ValueError('Root slots must be distinct partitions')
    lines = [
        '# Dev OS A/B boot policy. Generated; do not set a trial as the confirmed default.',
        'set timeout=3',
        f'search --no-floppy --fs-uuid --set=devos_boot {boot_uuid}',
        f'set default=devos-{confirmed}',
        # GRUB's fallback parser consumes numeric indices, unlike default which
        # accepts menu IDs. A menu ID here passed syntax checking but failed the
        # real missing-kernel UEFI test.
        f'set fallback={0 if confirmed == "A" else 1}',
        'set next_entry=',
        'if load_env -f ($devos_boot)/grub/devos.env next_entry; then',
        '  if [ "$next_entry" = "devos-A" -o "$next_entry" = "devos-B" ]; then',
        '    set devos_trial="$next_entry"',
        '    set next_entry=',
        # Refuse the trial if its one-shot marker cannot be consumed. Otherwise
        # a bad kernel could become a permanent boot loop on a read-only disk.
        '    if save_env -f ($devos_boot)/grub/devos.env next_entry; then',
        '      set default="$devos_trial"',
        '    fi',
        '  fi',
        'fi',
    ]
    console = ' console=ttyS0,115200' if serial else ''
    for slot in ('A', 'B'):
        lines += [f'menuentry "Dev OS slot {slot}" --id devos-{slot} {{',
                  f'  linux ($devos_boot)/devos/{slot}/vmlinuz root=PARTUUID={roots[slot]} '
                  f'rootwait rw panic=10 devos.slot={slot} console=tty0{console}', '}']
    return '\n'.join(lines) + '\n'


def sync(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_config(boot, boot_uuid, roots, confirmed, *, serial=False):
    """Atomically publish the confirmed fallback configuration on the boot filesystem."""
    content = render(boot_uuid, roots, confirmed, serial=serial)
    directory = Path(boot) / 'grub'
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='devos-cfg-', dir=directory)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(content)
            os.fchmod(stream.fileno(), 0o644)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, directory / 'grub.cfg')
        sync(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def environment(boot, *, trial=None, initialize=False):
    """Use grub-editenv's format; never fabricate or resize the environment block."""
    if trial not in (None, 'A', 'B'):
        raise ValueError('Invalid trial slot')
    path = Path(boot) / 'grub/devos.env'
    if initialize:
        if path.exists() or path.is_symlink():
            raise ValueError('Boot environment already exists')
        subprocess.run(['grub-editenv', str(path), 'create'], check=True, capture_output=True)
    if not path.is_file() or path.is_symlink():
        raise ValueError('Boot environment must be a regular file')
    command = ['grub-editenv', str(path)]
    command += ['unset', 'next_entry'] if trial is None else ['set', 'next_entry=devos-' + trial]
    subprocess.run(command, check=True, capture_output=True)
    with path.open('r+b') as stream:
        os.fsync(stream.fileno())
    sync(path.parent)
