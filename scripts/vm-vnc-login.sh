#!/bin/sh
# Full GUI login, for real: boot to the greeter, type the dev password
# through VNC (the same input path a human at the console would use),
# and capture the session that starts as the logged-in user.
set -eu
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
SRC=/home/ondev/src/dev-os-build/project/out/buildroot/images
VM=/home/ondev/devos-vm
OUT=/mnt/c/Users/ondev/Projects/dev-os/out/vm
mkdir -p "$VM" "$OUT"

cp --sparse=always "$SRC/rootfs.ext2" "$VM/disk.img"
cp "$SRC/bzImage" "$VM/bzImage"
rm -f "$VM"/*.sock "$VM"/*.ppm
echo "[1] boot $(date +%H:%M:%S)" > "$OUT/vnc-login.log"

DISPLAY=:0 qemu-system-x86_64 -M pc -enable-kvm -cpu host -m 1024 \
    -kernel "$VM/bzImage" \
    -drive file="$VM/disk.img",if=virtio,format=raw \
    -append "rootwait root=/dev/vda console=tty1 console=ttyS0 quiet" \
    -vga std -vnc :0 \
    -serial unix:"$VM/serial.sock",server,nowait \
    -monitor unix:"$VM/monitor.sock",server,nowait &
QEMU_PID=$!
echo "[2] qemu $QEMU_PID (vnc :5900)" >> "$OUT/vnc-login.log"

shot() {
    (echo "screendump $VM/$1.ppm"; sleep 0.4) | timeout 6 socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1 || true
    sleep 2
}

for tick in $(seq 1 20); do
    sleep 10
    shot w
    python3 /mnt/c/Users/ondev/Projects/dev-os/scripts/vm-graphics-probe.py "$VM/w.ppm" && break
done
sleep 15
shot greeter
echo "[3] greeter captured $(date +%H:%M:%S)" >> "$OUT/vnc-login.log"

export PATH="$HOME/.local/bin:$PATH"
cat > /tmp/vnc-login.py <<'PYEOF'
import sys
import time

sys.path.insert(0, '/home/ondev/.local/lib/python3.12/site-packages')
from vncdotool import api

client = api.connect('localhost::5900', timeout=30)
time.sleep(1.5)
password = list('yl7VxD1M-oW5O4W0lCw5q0jO')
# The username field is prefilled with 'dev'; press Return there to submit
# is not what we want -- focus starts on the user field, so move to the
# password field first with Tab, then type.
client.keyPress('tab')
time.sleep(0.4)
for character in password:
    client.keyPress(character)
    time.sleep(0.25)
time.sleep(0.5)
client.keyPress('return')
time.sleep(0.5)
print('TYPED')
PYEOF
python3 /tmp/vnc-login.py >> "$OUT/vnc-login.log" 2>&1 || true
echo "[4] typed $(date +%H:%M:%S)" >> "$OUT/vnc-login.log"

for tick in $(seq 1 12); do
    sleep 10
    shot login-$tick
    if ! cmp -s "$VM/greeter.ppm" "$VM/login-$tick.ppm"; then
        echo "[5] screen changed at $((tick*10))s $(date +%H:%M:%S)" >> "$OUT/vnc-login.log"
        sleep 10
        shot desktop
        sleep 10
        shot desktop2
        break
    fi
done

cp "$VM"/*.ppm "$OUT/" 2>/dev/null || true
echo "[6] done $(date +%H:%M:%S)" >> "$OUT/vnc-login.log"
kill $QEMU_PID 2>/dev/null || true
