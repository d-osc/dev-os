#!/usr/bin/env python3
"""Normal-boot smoke test of actual candidate code in a disposable QEMU disk."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import pexpect

PROJECT = Path(__file__).resolve().parents[1]
CHECK = '''import hashlib, importlib.metadata, importlib.machinery, importlib.util, json, pathlib, subprocess, sys
sys.path.insert(0, '/usr/lib/devos')
loader = importlib.machinery.SourceFileLoader('dev', '/usr/bin/dev')
spec = importlib.util.spec_from_loader('dev', loader)
dev = importlib.util.module_from_spec(spec)
loader.exec_module(dev)
import dev_compat, dev_repository
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
key = Ed25519PrivateKey.generate()
key.public_key().verify(key.sign(b'candidate'), b'candidate')
versions = {name: importlib.metadata.version(name) for name in
            ('tuf', 'securesystemslib', 'cryptography', 'packaging', 'pyelftools')}
root = pathlib.Path('/')
platform = json.loads(pathlib.Path('/usr/lib/devos/platform.json').read_text())
assert platform['arch'] == 'x86_64'
assert platform['runtimes']['python'] == '.'.join(map(str, sys.version_info[:3]))
node = subprocess.check_output(['node', '--version'], text=True).strip().lstrip('v')
assert platform['runtimes']['node'] == node
policy = json.loads(pathlib.Path('/etc/devos/package-policy.json').read_text())
assert policy['require_signed'] and not policy['allow_unsigned_override']
rejected = subprocess.run(['dev', 'install', '/opt/hello-0.1.0.dpk'], capture_output=True, text=True)
assert rejected.returncode != 0, 'Unsigned package installed under production policy'
assert not pathlib.Path('/usr/bin/dev-hello').exists()
subprocess.run(['dev', 'recover'], check=True)
subprocess.run(['dev', 'verify'], check=True)
python = pathlib.Path(sys.executable).resolve().relative_to(root).as_posix()
dev_compat.check_install(root, {'name': 'candidate-elf-check', 'version': '1', 'arch': 'x86_64',
                              'files': {python: {'mode': 0o755}}}, root, {}, dev, strict=True)
print('CANDIDATE_RESULT=' + json.dumps({'versions': versions, 'platform': platform,
 'manager_sha256': hashlib.sha256(pathlib.Path('/usr/bin/dev').read_bytes()).hexdigest(),
 'checks': ['normal boot and login', 'Ed25519 sign/verify', 'repository imports',
            'runtime versions match metadata', 'unsigned install rejected',
            'recover', 'verify', 'target Python ELF dependency and ABI validation']}), flush=True)
'''


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images', type=Path, required=True)
    parser.add_argument('--credentials', type=Path, required=True)
    parser.add_argument('--signed', action='store_true', help='Exercise signed package operations with an ephemeral repository')
    parser.add_argument('--output', type=Path, default=PROJECT / 'out/test-results/candidate.json')
    args = parser.parse_args()
    report = {'passed': False, 'image_sha256': sha256(args.images / 'rootfs.ext4'),
              'kernel_sha256': sha256(args.images / 'bzImage'),
              'method': 'Normal BusyBox init boot, disposable disk; QA probe only injected'}
    vm = None
    stage = 'prepare'
    try:
        accounts = json.loads(args.credentials.read_text())
        with tempfile.TemporaryDirectory(prefix='devos-candidate-') as directory:
            temporary = Path(directory)
            disk = temporary / 'rootfs.ext4'
            shutil.copyfile(args.images / 'rootfs.ext4', disk)
            probe = temporary / 'candidate-check.py'
            code = CHECK
            if args.signed:
                from candidate_signed_fixture import create, GUEST
                fixture = create(temporary, PROJECT)
                subprocess.run(['debugfs', '-w', '-R', f'write {fixture} /opt/repository.tar', str(disk)],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                code += GUEST
            probe.write_text(code)
            subprocess.run(['debugfs', '-w', '-R', f'write {probe} /opt/candidate-check.py', str(disk)],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            vm = pexpect.spawn('qemu-system-x86_64', [
                '-accel', 'kvm', '-machine', 'pc', '-m', '512', '-smp', '2',
                '-nographic', '-no-reboot', '-kernel', str(args.images / 'bzImage'),
                '-drive', f'file={disk},format=raw,if=virtio',
                '-append', 'root=/dev/vda rw console=ttyS0', '-nic', 'none'],
                encoding='utf-8', timeout=90, dimensions=(30, 160))
            stage = 'normal boot and authentication'
            vm.expect_exact('dev-os login:'); vm.sendline('dev')
            vm.expect_exact('Password:'); vm.sendline(accounts['dev'])
            vm.expect_exact('dev@dev-os:~$ ')
            vm.sendline('su -'); vm.expect_exact('Password:'); vm.sendline(accounts['root'])
            vm.expect_exact('root@dev-os:~# ')
            stage = 'candidate runtime checks'
            vm.sendline("python3 /opt/candidate-check.py; printf '\\nPROBE_RC=%s\\n' \"$?\"")
            vm.expect(r'\r+\nPROBE_RC=(\d+)\r+\n')
            result = vm.before
            # This buffer starts after authentication; never save login buffers.
            report['probe_output'] = result
            if int(vm.match.group(1)):
                raise AssertionError('Candidate probe failed')
            line = next(line for line in result.splitlines() if line.startswith('CANDIDATE_RESULT='))
            report.update(json.loads(line.split('=', 1)[1]))
            if args.signed:
                line = next(line for line in result.splitlines() if line.startswith('SIGNED_RESULT='))
                report['signed_operations'] = json.loads(line.split('=', 1)[1])
            report['passed'] = True
    except Exception as exc:
        report['failure'] = {'stage': stage, 'type': type(exc).__name__}
    finally:
        if vm is not None:
            vm.close(force=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
