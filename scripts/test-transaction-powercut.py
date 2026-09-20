#!/usr/bin/env python3
"""Abruptly kill disposable QEMU guests and recover their ext4 package state.

Never uses a physical disk, a user's running VM, or modifies the input image.
This simulates loss of the guest, not power loss of a physical storage controller.
"""
import argparse
import hashlib
import json
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

import pexpect

PROJECT = Path(__file__).resolve().parents[1]
DRIVER = '''import importlib.util, sys, time
sys.path.insert(0, '/opt/packaging.zip')
spec = importlib.util.spec_from_file_location('dev', '/opt/dev-test.py')
dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev)
def cut(label):
    if label == sys.argv[2]:
        print('POWER_CUT_READY', flush=True)
        while True:
            time.sleep(1)
dev.transaction_checkpoint = cut
from pathlib import Path
if sys.argv[1] == 'install':
    dev.install(Path('/'), '/opt/transaction-test.dpk')
elif sys.argv[1] == 'remove':
    dev.remove(Path('/'), 'hello')
elif sys.argv[1] == 'upgrade':
    with dev.database(Path('/')) as (db, path):
        dev.install_locked(Path('/'), '/opt/upgrade-test.dpk', db, path, replacement='upgrade')
elif sys.argv[1] == 'rollback':
    dev.rollback(Path('/'), 'hello')
else:
    with dev.database(Path('/')):
        pass
'''


