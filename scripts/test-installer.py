#!/usr/bin/env python3
"""Install from the ISO to a new disposable disk, eject ISO, and boot the installed OS."""
import argparse
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import time

import pexpect
from candidate_signed_fixture import create, GUEST

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--disk-type', choices=['virtio', 'nvme', 'sata'], default='virtio')
parser.add_argument('--output-dir', type=Path, help='Fresh directory for this disposable installation')
args = parser.parse_args()
project = Path(__file__).resolve().parents[1]
out = args.output_dir or project / 'out/installer-tests' / args.disk_type
out.mkdir(parents=True, exist_ok=True)

# Read-only QA data disk, never part of the released installer image.
fixture_temp = tempfile.TemporaryDirectory(prefix='devos-installer-fixture-')
fixture_root = Path(fixture_temp.name)
repository_tar = create(fixture_root, project)
fixture_tree = fixture_root / 'tree'; fixture_tree.mkdir()
shutil.copyfile(repository_tar, fixture_tree / 'repository.tar')
probe = 'import pathlib, json, hashlib, subprocess\n' + GUEST.replace('/opt/repository.tar', '/mnt/qa/repository.tar')
# Leave a signed package installed for the reboot-persistence check.
probe = probe.replace('    finally:\n', "        command('install', 'qa-app')\n        state('2')\n    finally:\n")
(fixture_tree / 'probe.py').write_text(probe)
shutil.copyfile(project / 'tools/dev_slots.py', fixture_tree / 'dev_slots.py')
(fixture_tree / 'slots_probe.py').write_text('''import dev_slots, subprocess
result = dev_slots.observe()
assert result['active'] == 'A' and result['inactive'] == 'B', result
subprocess.run(['mkdir', '-p', '/mnt/slot-check'], check=True)
subprocess.run(['mount', '-o', 'ro', result['target'], '/mnt/slot-check'], check=True)
try:
    try:
        dev_slots.observe()
    except ValueError as error:
        assert 'already mounted' in str(error), str(error)
    else:
        raise AssertionError('Mounted inactive slot was accepted')
finally:
    subprocess.run(['umount', '/mnt/slot-check'], check=True)
assert dev_slots.observe() == result
print('SLOT_IDENTITY_AND_MOUNT_REFUSAL_PASSED')
''')
fixture_disk = fixture_root / 'fixture.ext4'
with fixture_disk.open('wb') as stream:
    stream.truncate(32 * 1024**2)
subprocess.run(['mkfs.ext4', '-q', '-F', '-d', str(fixture_tree), str(fixture_disk)], check=True)
disk = out / 'installed.raw'
if disk.exists():
    raise SystemExit('Refusing to overwrite an existing test disk: ' + str(disk))
