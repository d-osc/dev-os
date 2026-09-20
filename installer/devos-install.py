#!/usr/bin/env python3
"""Interactive whole-disk UEFI installer. Runs only inside Dev OS live media."""
import ctypes
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid

PAYLOAD = Path('/opt/devos-installer')
MIN_DISK = 16 * 1024**3


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def descendants(node):
    yield node
    for child in node.get('children', []):
        yield from descendants(child)


def rejection(disk, swaps=()):
    if disk.get('type') != 'disk':
        return 'not a whole disk'
    if disk.get('ro'):
        return 'read-only'
    if int(disk.get('size') or 0) < MIN_DISK:
        return 'smaller than 16 GiB (A/B installation requires two root slots)'
    for node in descendants(disk):
        if any(node.get('mountpoints') or []):
            return 'has mounted filesystems'
        if node.get('name') in swaps:
            return 'has active swap'
        if node.get('label') == 'DEVOS_LIVE' or node.get('fstype') == 'iso9660':
            return 'installer/optical media'
        if node.get('type') not in ('disk', 'part'):
            return 'contains a mapped or RAID device'
        holders = Path('/sys/class/block') / Path(node['name']).name / 'holders'
        if holders.exists() and any(holders.iterdir()):
            return 'device has active holders'
    return None


def disks():
    output = run('lsblk', '--json', '--bytes', '--paths', '--output',
                 'NAME,TYPE,SIZE,MODEL,SERIAL,MAJ:MIN,RM,RO,MOUNTPOINTS,LABEL,FSTYPE',
                 capture_output=True)
    swaps = [line.split()[0] for line in Path('/proc/swaps').read_text().splitlines()[1:]]
    result = []
    for disk in json.loads(output.stdout)['blockdevices']:
        if disk.get('type') == 'disk':
            disk['blocked'] = rejection(disk, swaps)
            result.append(disk)
    return result


def identity(disk):
    return tuple(disk.get(k) for k in ('name', 'size', 'serial', 'maj:min', 'model'))


def password_hash(password):
    for name in ('libcrypt.so.2', 'libcrypt.so.1'):
        try:
            lib = ctypes.CDLL(name)
            break
        except OSError:
            pass
    else:
        raise RuntimeError('libcrypt is unavailable')
    lib.crypt.argtypes = (ctypes.c_char_p, ctypes.c_char_p)
    lib.crypt.restype = ctypes.c_char_p
    salt = '$6$' + secrets.token_hex(8) + '$'
    encoded = lib.crypt(password.encode(), salt.encode())
    if not encoded or not encoded.startswith(b'$6$'):
        raise RuntimeError('Unable to hash password')
    return encoded.decode()


def ask_password(label):
    while True:
        first = getpass.getpass(label + ': ')
        if len(first) < 12:
            print('Use at least 12 characters.')
            continue
        if first == getpass.getpass('Confirm ' + label.lower() + ': '):
            return password_hash(first)
        print('Passwords did not match.')


def verify_payload():
    metadata = json.loads((PAYLOAD / 'manifest.json').read_text())
    expected = {'rootfs.tar.gz', 'bzImage'}
    if set(metadata['files']) != expected:
        raise RuntimeError('Invalid installer manifest')
    for name, checksum in metadata['files'].items():
        with (PAYLOAD / name).open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != checksum:
            raise RuntimeError('Installer checksum mismatch: ' + name)
    return metadata


def partition_name(disk, number):
    return disk + ('p' if disk[-1].isdigit() else '') + str(number)


def system_layout():
    """Dedicated boot + two bounded root slots; remaining space belongs to /home."""
    names = ('efi', 'boot', 'A', 'B', 'home')
    partitions = {name: {'number': index + 1, 'partuuid': str(uuid.uuid4()),
                         'uuid': str(uuid.uuid4())} for index, name in enumerate(names)}
    # FAT has its own volume-ID format; EFI is addressed by GPT PARTUUID.
    del partitions['efi']['uuid']
    sizes = {'efi': '512MiB', 'boot': '256MiB', 'A': '4096MiB', 'B': '4096MiB'}
    lines = ['label: gpt']
    for name in names:
        parts = (['start=1MiB'] if name == 'efi' else [])
        if name in sizes:
            parts.append('size=' + sizes[name])
        parts += ['type=' + ('U' if name == 'efi' else 'L'), 'uuid=' + partitions[name]['partuuid']]
        lines.append(', '.join(parts))
    return partitions, '\n'.join(lines) + '\n'