def run(images, output):
    source_bytes = (PROJECT / 'tools/dev.py').read_bytes()
    report = {'passed': False, 'source_sha256': hashlib.sha256(source_bytes).hexdigest(),
        'method': 'SIGKILL QEMU with writable disposable raw ext4; reboot same disk',
        'policy': 'Explicit unsigned development fixture; signature pipeline tested separately',
        'base_image': str(images / 'rootfs.ext4'), 'cases': []}
    vm = None
    try:
        with tempfile.TemporaryDirectory(prefix='devos-powercut-') as directory:
            temporary = Path(directory)
            driver = temporary / 'crash.py'
            driver.write_text(DRIVER)
            core = temporary / 'dev-test.py'
            core.write_bytes(source_bytes)
            package = temporary / 'hello.dpk'
            subprocess.run([sys.executable, str(core), 'build',
                            str(PROJECT / 'examples/hello'), str(package)], check=True,
                           stdout=subprocess.DEVNULL)
            old_version = json.loads((PROJECT / 'examples/hello/manifest.json').read_text())['version']
            upgrade_source = temporary / 'upgrade-source'
            shutil.copytree(PROJECT / 'examples/hello', upgrade_source)
            manifest_path = upgrade_source / 'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['version'] = '0.2.0'
            manifest_path.write_text(json.dumps(manifest))
            (upgrade_source / 'payload/usr/bin/dev-hello').write_text('#!/bin/sh\necho upgraded\n')
            upgrade_package = temporary / 'upgrade.dpk'
            subprocess.run([sys.executable, str(core), 'build', str(upgrade_source), str(upgrade_package)],
                           check=True, stdout=subprocess.DEVNULL)
            import packaging
            library = temporary / 'packaging.zip'
            library_root = Path(packaging.__file__).parent
            with zipfile.ZipFile(library, 'w', zipfile.ZIP_DEFLATED) as zipped:
                for path in library_root.rglob('*.py'):
                    zipped.write(path, 'packaging/' + path.relative_to(library_root).as_posix())
            report['packaging_version'] = packaging.__version__
            policy = temporary / 'package-policy.json'
            policy.write_text(json.dumps({'version': 1, 'require_signed': False, 'allow_unsigned_override': False}))

            def boot(disk):
                guest = pexpect.spawn('qemu-system-x86_64', [
                    '-accel', 'kvm', '-machine', 'pc', '-m', '256', '-smp', '2',
                    '-nographic', '-no-reboot', '-kernel', str(images / 'bzImage'),
                    '-drive', f'file={disk},format=raw,if=virtio,cache=writethrough',
                    '-append', 'root=/dev/vda rw console=ttyS0 init=/bin/sh',
                    '-nic', 'none'], encoding='utf-8', timeout=45)
                guest.expect(r'# ')
                guest.sendline("export PS1='TXN_TEST> '")
                guest.expect_exact('\r\nTXN_TEST> ')
                return guest

            def command(text):
                vm.sendline(text + "; printf '\\nTEST_RC=%s\\n' \"$?\"")
                vm.expect(r'\r+\nTEST_RC=(\d+)\r+\n')
                status = int(vm.match.group(1))
                result = vm.before
                vm.expect_exact('TXN_TEST> ')
                if status:
                    raise AssertionError(f'{text}: {status}: {result}')

            def powercut():
                nonlocal vm
                vm.kill(signal.SIGKILL)
                vm.expect(pexpect.EOF)
                vm.close()
                vm = None

            cases = [('install', 'journal'), ('install', 'publish:dev-hello'),
                     ('install', 'file:0'), ('install', 'commit'),
                     ('remove', 'file:0'), ('remove', 'commit'),
                     ('remove', 'recover:0')]
            cases += [(operation, point) for operation in ('upgrade', 'rollback')
                      for point in ('replace-copy:dev-hello', 'replace-publish:dev-hello', 'file:0', 'commit', 'recover:0')]
            for index, (operation, point) in enumerate(cases):
                started = time.monotonic()
                disk = temporary / f'case-{index}.ext4'
                subprocess.run(['cp', '--reflink=auto', str(images / 'rootfs.ext4'), str(disk)], check=True)
                for operation_text in ('mkdir /etc/devos', 'rm /etc/devos/package-policy.json'):
                    subprocess.run(['debugfs', '-w', '-R', operation_text, str(disk)], check=True,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                for source, destination in [(core, '/opt/dev-test.py'),
                                            (driver, '/opt/crash.py'), (package, '/opt/transaction-test.dpk'),
                                            (upgrade_package, '/opt/upgrade-test.dpk'), (library, '/opt/packaging.zip'),
                                            (policy, '/etc/devos/package-policy.json')]:
                    subprocess.run(['debugfs', '-w', '-R', f'write {source} {destination}', str(disk)],
                                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                vm = boot(disk)
                if operation in ('remove', 'upgrade', 'rollback'):
                    command('python3 /opt/dev-test.py install /opt/transaction-test.dpk')
                if operation == 'rollback':
                    command('python3 /opt/crash.py upgrade never')
                first_point = 'file:0' if point == 'recover:0' else point
                vm.sendline(f'python3 /opt/crash.py {operation} {first_point}')
                vm.expect(r'\r+\nPOWER_CUT_READY\r+\n')
                powercut()
                vm = boot(disk)
                if point == 'recover:0':
                    vm.sendline('python3 /opt/crash.py recover recover:0')
                    vm.expect(r'\r+\nPOWER_CUT_READY\r+\n')
                    powercut()
                    vm = boot(disk)
                command('python3 /opt/dev-test.py recover')
                command('python3 /opt/dev-test.py verify')
                installed = operation in ('upgrade', 'rollback') or (operation == 'install') == (point == 'commit')
                command('test ' + ('-f' if installed else '! -e') + ' /usr/bin/dev-hello')
                command('test ! -e /var/lib/dev/transaction')
                command("test -z \"$(find /usr /opt -name '.dev-*')\"")
                # Verify the database agrees with the filesystem, not just that it parses.
                expression = "'hello' in json.load(open('/var/lib/dev/installed.json'))" if installed else \
                    "not os.path.exists('/var/lib/dev/installed.json') or 'hello' not in json.load(open('/var/lib/dev/installed.json'))"
                command('python3 -c "import json,os; assert ' + expression + '"')
                if installed:
                    expected = old_version
                    if (operation == 'upgrade' and point == 'commit') or (operation == 'rollback' and point != 'commit'):
                        expected = '0.2.0'
                    command('python3 -c "import json; assert json.load(open(\'/var/lib/dev/installed.json\'))[\'hello\'][\'version\'] == \'' + expected + '\'"')
                powercut()
                report['cases'].append({'operation': operation, 'checkpoint': point, 'passed': True,
                                        'seconds': round(time.monotonic() - started, 2)})
                print(f'PASS {operation} {point}', flush=True)
                disk.unlink()
            report['passed'] = True
    except Exception as exc:
        report['error'] = str(exc)
    finally:
        if vm is not None:
            vm.kill(signal.SIGKILL)
            vm.close(force=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + '\n')
    return report['passed']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=PROJECT / 'out/test-results/transaction-powercut.json')
    args = parser.parse_args()
    raise SystemExit(0 if run(args.images.resolve(), args.output.resolve()) else 1)