subprocess.run(['qemu-img', 'create', '-f', 'raw', str(disk), '16G'], check=True)
firmware = out / 'OVMF_VARS.fd'
shutil.copyfile('/usr/share/OVMF/OVMF_VARS_4M.fd', firmware)
user_password, root_password = secrets.token_urlsafe(16), secrets.token_urlsafe(16)
target = {'virtio': '/dev/vda', 'nvme': '/dev/nvme0n1', 'sata': '/dev/sda'}[args.disk_type]
report = {'disk_type': args.disk_type, 'target': target, 'passed': False, 'checks': []}
report['slot_observer_sha256'] = hashlib.sha256((fixture_tree / 'dev_slots.py').read_bytes()).hexdigest()
with (project / 'out/installer/dev-os-0.1-installer.iso').open('rb') as stream:
    report['iso_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
vm = None
log = None
installed_boots = 0


def launch(live):
    global vm, log, installed_boots
    options = ['-accel', 'kvm', '-machine', 'q35', '-m', '2048', '-smp', '2',
               '-nographic', '-no-reboot',
               '-drive', 'if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd',
               '-drive', f'if=pflash,format=raw,file={firmware}',
               '-netdev', 'user,id=net0', '-device', 'virtio-net-pci,netdev=net0']
    if args.disk_type == 'sata':
        options += ['-drive', f'file={disk},format=raw,if=ide']
    else:
        options += ['-drive', f'file={disk},format=raw,if=none,id=osdisk',
                    '-device', 'virtio-blk-pci,drive=osdisk' if args.disk_type == 'virtio'
                    else 'nvme,drive=osdisk,serial=DEVOS_TEST_NVME']
    if live:
        options += ['-cdrom', str(project / 'out/installer/dev-os-0.1-installer.iso'), '-boot', 'order=d']
    else:
        options += ['-boot', 'order=c']
    options += ['-drive', f'file={fixture_disk},format=raw,if=virtio,readonly=on']
    if not live:
        installed_boots += 1
    log = (out / ('live.log' if live else f'installed-{installed_boots}.log')).open('w')
    vm = pexpect.spawn('qemu-system-x86_64', options, encoding='utf-8', timeout=180,
                       dimensions=(40, 180))
    vm.logfile_read = log


def close():
    if vm is not None:
        vm.terminate(force=True)
    if log is not None:
        log.close()


def command(text, expected=0, prompt='DEVOS-LIVE# '):
    vm.sendline(text + "; printf '\\nSETUP_TEST_STATUS=%s\\n' \"$?\"")
    vm.expect(r'\r+\nSETUP_TEST_STATUS=(\d+)\r+\n')
    output = vm.before
    actual = int(vm.match.group(1))
    vm.expect_exact(prompt)
    if actual != expected:
        raise AssertionError(f'{text}: expected {expected}, got {actual}: {output}')
    report['checks'].append(text)
    return output


def secret(prompt, value):
    matched = vm.expect_exact([prompt, 'Setup failed:', 'DEVOS-LIVE# '])
    if matched != 0:
        raise RuntimeError('Installer stopped before credential prompt: ' + prompt)
    vm.logfile_read = None
    vm.sendline(value)
    # Next getpass prompt has echo disabled too. No sent credentials are logged.


def login():
    if vm.expect(['dev-os-test login:', 'grub> ']) != 0:
        raise RuntimeError('Installed disk dropped to the GRUB prompt')
    vm.sendline('tester')
    secret('Password:', user_password)
    vm.expect_exact('tester@dev-os-test:~$ ')
    report['checks'].append('installed login prompt: tester@dev-os-test:~$')
    vm.logfile_read = log
    vm.sendline("export PS1='DEVOS-TEST# '")
    vm.expect_exact('\r\nDEVOS-TEST# ')


try:
    started = time.monotonic()
    launch(True)
    vm.expect('Dev OS setup')
    vm.send('2')  # GRUB's serial-console menu hotkey.
    vm.expect_exact('DEVOS-LIVE# ')
    report['live_boot_seconds'] = round(time.monotonic() - started, 3)
    command('test -d /sys/firmware/efi')
    # Cancelling must not alter even the partition-table area of the disk.
    with disk.open('rb') as stream:
        before = hashlib.sha256(stream.read(1024 * 1024)).hexdigest()
    vm.sendline('dev install-system')
    vm.expect_exact('Target disk (full path, or Enter to cancel): ')
    vm.sendline('')
    vm.expect_exact('Cancelled. No disk changes.')
    vm.expect_exact('DEVOS-LIVE# ')
    with disk.open('rb') as stream:
        assert hashlib.sha256(stream.read(1024 * 1024)).hexdigest() == before
    report['checks'].append('cancel leaves disk partition-table area unchanged')
    for confirmation in ('CANCEL', 'ERASE ' + target):
        vm.sendline('dev install-system')
        vm.expect_exact('Target disk (full path, or Enter to cancel): ')
        vm.sendline(target)
        vm.expect_exact('Username [dev]: '); vm.sendline('tester')
        vm.expect_exact('Hostname [dev-os]: '); vm.sendline('dev-os-test')
        secret('User password: ', user_password)
        secret('Confirm user password: ', user_password)
        secret('Root password: ', root_password)
        secret('Confirm root password: ', root_password)
        vm.expect_exact(f'Type ERASE {target} to install: ')
        vm.logfile_read = log
        vm.sendline(confirmation)
        if confirmation == 'CANCEL':
            vm.expect_exact('Cancelled. No disk changes.')
            vm.expect_exact('DEVOS-LIVE# ')
            with disk.open('rb') as stream:
                assert hashlib.sha256(stream.read(1024 * 1024)).hexdigest() == before
            report['checks'].append('rejecting final erase confirmation leaves partition-table area unchanged')
    if vm.expect_exact(['INSTALLATION COMPLETE', 'Setup failed:'], timeout=240) != 0:
        vm.expect(r'\r+\n')
        raise RuntimeError('Installer failed: ' + vm.before)
    vm.expect_exact('DEVOS-LIVE# ')
    report['checks'].append('interactive disk partition, format, copy, accounts and EFI loader install')
    command('sync')
    close()
    launch(False)  # No CD, no -kernel and no -initrd: boot only the installed disk.
    login()
    for text in ('test "$(id -u)" = 1000', 'test ! -e /etc/devos-live',
                 'test -f /etc/devos-install.json'):
        command(text, prompt='DEVOS-TEST# ')
    vm.sendline("sudo -k; sudo -p 'INSTALL_AUTH: ' id -u")
    vm.expect_exact('\r\nINSTALL_AUTH: ')
    vm.logfile_read = None; vm.sendline(user_password)
    vm.expect(r'\r+\n0\r+\n'); vm.expect_exact('DEVOS-TEST# ')
    vm.logfile_read = log
    report['checks'].append('installed user sudo authentication')
    command('sudo mountpoint -q /boot/efi', prompt='DEVOS-TEST# ')
    command('sudo mountpoint -q /boot', prompt='DEVOS-TEST# ')
    command('sudo mountpoint -q /home', prompt='DEVOS-TEST# ')
    command("grep -q 'devos.slot=A' /proc/cmdline", prompt='DEVOS-TEST# ')
    command('sudo dev install /opt/hello-0.1.0.dpk', expected=1, prompt='DEVOS-TEST# ')
    fixture_device = '/dev/vdb' if args.disk_type == 'virtio' else '/dev/vda'
    command('sudo mkdir -p /mnt/qa && sudo mount -o ro ' + fixture_device + ' /mnt/qa', prompt='DEVOS-TEST# ')
    command('sudo python3 /mnt/qa/probe.py', prompt='DEVOS-TEST# ')
    command('sudo python3 /mnt/qa/slots_probe.py', prompt='DEVOS-TEST# ')
    command("test \"$(qa-app)\" = '2'", prompt='DEVOS-TEST# ')
    command('echo shared-home-persistence > ~/qa-persistence', prompt='DEVOS-TEST# ')
    vm.sendline('su -'); secret('Password:', root_password)
    vm.expect_exact('root@dev-os-test:~# '); vm.logfile_read = log
    report['checks'].append('installed root prompt: root@dev-os-test:~#')
    vm.sendline("export PS1='DEVOS-TEST# '"); vm.expect_exact('\r\nDEVOS-TEST# ')
    command('test "$(id -u)" = 0', prompt='DEVOS-TEST# ')
    report['checks'].append('installed root su authentication')
    command('sync', prompt='DEVOS-TEST# ')
    close()
    launch(False)
    login()
    command('dev list | grep -q qa-app', prompt='DEVOS-TEST# ')
    command("test \"$(qa-app)\" = '2'", prompt='DEVOS-TEST# ')
    command('grep -q shared-home-persistence ~/qa-persistence', prompt='DEVOS-TEST# ')
    report['checks'].append('signed package and shared /home persist through reboot without installer media')
    report['passed'] = True
except Exception as exc:
    # pexpect exceptions can include authentication buffers; never print those.
    report['error'] = {'type': type(exc).__name__}
finally:
    close()
    fixture_temp.cleanup()
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))

raise SystemExit(0 if report['passed'] else 1)
