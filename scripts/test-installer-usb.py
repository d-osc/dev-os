#!/usr/bin/env python3
"""Boot a raw-written ISO as a virtual USB stick and check source-media protection."""
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import time

import pexpect

project = Path(__file__).resolve().parents[1]
out = project / 'out/installer-tests/usb'
out.mkdir(parents=True, exist_ok=True)
usb = out / 'installer-usb.raw'
with usb.open('xb') as dest, (project / 'out/installer/dev-os-0.1-installer.iso').open('rb') as src:
    shutil.copyfileobj(src, dest, 1024 * 1024)
    dest.truncate(16 * 1024**3)
firmware = out / 'OVMF_VARS.fd'
shutil.copyfile('/usr/share/OVMF/OVMF_VARS_4M.fd', firmware)
monitor = out / 'qmp.sock'
vm = pexpect.spawn('qemu-system-x86_64', [
    '-accel', 'kvm', '-machine', 'q35', '-m', '2048', '-smp', '2',
    '-display', 'none', '-serial', 'stdio', '-monitor', 'none',
    '-qmp', f'unix:{monitor},server=on,wait=off',
    '-drive', 'if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd',
    '-drive', f'if=pflash,format=raw,file={firmware}',
    '-drive', f'if=none,id=installer,format=raw,file={usb}',
    '-device', 'qemu-xhci,id=usb', '-device', 'usb-storage,drive=installer,bootindex=1',
    '-netdev', 'user,id=net0', '-device', 'virtio-net-pci,netdev=net0'],
    encoding='utf-8', timeout=120)
report = {'passed': False, 'checks': []}
with (project / 'out/installer/dev-os-0.1-installer.iso').open('rb') as stream:
    report['iso_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
with (out / 'usb.log').open('w') as log:
    vm.logfile_read = log
    try:
        vm.expect('Dev OS setup'); vm.send('1')
        vm.expect_exact('DEVOS-LIVE# ')
        report['checks'].append('UEFI boot from a raw-written, writable virtual USB stick')
        # The framebuffer can finish rendering after the serial shell is ready.
        time.sleep(1)
        with socket.socket(socket.AF_UNIX) as client:
            client.connect(str(monitor))
            stream = client.makefile('rwb', buffering=0)
            json.loads(stream.readline())
            for request in ({'execute': 'qmp_capabilities'},
                            {'execute': 'screendump', 'arguments': {
                                'filename': str(out / 'setup-screen.png'), 'format': 'png'}}):
                stream.write(json.dumps(request).encode() + b'\n')
                while True:
                    response = json.loads(stream.readline())
                    if 'error' in response:
                        raise RuntimeError(str(response))
                    if 'return' in response:
                        break
        vm.sendline('dev install-system')
        vm.expect_exact('Target disk (full path, or Enter to cancel): ')
        if 'installer/optical media' not in vm.before:
            raise AssertionError('Writable 16 GiB installer USB was not identified as source media')
        vm.sendline('/dev/sda')
        vm.expect_exact('Target is not an available whole disk')
        vm.expect_exact('DEVOS-LIVE# ')
        report['checks'].append('installer refuses to select its own writable USB source as target')
        report['passed'] = True
    except Exception as exc:
        report['error'] = str(exc)
        raise
    finally:
        vm.terminate(force=True)
        (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2))
