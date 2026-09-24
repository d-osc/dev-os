#!/bin/sh
# Wizard proof: a genuine first boot. The wizard must appear with keyboard
# focus, take the whole setup from the keyboard (user 'tester', timezone
# Asia/Bangkok, Thai input), and leave verifiable state behind.
set -eu
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
SRC=/home/ondev/src/dev-os-build/project/out/buildroot/images
VM=/home/ondev/devos-vm
OUT=/mnt/c/Users/ondev/Projects/dev-os/out/vm
SCRIPTS=/mnt/c/Users/ondev/Projects/dev-os/scripts

pkill -9 qemu-system 2>/dev/null || true
sleep 1
cp --sparse=always "$SRC/rootfs.ext2" "$VM/disk.img"
rm -f "$VM"/*.sock "$VM"/login.ppm
echo "[1] fresh boot $(date +%H:%M:%S)" > "$OUT/wizard.log"

nohup setsid qemu-system-x86_64 -M pc -enable-kvm -cpu host -m 1024 \
    -kernel "$SRC/bzImage" -drive file="$VM/disk.img",if=virtio,format=raw \
    -append "rootwait root=/dev/vda console=tty1 console=ttyS0 quiet" \
    -vga none -device virtio-vga -vnc :0 -usb -device usb-tablet \
    -device virtio-net-pci,netdev=net0 -netdev user,id=net0 \
    -serial unix:"$VM/serial.sock",server,nowait \
    -monitor unix:"$VM/monitor.sock",server,nowait \
    > "$VM/qemu.log" 2>&1 < /dev/null &
sleep 6

shot() {
    (echo "screendump $1"; sleep 0.4) | timeout 6 socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1 || true
    sleep 1
}
up=""
for tick in $(seq 1 24); do
    sleep 10
    rm -f "$VM/login.ppm"
    shot "$VM/login.ppm"
    if [ -f "$VM/login.ppm" ] && python3 "$SCRIPTS/vm-graphics-probe.py" "$VM/login.ppm" 2>/dev/null; then
        up=1; break
    fi
done
[ -n "$up" ] || { echo "[!] NO GRAPHICS" >> "$OUT/wizard.log"; exit 1; }
sleep 12
timeout 120 python3 "$SCRIPTS/vm-vnc-login-full.py" >> "$OUT/wizard.log" 2>&1 || true
echo "[2] login sent" >> "$OUT/wizard.log"
sleep 25
shot "$VM/wizard-live.ppm"
python3 "$SCRIPTS/vm-session-nopoweroff.py" \
    'ps | grep dev-wizard | grep -v grep' >> "$OUT/wizard.log" 2>&1 || true

python3 - >> "$OUT/wizard.log" 2>&1 <<'PY'
import sys, time
sys.path.insert(0, '/home/ondev/.local/lib/python3.12/site-packages')
from vncdotool import api
client = api.connect('localhost::5900', timeout=30)
time.sleep(0.8)
def type_chars(text):
    for character in text:
        client.keyPress(character)
        time.sleep(0.24)
def press(key):
    client.keyPress(key)
    time.sleep(0.6)
press('return')                        # welcome -> user form
type_chars('tester')
press('tab')
type_chars('Test User')
press('tab')
type_chars('secret1')
press('tab')
type_chars('secret1')
press('tab')
type_chars('yl7VxD1M-oW5O4W0lCw5q0jO')
press('return')                        # create the user
time.sleep(5)
press('2')                             # Asia/Bangkok
press('return')
time.sleep(3)
press('2')                             # Thai - Kedmanee
press('return')
time.sleep(2)
press('return')                        # finish
time.sleep(2)
client.captureScreen('/home/ondev/devos-vm/wizard-after.png')
client.captureScreen('/home/ondev/devos-vm/wizard-after.png')
sys.stdout.flush()
import os
os._exit(0)                            # vncdotool's disconnect can hang
PY

shot "$VM/wizard-final.ppm"
python3 "$SCRIPTS/vm-session-nopoweroff.py" \
    'grep tester /etc/passwd' \
    'su - tester -c id' \
    'ls /home/tester | head -3' \
    'date; readlink /etc/localtime' \
    'cat /home/dev/.config/devos/settings.json' \
    'ls /home/dev/.config/devos/wizard-done' \
    'cat /tmp/devos-wizard.log' \
    >> "$OUT/wizard.log" 2>&1 || true
cp "$VM"/wizard-*.ppm "$OUT/" 2>/dev/null || true
pkill -9 qemu-system 2>/dev/null || true
echo "[3] done $(date +%H:%M:%S)" >> "$OUT/wizard.log"