def configure_target(target, username, hostname, user_hash, root_hash, fs_uuid, part_uuid, esp_uuid, system=None):
    etc = target / 'etc'
    passwd = (etc / 'passwd').read_text().splitlines()
    if any(line.split(':')[0] == username for line in passwd):
        raise RuntimeError('Username collides with a system account')
    passwd.append(f'{username}:x:1000:1000:Dev OS user:/home/{username}:/bin/sh')
    (etc / 'passwd').write_text('\n'.join(passwd) + '\n')
    shadow = [f'root:{root_hash}:19000:0:99999:7:::' if line.startswith('root:') else line
              for line in (etc / 'shadow').read_text().splitlines()]
    shadow.append(f'{username}:{user_hash}:19000:0:99999:7:::')
    (etc / 'shadow').write_text('\n'.join(shadow) + '\n')
    (etc / 'shadow').chmod(0o600)
    groups = (etc / 'group').read_text().splitlines()
    existing_names = {line.split(':')[0] for line in groups}
    if username in existing_names or any(line.split(':')[2] == '1000' for line in groups):
        raise RuntimeError('Primary group collides with a system group')
    groups.append(f'{username}:x:1000:')
    wheel = False
    for index, line in enumerate(groups):
        if line.startswith('wheel:'):
            fields = line.split(':')
            fields[3] = ','.join(filter(None, [fields[3], username]))
            groups[index] = ':'.join(fields)
            wheel = True
    if not wheel:
        groups.append(f'wheel:x:10:{username}')
    (etc / 'group').write_text('\n'.join(groups) + '\n')
    home = target / 'home' / username
    home.mkdir(mode=0o700)
    os.chown(home, 1000, 1000)
    (etc / 'hostname').write_text(hostname + '\n')
    (etc / 'hosts').write_text(f'127.0.0.1 localhost\n127.0.1.1 {hostname}\n::1 localhost\n')
    fstab = [line for line in (etc / 'fstab').read_text().splitlines()
             if not (line.strip() and not line.startswith('#') and line.split()[1] in ('/', '/boot/efi'))]
    fstab += [f'UUID={fs_uuid} / ext4 defaults,noatime 0 1',
              f'PARTUUID={esp_uuid} /boot/efi vfat defaults,umask=0077 0 2']
    (etc / 'fstab').write_text('\n'.join(fstab) + '\n')
    serial = 'console=ttyS0' in Path('/proc/cmdline').read_text()
    lines = [line for line in (etc / 'inittab').read_text().splitlines()
             if 'getty' not in line and 'GENERIC_SERIAL' not in line]
    # libmount resolves UUID/PARTUUID via sysfs, including the early root remount.
    lines.insert(0, '::sysinit:/bin/mount -t sysfs sysfs /sys')
    lines.append('tty1::respawn:/sbin/getty -L tty1 0 linux')
    if serial:
        lines.append('ttyS0::respawn:/sbin/getty -L ttyS0 115200 vt100')
    (etc / 'inittab').write_text('\n'.join(lines) + '\n')
    commandline = f'root=PARTUUID={part_uuid} rootwait rw console=tty0'
    if serial:
        commandline += ' console=ttyS0,115200'
    config = ('set timeout=2\nset default=0\n'
              'menuentry "Dev OS" {\n'
              f'  search --no-floppy --fs-uuid --set=root {fs_uuid}\n'
              f'  linux /boot/vmlinuz {commandline}\n}}\n')
    (target / 'boot/grub').mkdir(parents=True, exist_ok=True)
    (target / 'boot/grub/grub.cfg').write_text(config)
    (etc / 'devos-install.json').write_text(json.dumps({
        'version': '0.1', 'firmware': 'UEFI', 'root_partuuid': part_uuid,
        'root_uuid': fs_uuid, 'username': username, 'hostname': hostname}, indent=2) + '\n')
    if system is not None:
        # Source checkout and installed live-image locations.
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
        sys.path.append('/usr/lib/devos')
        import dev_boot
        fstab = [line for line in (etc / 'fstab').read_text().splitlines()
                 if not (line.strip() and not line.startswith('#') and line.split()[1] in ('/boot', '/home'))]
        # Parents must be mounted before children: /boot precedes /boot/efi.
        efi_entry = f'PARTUUID={esp_uuid} /boot/efi vfat defaults,umask=0077 0 2'
        fstab.remove(efi_entry)
        fstab += [f'UUID={system["boot"]["uuid"]} /boot ext4 defaults,noatime 0 2', efi_entry,
                  f'UUID={system["home"]["uuid"]} /home ext4 defaults,noatime 0 2']
        (etc / 'fstab').write_text('\n'.join(fstab) + '\n')
        dev_boot.publish_config(target / 'boot', system['boot']['uuid'],
                                {slot: system[slot]['partuuid'] for slot in ('A', 'B')}, 'A', serial=serial)
        dev_boot.environment(target / 'boot', initialize=True)
        (etc / 'devos-system.json').write_text(json.dumps({
            'version': 1, 'layout': 'ab', 'slot': 'A', 'partitions': system,
            'shared_mounts': ['/home'], 'slots': {'A': {'initialized': True}, 'B': {'initialized': False}}
        }, indent=2) + '\n')


