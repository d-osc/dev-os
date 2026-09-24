#!/bin/sh
# Boot to the greeter and pull the whole Xorg log out through serial.
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

python3 /mnt/c/Users/ondev/Projects/dev-os/scripts/vm-session-nopoweroff.py \
    'base64 /var/log/Xorg.0.log > /tmp/x.b64; wc -c /tmp/x.b64' \
    > "$OUT/xorg-transfer.log" 2>&1 || true

python3 - >> "$OUT/Xorg.0.log" 2>&1 <<'PYEOF' || true
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
            chunk = sock.recv(65536)
            if chunk:
                data += chunk
        except socket.timeout:
            continue
    return data


def expect(needle, seconds=25):
    collected = ''
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        collected += drain(0.4).decode('utf-8', 'replace')
        if needle in collected:
            return collected
    raise SystemExit('missing %r' % needle)


sock.sendall(b'\n')
time.sleep(1.0)
drain(1.0)
sock.sendall(b'root\n')
time.sleep(1.2)
drain(1.0)
sock.sendall(b'mSJlOJ51W6nbaiC83JRqybPv\n')
time.sleep(2.0)
expect('~# ')
sock.sendall(b'stty -echo; cat /tmp/x.b64\n')
time.sleep(1.0)
raw = b''
end = time.monotonic() + 40
while time.monotonic() < end:
    raw += drain(0.6)
    if b'root@dev-os:~#' in raw[-60:]:
        break
import base64
import sys
body = raw.split(b'stty -echo; cat /tmp/x.b64\n', 1)[-1]
body = body.split(b'root@dev-os:~#')[0]
clean = b''.join(body.split())
sys.stdout.buffer.write(base64.b64decode(clean))
PYEOF

kill $QEMU_PID 2>/dev/null || true
