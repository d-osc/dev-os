#!/bin/sh
# Suspend proof: boot, verify S3 support, suspend via serial (root), show
# the guest freezes, wake it with a key event, and confirm resume.
set -eu
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
SRC=/home/ondev/src/dev-os-build/project/out/buildroot/images
VM=/home/ondev/devos-vm
OUT=/mnt/c/Users/ondev/projects/dev-os/out/vm
mkdir -p "$VM" "$OUT"

pkill -9 qemu-system 2>/dev/null || true
sleep 1
cp --sparse=always "$SRC/rootfs.ext2" "$VM/disk.img"
rm -f "$VM"/*.sock "$VM"/*.ppm
echo "[1] boot $(date +%H:%M:%S)" > "$OUT/suspend.log"

nohup setsid qemu-system-x86_64 -M pc -enable-kvm -cpu host -m 1024 \
    -kernel "$SRC/bzImage" \
    -drive file="$VM/disk.img",if=virtio,format=raw \
    -append "rootwait root=/dev/vda console=tty1 console=ttyS0 quiet" \
    -vga std -vnc :0 \
    -serial unix:"$VM/serial.sock",server,nowait \
    -monitor unix:"$VM/monitor.sock",server,nowait \
    > "$VM/qemu.log" 2>&1 < /dev/null &

# wait for the login prompt over serial (graphics not needed here)
up=""
for tick in $(seq 1 24); do
    sleep 10
    if timeout 3 python3 - <<'PYEOF'
import socket, sys
try:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect('/home/ondev/devos-vm/serial.sock')
    s.settimeout(0.5)
    s.sendall(b'\n')
    import time; time.sleep(0.8)
    data = b''
    try:
        data = s.recv(4096)
    except socket.timeout:
        pass
    sys.exit(0 if b'login' in data or b'# ' in data else 1)
except OSError:
    sys.exit(1)
PYEOF
    then up=1; break; fi
done
[ -n "$up" ] || { echo "[!] serial never came up" >> "$OUT/suspend.log"; exit 1; }
echo "[2] serial up" >> "$OUT/suspend.log"

python3 - "$VM" "$OUT" <<'PYEOF' >> "$OUT/suspend.log" 2>&1 || true
import socket
import subprocess
import sys
import time

vm, out = sys.argv[1], sys.argv[2]


def session():
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(vm + '/serial.sock')
    s.settimeout(0.3)
    return s


def drain(s, seconds):
    end = time.monotonic() + seconds
    data = b''
    while time.monotonic() < end:
        try:
            chunk = s.recv(4096)
            if chunk:
                data += chunk
        except socket.timeout:
            pass
    return data


def run(s, cmd, wait=1.5, collect=3.0):
    s.sendall(cmd.encode() + b'\n')
    time.sleep(wait)
    return drain(s, collect).decode('utf-8', 'replace')


s = session()
for _ in range(3):
    s.sendall(b'\x03')
    time.sleep(0.3)
drain(s, 0.8)
run(s, 'root', 1.0, 1.0)
run(s, 'mSJlOJ51W6nbaiC83JRqybPv', 1.5, 1.2)
run(s, 'stty -echo', 0.5, 0.6)
print('S3 support:', run(s, 'cat /sys/power/state', 1.0, 2.5).strip()[:60])
print('before suspend ps:', [line for line in run(
    s, 'ps w | grep -cE "openbox|init"', 1.0, 2.0).splitlines() if line.strip()][-1:])
print('--- suspending (echo mem > /sys/power/state)')
s.sendall(b'echo mem > /sys/power/state\n')
time.sleep(3)
print('--- guest frozen check: sending echo, expecting NO reply')
s.sendall(b'echo AWAKE\n')
time.sleep(3)
reply = drain(s, 3.0)
print('reply while suspended:', repr(reply[:80]))
print('FROZEN' if b'AWAKE' not in reply else 'NOT-FROZEN')
print('--- waking via key event')
subprocess.run(['sh', '-c',
                "echo 'sendkey shift' | timeout 4 socat - UNIX-CONNECT:%s/monitor.sock"
                " >/dev/null 2>&1 || true" % vm])
time.sleep(4)
s.sendall(b'echo AWAKE2\n')
time.sleep(3)
reply2 = drain(s, 3.0)
print('reply after wake:', repr(reply2[:100]))
print('RESUMED' if b'AWAKE2' in reply2 else 'NOT-RESUMED')
print('after resume ps:', run(s, 'ps w | grep -cE "openbox|init"',
                             1.0, 2.0).strip().splitlines()[-1:])
PYEOF
echo "[3] done" >> "$OUT/suspend.log"
pkill -9 qemu-system 2>/dev/null || true
