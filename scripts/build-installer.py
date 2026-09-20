#!/usr/bin/env python3
"""Build an offline UEFI installer ISO. Run on Linux under fakeroot."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
IMAGES = PROJECT / 'out/buildroot/images'
OUTPUT = PROJECT / 'out/installer'


def run(*args, **kwargs):
    subprocess.run(args, check=True, **kwargs)


def write(path, content, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(mode)


def sanitize(root):
    etc = root / 'etc'
    passwd = (etc / 'passwd').read_text().splitlines()
    removed = {line.split(':')[0] for line in passwd if line.split(':')[2] == '1000'}
    write(etc / 'passwd', '\n'.join(line for line in passwd if line.split(':')[0] not in removed) + '\n')
    shadow = []
    for line in (etc / 'shadow').read_text().splitlines():
        fields = line.split(':')
        if fields[0] in removed:
            continue
        if fields[0] == 'root':
            fields[1] = '*'
        shadow.append(':'.join(fields))
    write(etc / 'shadow', '\n'.join(shadow) + '\n', 0o600)
    groups = []
    for line in (etc / 'group').read_text().splitlines():
        fields = line.split(':')
        if fields[2] == '1000':
            continue
        fields[3] = ','.join(name for name in fields[3].split(',') if name not in removed)
        groups.append(':'.join(fields))
    write(etc / 'group', '\n'.join(groups) + '\n')
    for username in removed:
        home = root / 'home' / username
        if home.is_dir() and not home.is_symlink():
            shutil.rmtree(home)
    for name in ('gshadow', 'machine-id', 'devos-live'):
        path = etc / name
        if path.exists() or path.is_symlink():
            path.unlink()
    # The live installer marker and automatic root shells are never in the installed payload.
    return sorted({line.split(':')[0] for line in (etc / 'passwd').read_text().splitlines()} |
                  {line.split(':')[0] for line in groups})


def build():
    if not os.environ.get('FAKEROOTKEY'):
        raise SystemExit('Run: fakeroot -- python3 scripts/build-installer.py')
    for tool in ('tar', 'find', 'cpio', 'gzip', 'grub-mkrescue', 'xorriso'):
        if not shutil.which(tool):
            raise SystemExit('Missing host tool: ' + tool)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='installer-stage-', dir=PROJECT / 'out') as stage:
        stage = Path(stage)
        base, live, iso = stage / 'base', stage / 'live', stage / 'iso'
        base.mkdir(); live.mkdir(); (iso / 'boot/grub').mkdir(parents=True)
        run('tar', '--numeric-owner', '-xzpf', str(IMAGES / 'rootfs.tar.gz'), '-C', str(base))
        reserved = sanitize(base)
        payload_tar = stage / 'rootfs.tar.gz'
        run('tar', '--numeric-owner', '-czpf', str(payload_tar), '-C', str(base), '.')
        run('tar', '--numeric-owner', '-xzpf', str(payload_tar), '-C', str(live))
        payload = live / 'opt/devos-installer'
        payload.mkdir(parents=True)
        shutil.copyfile(payload_tar, payload / 'rootfs.tar.gz')
        shutil.copyfile(IMAGES / 'bzImage', payload / 'bzImage')
        files = {}
        for name in ('rootfs.tar.gz', 'bzImage'):
            with (payload / name).open('rb') as stream:
                files[name] = hashlib.file_digest(stream, 'sha256').hexdigest()
        write(payload / 'manifest.json', json.dumps({'version': '0.1', 'files': files,
                                                    'reserved_names': reserved}, indent=2) + '\n')
        write(live / 'etc/devos-live', 'Dev OS offline installer\n')
        write(live / 'init', '#!/bin/sh\nmount -t proc proc /proc\nmount -t sysfs sysfs /sys\n'
              'mount -t devtmpfs devtmpfs /dev\nexec /sbin/init\n', 0o755)
        console = live / 'dev/console'
        if not console.exists():
            os.mknod(console, stat.S_IFCHR | 0o600, os.makedev(5, 1))
        write(live / 'etc/inittab', '::sysinit:/bin/mkdir -p /dev/pts /dev/shm /run /tmp\n'
              '::sysinit:/bin/mount -a\n::sysinit:/etc/init.d/rcS\n'
              'tty1::respawn:/usr/sbin/devos-live-shell\n'
              'ttyS0::respawn:/usr/sbin/devos-live-shell\n'
              '::ctrlaltdel:/sbin/reboot\n::shutdown:/bin/umount -a -r\n')
        write(live / 'usr/sbin/devos-live-shell', '#!/bin/sh\n'
              'echo "Dev OS live setup: run dev install-system to begin."\n'
              'export PS1="DEVOS-LIVE# "\nexec /bin/sh -i\n', 0o755)
        initramfs = iso / 'boot/live.cpio.gz'
        with initramfs.open('wb') as output:
            find = subprocess.Popen(['find', '.', '-print0'], cwd=live, stdout=subprocess.PIPE)
            cpio = subprocess.Popen(['cpio', '--null', '-o', '--format=newc', '--owner=0:0'],
                                    cwd=live, stdin=find.stdout, stdout=subprocess.PIPE)
            find.stdout.close()
            gzip = subprocess.Popen(['gzip', '-1'], stdin=cpio.stdout, stdout=output)
            cpio.stdout.close()
            statuses = [gzip.wait(), cpio.wait(), find.wait()]
            if any(statuses):
                raise RuntimeError('initramfs creation failed')
        shutil.copyfile(IMAGES / 'bzImage', iso / 'boot/vmlinuz')
        write(iso / 'boot/grub/grub.cfg', '''set timeout=10
set default=0
serial --unit=0 --speed=115200
terminal_input console serial
terminal_output console serial
menuentry "Dev OS setup (screen and keyboard)" --hotkey=1 {
    linux /boot/vmlinuz rdinit=/init console=tty0
    initrd /boot/live.cpio.gz
}
menuentry "Dev OS setup (serial console)" --hotkey=2 {
    linux /boot/vmlinuz rdinit=/init console=tty0 console=ttyS0,115200
    initrd /boot/live.cpio.gz
}
''')
        run('grub-mkrescue', '-o', str(OUTPUT / 'dev-os-0.1-installer.iso'), str(iso),
            '--', '-volid', 'DEVOS_LIVE')
        shutil.copyfile(payload / 'manifest.json', OUTPUT / 'payload-manifest.json')
    with (OUTPUT / 'dev-os-0.1-installer.iso').open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    write(OUTPUT / 'SHA256SUMS', checksum + '  dev-os-0.1-installer.iso\n')
    print('Installer ISO: ' + str(OUTPUT / 'dev-os-0.1-installer.iso'))


if __name__ == '__main__':
    build()