def install(disk, username, hostname, user_hash, root_hash):
    fresh = next((entry for entry in disks() if entry['name'] == disk['name']), None)
    if not fresh or fresh['blocked'] or identity(fresh) != identity(disk):
        raise RuntimeError('Disk changed or became busy. Restart setup.')
    path = disk['name']
    if not stat.S_ISBLK(os.stat(path).st_mode):
        raise RuntimeError('Selected target is not a block device')
    system, layout = system_layout()
    print('Partitioning ' + path + ' ...', flush=True)
    # There is deliberately no unattended / --yes entry point.
    run('sfdisk', '--wipe', 'always', '--wipe-partitions', 'always', path, input=layout)
    run('blockdev', '--rereadpt', path)
    run('mdev', '-s')
    devices = {name: partition_name(path, entry['number']) for name, entry in system.items()}
    esp, root = devices['efi'], devices['A']
    for _ in range(50):
        if all(Path(device).exists() for device in devices.values()):
            break
        time.sleep(0.1)
    else:
        raise RuntimeError('Partition devices did not appear')
    run('mkfs.fat', '-F', '32', '-n', 'DEVOS_EFI', esp)
    for name in ('boot', 'A', 'B', 'home'):
        run('mkfs.ext4', '-F', '-U', system[name]['uuid'], '-L', 'DEVOS_' + name.upper(), devices[name])
    target = Path(tempfile.mkdtemp(prefix='devos-target-', dir='/mnt'))
    mounted = []
    try:
        run('mount', root, str(target))
        mounted.append(target)
        # BusyBox tar restores stored modes by default; GNU tar's -p is not portable here.
        run('tar', '-xzf', str(PAYLOAD / 'rootfs.tar.gz'), '--numeric-owner', '-C', str(target))
        for name, mountpoint in (('boot', target / 'boot'), ('home', target / 'home')):
            mountpoint.mkdir(parents=True, exist_ok=True)
            run('mount', devices[name], str(mountpoint))
            mounted.append(mountpoint)
        efi = target / 'boot/efi'
        efi.mkdir(parents=True, exist_ok=True)
        run('mount', esp, str(efi))
        mounted.append(efi)
        kernel = target / 'boot/devos/A/vmlinuz'
        kernel.parent.mkdir(parents=True)
        shutil.copyfile(PAYLOAD / 'bzImage', kernel)
        configure_target(target, username, hostname, user_hash, root_hash,
                         system['A']['uuid'], system['A']['partuuid'], system['efi']['partuuid'], system)
        run('grub-install', '--target=x86_64-efi', '--efi-directory=' + str(efi),
            '--boot-directory=' + str(target / 'boot'), '--removable', '--no-nvram', path)
        os.sync()
    finally:
        # Never recursively delete this directory: an unmount may have failed.
        for mounted_path in reversed(mounted):
            run('umount', str(mounted_path))
        target.rmdir()
    print('\nINSTALLATION COMPLETE', flush=True)
    print('Remove the installer USB/ISO, select the target disk in the UEFI boot menu, then reboot.')
    print('Login: ' + username + '. sudo uses your user password; su uses the root password.')


