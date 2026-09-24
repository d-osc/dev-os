#!/bin/sh
# Does a QEMU sendkey produce bytes on /dev/input/event1 (the real AT
# keyboard node)?  Kernel-level truth, independent of X.
set -eu
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
SRC=/home/ondev/src/dev-os-build/project/out/buildroot/images
VM=/home/ondev/devos-vm
OUT=/mnt/c/Users/ondev/Projects/dev-os/out/vm
mkdir -p "$VM" "$OUT"

cp --sparse=always "$SRC/rootfs.ext2" "$VM/disk.img"
cp "$SRC/bzImage" "$VM/bzImage"
rm -f "$VM"/*.sock "$VM"/*.ppm

DISPLAY=:0 qemu-system-x86_64 -M pc -enable-kvm -cpu host -m 1024 \
    -kernel "$VM/bzImage" \
    -drive file="$VM/disk.img",if=virtio,format=raw \
    -append "rootwait root=/dev/vda console=tty1 console=ttyS0 quiet" \
    -vga std -display none \
    -serial unix:"$VM/serial.sock",server,nowait \
    -monitor unix:"$VM/monitor.sock",server,nowait &
QEMU_PID=$!

for tick in $(seq 1 20); do
    sleep 10
    echo "screendump $VM/w.ppm" | socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1
    sleep 2
    python3 /mnt/c/Users/ondev/Projects/dev-os/scripts/vm-graphics-probe.py "$VM/w.ppm" && break
done

python3 - > "$OUT/kernelkey-result.txt" 2>&1 <<'PYEOF' || true
import socket
import subprocess
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

# Capture event1 for 6 seconds while injecting three keys.
send('(timeout 6 cat /dev/input/event1 | od -An -tx1 > /tmp/k1.txt) & echo CAPTURING\n')
time.sleep(1.0)
drain(1.0)
for key in ('d', 'x', 'ret'):
    monitor('sendkey %s' % key)
    time.sleep(0.5)
time.sleep(6.5)
send('wc -c /tmp/k1.txt; head -6 /tmp/k1.txt\n')
time.sleep(1.5)
print('=== event1 capture ===')
print(drain(5.0))

# Also ask X directly what it thinks: list input devices via xinput if
# present, else probe the server through xdpyinfo-free python.
send('ls /usr/bin | grep -iE "xinput|xdpyinfo|xtst" || echo no-x-tools\n')
time.sleep(1.5)
print(drain(4.0))
PYEOF

kill $QEMU_PID 2>/dev/null || true
