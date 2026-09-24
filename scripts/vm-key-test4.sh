#!/bin/sh
# QMP input-send-event into an explicit usb-kbd device: does it reach the
# guest kernel input nodes?
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
    -monitor unix:"$VM/monitor.sock",server,nowait \
    -qmp unix:"$VM/qmp.sock",server,nowait \
    -usb -device usb-kbd,id=kbd0 &
QEMU_PID=$!

for tick in $(seq 1 20); do
    sleep 10
    echo "screendump $VM/w.ppm" | socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1
    sleep 2
    python3 /mnt/c/Users/ondev/Projects/dev-os/scripts/vm-graphics-probe.py "$VM/w.ppm" && break
done

cat > /tmp/qmp-keys.py <<'PYEOF'
import json
import socket
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


qmp = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
qmp.connect('/home/ondev/devos-vm/qmp.sock')
qmp.settimeout(0.5)
time.sleep(0.5)
qmp.recv(65536)
qmp.sendall(b'{"execute":"qmp_capabilities"}\n')
time.sleep(0.5)
qmp.recv(65536)


def key(name, device=None):
    events = [{'type': 'key', 'data': {'down': True,
                                       'key': {'type': 'qcode', 'data': name}}},
              {'type': 'key', 'data': {'down': False,
                                       'key': {'type': 'qcode', 'data': name}}}]
    arguments = {'events': events}
    if device:
        arguments['device'] = device
    qmp.sendall((json.dumps({'execute': 'input-send-event',
                             'arguments': arguments}) + '\n').encode())
    time.sleep(0.3)
    try:
        qmp.settimeout(1.0)
        return qmp.recv(65536).decode().strip()
    except socket.timeout:
        return '<no reply>'


send('\n'); time.sleep(1.0); drain(1.0)
send('root\n'); time.sleep(1.2); drain(1.0)
send('mSJlOJ51W6nbaiC83JRqybPv\n'); time.sleep(2.0); drain(1.5)
send('stty -echo\n'); time.sleep(0.4); drain(0.6)

send('rm -f /tmp/k*.txt; for n in 0 1 2 3 4; do (timeout 8 cat /dev/input/event$n 2>/dev/null | od -An -tx1 > /tmp/k$n.txt) & done\n')
time.sleep(1.0)
drain(0.8)
for name in ('a', 'b'):
    print('usb:', key(name, 'kbd0'))
    time.sleep(0.4)
print('default:', key('c'))
time.sleep(8.5)
send('for n in 0 1 2 3 4; do echo NODE$n=$(wc -c < /tmp/k$n.txt 2>/dev/null || echo NA); done; head -3 /tmp/k3.txt\n')
time.sleep(1.5)
print(drain(5.0))
PYEOF
python3 /tmp/qmp-keys.py > "$OUT/keytest4-result.txt" 2>&1 || true

kill $QEMU_PID 2>/dev/null || true