def main():
    if len(sys.argv) != 1:
        raise RuntimeError('This installer is interactive; no command-line options are accepted')
    if os.geteuid() != 0 or not Path('/etc/devos-live').is_file():
        raise RuntimeError('Boot Dev OS live installer media and run dev install-system as root')
    if not Path('/sys/firmware/efi').is_dir():
        raise RuntimeError('Boot the installer in UEFI mode. Legacy BIOS installation is not supported.')
    for tool in ('sfdisk', 'lsblk', 'blockdev', 'mdev', 'mkfs.fat', 'mkfs.ext4', 'mount', 'umount', 'tar', 'grub-install', 'grub-editenv'):
        if not shutil.which(tool):
            raise RuntimeError('Missing required installer tool: ' + tool)
    print('Dev OS setup - x86_64 UEFI, whole-disk A/B installation (minimum 16 GiB)')
    print('Creates separate boot, two 4 GiB system slots and shared /home. Slot B starts empty.')
    print('This will ERASE ALL DATA on the disk you select. No dual boot or partition resizing.')
    print('Verifying installer files ...', flush=True)
    metadata = verify_payload()
    password_hash(secrets.token_urlsafe(16))  # Check the runtime before asking for credentials.
    run('tar', '-tzf', str(PAYLOAD / 'rootfs.tar.gz'), '--numeric-owner',
        stdout=subprocess.DEVNULL)  # Verify extraction support before any disk writes.
    choices = disks()
    for entry in choices:
        model = (entry.get('model') or 'unknown model').strip()
        print(f"{entry['name']}  {entry['size'] / 1024**3:.1f} GiB  {model}  "
              f"serial={entry.get('serial') or '-'}  {entry['blocked'] or 'available'}")
    selected = input('Target disk (full path, or Enter to cancel): ').strip()
    if not selected:
        print('Cancelled. No disk changes.')
        return
    disk = next((entry for entry in choices if entry['name'] == selected), None)
    if disk is None or disk['blocked']:
        raise RuntimeError('Target is not an available whole disk')
    username = input('Username [dev]: ').strip() or 'dev'
    if not re.fullmatch('[a-z][a-z0-9_-]{0,30}', username) or username in metadata['reserved_names']:
        raise RuntimeError('Invalid or reserved username')
    hostname = input('Hostname [dev-os]: ').strip() or 'dev-os'
    if not re.fullmatch('[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', hostname):
        raise RuntimeError('Invalid hostname')
    user_hash = ask_password('User password')
    root_hash = ask_password('Root password')
    print(f'\nERASE {selected}: {disk["size"] / 1024**3:.1f} GiB')
    print('Layout: GPT; 512 MiB EFI System Partition; remaining space ext4 for Dev OS.')
    print('Account: ' + username + '; hostname: ' + hostname)
    if input(f'Type ERASE {selected} to install: ') != f'ERASE {selected}':
        print('Cancelled. No disk changes.')
        return
    install(disk, username, hostname, user_hash, root_hash)


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print('\nStopped. If partitioning already started, the selected disk may be incomplete.', file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print('Setup failed: ' + str(exc), file=sys.stderr)
        sys.exit(1)
