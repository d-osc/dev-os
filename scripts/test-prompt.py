#!/usr/bin/env python3
"""Test the login prompt in a disposable Dev OS disk copy (Linux/QEMU)."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import pexpect

project = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--images', type=Path, default=project / 'out/images')
parser.add_argument('--credentials', type=Path, default=project / 'out/vm-credentials.json')
parser.add_argument('--prepared', action='store_true', help='verify the profile already exists in the supplied image')
args = parser.parse_args()
accounts = json.loads(args.credentials.read_text())
report_path = project / 'out/test-results/prompt.json'
report_path.parent.mkdir(parents=True, exist_ok=True)
report = {'passed': False, 'checks': [], 'image': 'prepared release image' if args.prepared else 'disposable copy with current prompt profile'}
vm = None
stage = 'prepare disk'
try:
    with tempfile.TemporaryDirectory(prefix='devos-prompt-') as temporary:
        temporary = Path(temporary)
        disk = temporary / 'rootfs.ext4'
        shutil.copyfile(args.images / 'rootfs.ext4', disk)
        profile = temporary / 'devos-prompt.sh'
        profile.write_text((project / 'rootfs-overlay/etc/profile.d/devos-prompt.sh').read_text(), newline='\n')
        # Only this disposable disk is modified; base images and ISO stay untouched.
        if not args.prepared:
            for command in ('mkdir /etc/profile.d', 'rm /etc/profile.d/devos-prompt.sh',
                            f'write {profile} /etc/profile.d/devos-prompt.sh'):
                subprocess.run(['debugfs', '-w', '-R', command, str(disk)], check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        stored = subprocess.check_output(['debugfs', '-R', 'cat /etc/profile.d/devos-prompt.sh', str(disk)],
                                         stderr=subprocess.DEVNULL)
        assert stored == profile.read_bytes()
        vm = pexpect.spawn('qemu-system-x86_64', [
            '-accel', 'kvm', '-machine', 'pc', '-m', '512', '-smp', '2',
            '-nographic', '-snapshot', '-no-reboot', '-kernel', str(args.images / 'bzImage'),
            '-drive', f'file={disk},format=raw,if=virtio',
            '-append', 'root=/dev/vda rw console=ttyS0', '-nic', 'none'],
            encoding='utf-8', timeout=90, dimensions=(30, 160))

        def expect_prompt(prompt, label):
            vm.expect_exact(prompt)
            report['checks'].append(label)
            print('PASS: ' + label, flush=True)

        stage = 'dev login'
        vm.expect_exact('dev-os login:'); vm.sendline('dev')
        vm.expect_exact('Password:'); vm.sendline(accounts['dev'])
        expect_prompt('dev@dev-os:~$ ', 'login: dev@dev-os:~$')
        vm.timeout = 15
        stage = 'directory updates'
        vm.sendline('cd /tmp')
        expect_prompt('dev@dev-os:/tmp$ ', 'cd /tmp updates prompt')
        vm.sendline('cd; mkdir -p prompt-check; cd prompt-check')
        expect_prompt('dev@dev-os:~/prompt-check$ ', 'home subdirectory uses ~/')
        vm.sendline('cd')
        expect_prompt('dev@dev-os:~$ ', 'cd returns to ~')
        stage = 'su root'
        vm.sendline('su'); vm.expect_exact('Password:'); vm.sendline(accounts['root'])
        expect_prompt('root@dev-os:/home/dev# ', 'su: root identity and # without changing directory')
        vm.sendline('exit')
        expect_prompt('dev@dev-os:~$ ', 'exit su restores dev prompt')
        stage = 'su login root'
        vm.sendline('su -'); vm.expect_exact('Password:'); vm.sendline(accounts['root'])
        expect_prompt('root@dev-os:~# ', 'su -: root home and #')
        vm.sendline('exit')
        expect_prompt('dev@dev-os:~$ ', 'exit su - restores dev prompt')
        stage = 'sudo login root'
        vm.sendline("sudo -k; sudo -p 'PROMPT_AUTH: ' -i")
        vm.expect_exact('\r\nPROMPT_AUTH: '); vm.sendline(accounts['dev'])
        expect_prompt('root@dev-os:~# ', 'sudo -i: root home and #')
        vm.sendline('exit')
        expect_prompt('dev@dev-os:~$ ', 'exit sudo restores dev prompt')
        stage = 'non-interactive shell'
        vm.sendline("sh -c '. /etc/profile.d/devos-prompt.sh; echo NONINTERACTIVE_OK'")
        vm.expect(r'\r+\nNONINTERACTIVE_OK\r+\n')
        expect_prompt('dev@dev-os:~$ ', 'non-interactive profile produces no output')
        stage = 'fresh login persistence'
        vm.sendline('exit'); vm.expect_exact('dev-os login:'); vm.sendline('dev')
        vm.expect_exact('Password:'); vm.sendline(accounts['dev'])
        expect_prompt('dev@dev-os:~$ ', 'fresh login automatically loads prompt')
        report['passed'] = True
        vm.close(force=True); vm = None
except Exception as exc:
    # Never include authentication buffers or credentials in the report.
    report['failure'] = {'stage': stage, 'type': type(exc).__name__}
finally:
    if vm is not None:
        vm.close(force=True)
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
raise SystemExit(0 if report['passed'] else 1)
