"""Verify the exported image reaches login with Windows QEMU software emulation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time

if os.name != 'nt':
    raise SystemExit('Run this test on Windows after exporting images')
project = Path(__file__).resolve().parents[1]
images = project / 'out/images'
reports = project / 'out/test-results'
reports.mkdir(parents=True, exist_ok=True)
qemu = shutil.which('qemu-system-x86_64.exe')
if not qemu:
    raise SystemExit('qemu-system-x86_64.exe is not in PATH')
started = time.monotonic()
proc = subprocess.Popen([
    qemu, '-accel', 'tcg', '-machine', 'pc', '-m', '512', '-smp', '2',
    '-display', 'none', '-serial', 'stdio', '-monitor', 'none', '-snapshot',
    '-no-reboot', '-kernel', str(images / 'bzImage'),
    '-drive', f'file={images / "rootfs.ext4"},format=raw,if=virtio',
    '-append', 'root=/dev/vda rw console=ttyS0',
    '-netdev', 'user,id=net0', '-device', 'virtio-net-pci,netdev=net0'],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    creationflags=subprocess.CREATE_NO_WINDOW)
ready = threading.Event()
output = bytearray()
elapsed = None


def read_serial():
    global elapsed
    while True:
        char = proc.stdout.read(1)
        if not char:
            return
        output.extend(char)
        if output.endswith(b'dev-os login:'):
            elapsed = round(time.monotonic() - started, 3)
            ready.set()
            return


reader = threading.Thread(target=read_serial, daemon=True)
reader.start()
try:
    passed = ready.wait(90)
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    reader.join(timeout=5)
    proc.stdin.close()
    proc.stdout.close()
(reports / 'windows-tcg.log').write_bytes(output)
report = {'passed': passed, 'host': 'Windows', 'acceleration': 'tcg',
          'memory_mib': 512, 'vcpus': 2, 'boot_to_login_seconds': elapsed,
          'scope': 'Exported kernel/disk boot to login; authentication and package tests run separately in WSL/KVM.'}
(reports / 'windows-tcg.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
raise SystemExit(0 if passed else 1)
