#!/usr/bin/env python3
"""Boot an isolated QEMU snapshot and verify real guest login/package privileges."""
import argparse
import json
from pathlib import Path
import re
import shlex
import time

import pexpect

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--memory', type=int, default=512)
parser.add_argument('--accel', choices=['kvm', 'tcg'], default='kvm')
args = parser.parse_args()
project = Path(__file__).resolve().parents[1]
images = project / 'out/buildroot/images'
accounts = json.loads((project / 'out/vm-credentials.json').read_text())
report_dir = project / 'out/test-results'
report_dir.mkdir(parents=True, exist_ok=True)
log = (report_dir / f'vm-{args.memory}.log').open('w')
cmd = ['-accel', args.accel, '-machine', 'pc', '-m', str(args.memory),
       '-smp', '2', '-nographic', '-snapshot', '-no-reboot',
       '-kernel', str(images / 'bzImage'),
       '-drive', f'file={images / "rootfs.ext4"},format=raw,if=virtio',
       '-append', 'root=/dev/vda rw console=ttyS0',
       '-netdev', 'user,id=net0', '-device', 'virtio-net-pci,netdev=net0']
start = time.monotonic()
vm = pexpect.spawn('qemu-system-x86_64', cmd, encoding='utf-8', timeout=120,
                   dimensions=(30, 160))
vm.logfile_read = log
report = {'memory_mib': args.memory, 'acceleration': args.accel, 'vcpus': 2,
          'checks': [], 'passed': False}
prompt = 'DEVOS_PROMPT> '


def command(command_text, expected_status=0):
    vm.sendline(command_text + "; printf '\\nDEVOS_STATUS=%s\\n' \"$?\"")
    vm.expect(r'\r+\nDEVOS_STATUS=(\d+)\r+\n')
    output = vm.before
    status = int(vm.match.group(1))
    vm.expect_exact(prompt)
    if status != expected_status:
        raise AssertionError(f'{command_text}: status {status}, expected {expected_status}: {output}')
    report['checks'].append(command_text)
    return output


def password(value):
    # Only output is logged, never sent credentials. Disable read logging too
    # until the guest has completed authentication.
    vm.logfile_read = None
    vm.sendline(value)
    vm.expect(r'[$#] ')
    vm.logfile_read = log
    vm.sendline("export PS1='" + prompt + "'")
    vm.expect_exact('\r\n' + prompt)


try:
    vm.expect('dev-os login:')
    report['boot_to_login_seconds'] = round(time.monotonic() - start, 3)
    vm.sendline('dev')
    vm.expect('Password:')
    password(accounts['dev'])
    command('test "$(id -u)" = 1000')
    output = command('cat /proc/meminfo; cat /proc/uptime')
    report['idle_meminfo_kib'] = {k: int(v) for k, v in
                                  re.findall(r'^(MemTotal|MemFree|MemAvailable|Cached|Buffers):\s+(\d+) kB', output, re.MULTILINE)}
    command('grep -q "Dev OS" /etc/os-release')
    output = command('uname -r; python3 --version')
    report['kernel'] = re.search(r'\r+\n(\d+\.\d+\.[^\r\n]+)\r+\n', output).group(1)
    report['python'] = re.search(r'Python ([0-9.]+)', output).group(1)
    command('dev install /opt/hello-0.1.0.dpk', expected_status=1)
    vm.sendline("sudo -k; sudo -p 'DEVOS_AUTH: ' id -u")
    vm.expect_exact('\r\nDEVOS_AUTH: ')
    vm.logfile_read = None
    vm.sendline(accounts['dev'])
    vm.expect(r'\r+\n0\r+\n')
    vm.expect_exact(prompt)
    vm.logfile_read = log
    report['checks'].append('sudo password authentication -> uid 0')
    command('sudo dev install /opt/hello-0.1.0.dpk')
    command("test \"$(dev-hello)\" = 'Hello from Dev OS!'")
    command("dev list | grep -q '^hello 0.1.0$'")
    command('sudo dev remove hello')
    command('test ! -e /usr/bin/dev-hello')
    vm.sendline('su -')
    vm.expect('Password:')
    password(accounts['root'])
    command('test "$(id -u)" = 0')
    report['checks'].append('su password authentication -> uid 0')
    command('test -x /usr/bin/sudo; test -x /bin/su')
    command('ip -4 addr show eth0 | grep -q "inet "')
    command('python3 /usr/lib/devos/memory-probe.py 12 > /tmp/devos-memory-probe.log & probe_pid=$!')
    command('for i in 1 2 3 4 5 6 7 8 9 10; do grep -q READY /tmp/devos-memory-probe.log && break; sleep 1; done; grep -q READY /tmp/devos-memory-probe.log')
    roundtrips = []
    for _ in range(5):
        before = time.monotonic()
        command('true')
        roundtrips.append(round((time.monotonic() - before) * 1000, 2))
    report['shell_roundtrip_ms_during_allocation'] = roundtrips
    report['roundtrip_note'] = 'Includes pexpect send delay and host scheduling; not an OS latency benchmark.'
    command('wait "$probe_pid"')
    output = command('cat /tmp/devos-memory-probe.log')
    report['probe_allocated_bytes'] = int(re.search(r'allocated_bytes=(\d+)', output).group(1))
    command('grep -q DONE /tmp/devos-memory-probe.log')
    command('dmesg | grep -i "out of memory\\|killed process"', expected_status=1)
    report['passed'] = True
except Exception as exc:
    report['error'] = str(exc)
    raise
finally:
    vm.terminate(force=True)
    log.close()
    (report_dir / f'vm-{args.memory}.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
