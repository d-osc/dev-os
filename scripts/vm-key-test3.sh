#!/bin/sh
# QMP input-send-event vs HMP sendkey: which one reaches the guest kernel?
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
    -qmp unix:"$VM/qmp.sock",server,nowait &
QEMU_PID=$!

for tick in $(seq 1 20); do
    sleep 10
    echo "screendump $VM/w.ppm" | socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1
    sleep 2
    python3 /mnt/c/Users/ondev/Projects/dev-os/scripts/vm-graphics-probe.py "$VM/w.ppm" && break
done

python3 - > "$OUT/keytest3-result.txt" 2>&1 <<'PYEOF' || true
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


# --- QMP helper with persistent connection ---
qmp = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
qmp.connect('/home/ondev/devos-vm/qmp.sock')
qmp.settimeout(0.5)
greeting = b''
end = time.monotonic() + 3
while time.monotonic() < end:
    try:
        chunk = qmp.recv(4096)
        if chunk:
            greeting += chunk
            if b'"return"' in greeting or b'greeting' in greeting:
                break
    except socket.timeout:
        continue


def qmp_send(payload):
    qmp.sendall((json.dumps(payload) + '\n').encode())


def qmp_read(seconds=1.5):
    end = time.monotonic() + seconds
    data = b''
    while time.monotonic() < end:
        try:
            chunk = qmp.recv(4096)
            if chunk:
                data += chunk
        except socket.timeout:
            continue
    return data.decode('utf-8', 'replace')


qmp_read(2.0)
qmp_send({'execute': 'qmp_capabilities'})
print('=== qmp capabilities ===')
print(qmp_read(1.5))

# --- guest login ---
send('\n'); time.sleep(1.0); drain(1.0)
send('root\n'); time.sleep(1.2); drain(1.0)
send('mSJlOJ51W6nbaiC83JRqybPv\n'); time.sleep(2.0); drain(1.5)
send('stty -echo\n'); time.sleep(0.4); drain(0.6)


def capture(label):
    send('rm -f /tmp/k.txt; (timeout 5 cat /dev/input/event1 | od -An -tx1 > /tmp/k.txt) &\n')
    time.sleep(0.8)
    drain(0.5)


def report(label):
    time.sleep(5.5)
    send('echo SIZE_$(wc -c < /tmp/k.txt); head -4 /tmp/k.txt\n')
    time.sleep(1.5)
    print('=== %s ===' % label)
    print(drain(5.0))


capture('qmp')
for key in ('a', 'b'):
    qmp_send({'execute': 'input-send-event', 'arguments': {'events': [
        {'type': 'key', 'data': {'down': True, 'key': {'type': 'qcode', 'data': key}}},
        {'type': 'key', 'data': {'down': False, 'key': {'type': 'qcode', 'data': key}}},
    ]}})
    print(qmp_read(1.0))
    time.sleep(0.4)
report('qmp input-send-event')

capture('qmp-device')
for key in ('c', 'd'):
    qmp_send({'execute': 'input-send-event', 'arguments': {
        'device': 'QEMU PS/2 Keyboard', 'events': [
            {'type': 'key', 'data': {'down': True, 'key': {'type': 'qcode', 'data': key}}},
            {'type': 'key', 'data': {'down': False, 'key': {'type': 'qcode', 'data': key}}},
        ]}})
    print(qmp_read(1.0))
    time.sleep(0.4)
report('qmp named device')
PYEOF

kill $QEMU_PID 2>/dev/null || true
