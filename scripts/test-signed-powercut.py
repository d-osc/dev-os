#!/usr/bin/env python3
"""SIGKILL disposable QEMU guests during signed batches; verify normal-boot recovery."""
import argparse
import hashlib
import json
from pathlib import Path
import signal
import subprocess
import tempfile
import time

import pexpect
from candidate_signed_fixture import create

PROJECT = Path(__file__).resolve().parents[1]
DRIVER = r'''
import argparse, functools, hashlib, http.server, importlib.machinery, importlib.util
import errno, json, os, pathlib, subprocess, sys, tarfile, tempfile, threading, time
sys.path.insert(0, '/usr/lib/devos')
loader = importlib.machinery.SourceFileLoader('dev', '/usr/bin/dev')
spec = importlib.util.spec_from_loader('dev', loader)
dev = importlib.util.module_from_spec(spec)
sys.modules['dev'] = dev
loader.exec_module(dev)
operation, point = sys.argv[1:]
root = pathlib.Path('/')
with tempfile.TemporaryDirectory(prefix='signed-powercut-') as temporary:
    base = pathlib.Path(temporary)
    with tarfile.open('/opt/repository.tar') as archive:
        archive.extractall(base, filter='data')
    public = base / 'repository'
    generations = json.loads((public / 'fixture.json').read_text())
    serving = [public / 'generations' / str(generations['1'])]
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(serving[0]), **kwargs)
        def log_message(self, *args): pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    anchor = public / 'bootstrap-root.json'
    url = 'http://127.0.0.1:' + str(server.server_port)
    subprocess.run(['dev', 'trust', str(anchor), '--sha256', hashlib.sha256(anchor.read_bytes()).hexdigest(),
        '--metadata-url', url + '/metadata', '--targets-url', url + '/targets', '--allow-loopback-http'], check=True)
    if operation != 'install':
        subprocess.run(['dev', 'install', 'qa-app'], check=True)
        serving[0] = public / 'generations' / str(generations['2'])
    if operation == 'rollback':
        subprocess.run(['dev', 'upgrade', 'qa-lib'], check=True)
    def checkpoint(label):
        if label == point:
            if operation == 'disk-full':
                # Exhaust the real guest root ext4 after the first replacement.
                # This is a disposable image; never touch a host filesystem.
                with open('/var/lib/dev/disk-full-fixture', 'wb', buffering=0) as fill:
                    try:
                        while True: fill.write(b'X' * (1024 * 1024))
                    except OSError as exc:
                        assert exc.errno == errno.ENOSPC
                return
            print('SIGNED_CUT_READY', flush=True)
            while True: time.sleep(1)
    dev.transaction_checkpoint = checkpoint
    if operation == 'disk-full':
        try:
            dev.repository_module().dispatch(root, argparse.Namespace(command='upgrade', name='qa-lib'), dev)
        except OSError as exc:
            assert exc.errno == errno.ENOSPC, str(exc)
        else:
            raise AssertionError('Disk-full upgrade unexpectedly succeeded')
        journal = root / 'var/lib/dev/transaction/journal.json'
        assert journal.exists(), 'Expected recoverable pending transaction'
        record = json.loads(journal.read_text())
        assert json.loads((root / 'var/lib/dev/installed.json').read_text()) == record['before']
        old_files, _ = dev.batch_files(record['before'], record['after'])
        for name, metadata in old_files.items():
            assert dev.matches_file(root / 'var/lib/dev/transaction/old' / name, metadata)
        # Reclaim space without invoking recovery; normal init must restore it.
        (root / 'var/lib/dev/disk-full-fixture').unlink()
        os.sync()
        print('SIGNED_CUT_READY', flush=True)
        while True: time.sleep(1)
    elif operation == 'rollback':
        dev.rollback(root, ['qa-app', 'qa-lib'])
    else:
        args = argparse.Namespace(command=operation, name='qa-lib', package='qa-app')
        dev.repository_module().dispatch(root, args, dev)
    raise AssertionError('Requested checkpoint was never reached')
'''
VERIFY = r'''
import json, pathlib, subprocess, sys
root = pathlib.Path('/')
# Check before invoking a dev command: recovery must have happened during init.
assert not (root / 'var/lib/dev/transaction').exists(), 'Boot recovery left a pending journal'
path = root / 'var/lib/dev/installed.json'
database = json.loads(path.read_text()) if path.exists() else {}
version = sys.argv[1]
if version == 'absent':
    assert not database
    assert not (root / 'usr/bin/qa-app').exists()
    assert not (root / 'usr/share/qa-lib/version').exists()
else:
    assert set(database) == {'qa-app', 'qa-lib'}
    for manifest in database.values():
        assert manifest['version'] == version
        assert manifest['installed_trust']['type'] == 'tuf'
    assert subprocess.check_output(['/usr/bin/qa-app'], text=True) == version
subprocess.run(['dev', 'verify'], check=True)
print('BOOT_RECOVERY_VERIFIED', flush=True)
'''


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images', type=Path, required=True)
    parser.add_argument('--credentials', type=Path, required=True)
    parser.add_argument('--disk-full', action='store_true', help='Run the real ext4 exhaustion/recovery case instead')
    parser.add_argument('--output', type=Path, default=PROJECT / 'out/test-results/signed-powercut.json')
    args = parser.parse_args()
    report = {'passed': False, 'image_sha256': digest(args.images / 'rootfs.ext4'),
              'kernel_sha256': digest(args.images / 'bzImage'), 'cases': [],
              'method': 'Signed batches; SIGKILL QEMU; same disk, normal init boot; offline journal recovery'}
    accounts = json.loads(args.credentials.read_text())
    vm = None
    stage = 'prepare'
    try:
        with tempfile.TemporaryDirectory(prefix='devos-signed-powercut-') as directory:
            temporary = Path(directory)
            fixture = create(temporary, PROJECT)
            driver = temporary / 'driver.py'; driver.write_text(DRIVER)
            verifier = temporary / 'verify.py'; verifier.write_text(VERIFY)

            def boot(disk):
                guest = pexpect.spawn('qemu-system-x86_64', [
                    '-accel', 'kvm', '-machine', 'pc', '-m', '512', '-smp', '2',
                    '-nographic', '-no-reboot', '-kernel', str(args.images / 'bzImage'),
                    '-drive', f'file={disk},format=raw,if=virtio,cache=writethrough',
                    '-append', 'root=/dev/vda rw console=ttyS0', '-nic', 'none'],
                    encoding='utf-8', timeout=90, dimensions=(30, 160))
                try:
                    guest.expect_exact('dev-os login:'); guest.sendline('dev')
                    guest.expect_exact('Password:'); guest.sendline(accounts['dev'])
                    guest.expect_exact('dev@dev-os:~$ ')
                    guest.sendline('su -'); guest.expect_exact('Password:'); guest.sendline(accounts['root'])
                    guest.expect_exact('root@dev-os:~# ')
                    return guest
                except Exception:
                    guest.close(force=True)
                    raise

            cases = [('install', point) for point in ('journal', 'publish:qa-app', 'file:1', 'commit')]
            cases += [(operation, point) for operation in ('upgrade', 'rollback')
                      for point in ('replace-copy:qa-app', 'replace-publish:qa-app', 'file:1', 'commit')]
            if args.disk_full:
                cases = [('disk-full', 'file:0')]
                report['method'] = 'Fill guest ext4 after first replacement; verify ENOSPC and durable backups; reclaim space; SIGKILL and normal boot recovery'
            for index, (operation, point) in enumerate(cases):
                stage = operation + ':' + point
                started = time.monotonic()
                disk = temporary / ('case-' + str(index) + '.ext4')
                subprocess.run(['cp', '--reflink=auto', str(args.images / 'rootfs.ext4'), str(disk)], check=True)
                for source, name in ((fixture, 'repository.tar'), (driver, 'cut-driver.py'), (verifier, 'verify-cut.py')):
                    subprocess.run(['debugfs', '-w', '-R', f'write {source} /opt/{name}', str(disk)],
                                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                vm = boot(disk)
                vm.sendline('python3 /opt/cut-driver.py ' + operation + ' ' + point)
                vm.expect(r'\r+\nSIGNED_CUT_READY\r+\n')
                vm.kill(signal.SIGKILL); vm.expect(pexpect.EOF); vm.close(); vm = None
                committed = point == 'commit'
                expected = ('1' if committed else 'absent') if operation == 'install' else (
                    ('2' if committed else '1') if operation == 'upgrade' else ('1' if committed else '2'))
                if operation == 'disk-full':
                    expected = '1'
                vm = boot(disk)
                vm.sendline('python3 /opt/verify-cut.py ' + expected)
                vm.expect(r'\r+\nBOOT_RECOVERY_VERIFIED\r+\n')
                vm.close(force=True); vm = None
                disk.unlink()
                report['cases'].append({'operation': operation, 'point': point, 'expected': expected,
                                        'passed': True, 'seconds': round(time.monotonic() - started, 2)})
                print('PASS ' + stage, flush=True)
            report['passed'] = True
    except Exception as exc:
        # Do not leak authentication buffers in failures.
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
