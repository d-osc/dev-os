#!/bin/sh
# In a REAL running guest: try three sendkey variants (plain echo, sleep
# after send, single long connection) and see which reaches /dev/input.
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

python3 - > "$OUT/keytest2-result.txt" 2>&1 <<'PYEOF' || true
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


MON = '/home/ondev/devos-vm/monitor.sock'


def monitor_text(command, hold=0.0):
    process = subprocess.run(
        ['socat', '-', 'UNIX-CONNECT:' + MON],
        input=(command + '\n').encode(), capture_output=True, timeout=6)
    return process.stdout.decode('utf-8', 'replace')[-160:]


send('\n'); time.sleep(1.0); drain(1.0)
send('root\n'); time.sleep(1.2); drain(1.0)
send('mSJlOJ51W6nbaiC83JRqybPv\n'); time.sleep(2.0); drain(1.5)
send('stty -echo\n'); time.sleep(0.4); drain(0.6)

def capture(variant, keys):
    send('rm -f /tmp/k.txt; (timeout 5 cat /dev/input/event1 | od -An -tx1 > /tmp/k.txt) &\n')
    time.sleep(0.8)
    drain(0.5)
    for key in keys:
        if variant == 'echo':
            subprocess.run("echo 'sendkey %s' | socat - UNIX-CONNECT:%s >/dev/null 2>&1"
                           % (key, MON), shell=True)
        elif variant == 'hold':
            subprocess.run("(echo 'sendkey %s'; sleep 0.6) | socat - UNIX-CONNECT:%s "
                           ">/dev/null 2>&1" % (key, MON), shell=True)
        elif variant == 'python':
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.connect(MON)
            client.sendall(('sendkey %s\n' % key).encode())
            time.sleep(0.6)
            client.close()
        time.sleep(0.4)
    time.sleep(5.5)
    send('echo SIZE=$(wc -c < /tmp/k.txt); head -4 /tmp/k.txt\n')
    time.sleep(1.5)
    print('=== variant', variant, '===')
    print(drain(5.0))

print('=== sendkey monitor response sample ===')
print(monitor_text('sendkey d'))
capture('echo', ['a', 'b'])
capture('hold', ['c', 'd'])
capture('python', ['e', 'f'])
PYEOF

kill $QEMU_PID 2>/dev/null || true
