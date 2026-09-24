#!/bin/sh
# Boot to the greeter and trace the keyboard path: kernel evdev devices,
# atkbd in dmesg, what Xorg's evdev driver picked up, and whether a QEMU
# sendkey actually lands in /dev/input/event0.
set -eu
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
SRC=/home/ondev/src/dev-os-build/project/out/buildroot/images
VM=/home/ondev/devos-vm
OUT=/mnt/c/Users/ondev/Projects/dev-os/out/vm
mkdir -p "$VM" "$OUT"

cp --sparse=always "$SRC/rootfs.ext2" "$VM/disk.img"
cp "$SRC/bzImage" "$VM/bzImage"
rm -f "$VM"/*.sock "$VM"/*.ppm
echo "[1] boot $(date +%H:%M:%S)" > "$OUT/input-probe.log"

DISPLAY=:0 qemu-system-x86_64 -M pc -enable-kvm -cpu host -m 1024 \
    -kernel "$VM/bzImage" \
    -drive file="$VM/disk.img",if=virtio,format=raw \
    -append "rootwait root=/dev/vda console=tty1 console=ttyS0 quiet" \
    -vga std -display none \
    -serial unix:"$VM/serial.sock",server,nowait \
    -monitor unix:"$VM/monitor.sock",server,nowait &
QEMU_PID=$!

shot() {
    echo "screendump $VM/$1.ppm" | socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1
    sleep 2
}
send() { for key in "$@"; do echo "sendkey $key" | socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1; sleep 0.2; done; }

for tick in $(seq 1 20); do
    sleep 10
    shot wait-$tick
    python3 /mnt/c/Users/ondev/Projects/dev-os/scripts/vm-graphics-probe.py "$VM/wait-$tick.ppm" && break
done
echo "[2] greeter up $(date +%H:%M:%S)" >> "$OUT/input-probe.log"

echo "--- kernel input state" >> "$OUT/input-probe.log"
python3 /mnt/c/Users/ondev/Projects/dev-os/scripts/vm-session-nopoweroff.py \
    'cat /proc/bus/input/devices | head -14' \
    'dmesg | grep -iE "atkbd|i8042|input" | head -8' \
    'ls -la /dev/input/ 2>&1' \
    'grep -A3 -iE "evdev|input" /var/log/Xorg.0.log | head -16' \
    >> "$OUT/input-probe.log" 2>&1 || true

echo "--- live sendkey test" >> "$OUT/input-probe.log"
python3 - >> "$OUT/input-probe.log" 2>&1 <<'PYEOF' || true
import socket
import subprocess
import threading
import time

sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect('/home/ondev/devos-vm/serial.sock')
sock.settimeout(0.5)


def drain(seconds):
    end = time.monotonic() + seconds
    data = b''
    while time.monotonic() < end:
        try:
            chunk = sock.recv(4096)
            if chunk:
                data += chunk
        except socket.timeout:
            continue
    return data.decode('utf-8', 'replace')


def send(text):
    sock.sendall(text.encode())


def monitor(command):
    subprocess.run(['socat', '-', 'UNIX-CONNECT:/home/ondev/devos-vm/monitor.sock'],
                   input=(command + '\n').encode(), capture_output=True, timeout=5)


send('\n')
time.sleep(1.0)
drain(1.0)
send('root\n')
time.sleep(1.2)
drain(1.0)
send('mSJlOJ51W6nbaiC83JRqybPv\n')
time.sleep(2.0)
drain(1.5)

# Read the keyboard evdev node in the background while QEMU injects keys.
send('(head -c 96 /dev/input/event0 | od -An -tx1 > /tmp/keys.txt 2>&1; echo KEYCAPTURE-DONE >> /tmp/keys.txt) &\n')
time.sleep(1.0)
drain(1.0)
for key in ('a', 'shift-b', 'c'):
    monitor('sendkey %s' % key)
    time.sleep(0.4)
time.sleep(2.0)
send('cat /tmp/keys.txt\n')
time.sleep(1.5)
print(drain(4.0))
PYEOF

echo "[3] done $(date +%H:%M:%S)" >> "$OUT/input-probe.log"
kill $QEMU_PID 2>/dev/null || true
