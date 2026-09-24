#!/bin/sh
# Image-viewer proof: boot, log in, run dev-view --test against the seeded
# ~/Pictures sample, pull the render, and check the canvas actually shows
# image content (a gradient + checkerboard, not a flat panel).
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
echo "[1] boot $(date +%H:%M:%S)" > "$OUT/view.log"

nohup setsid qemu-system-x86_64 -M pc -enable-kvm -cpu host -m 1024 \
    -kernel "$SRC/bzImage" \
    -drive file="$VM/disk.img",if=virtio,format=raw \
    -append "rootwait root=/dev/vda console=tty1 console=ttyS0 quiet" \
    -vga none -device virtio-vga -vnc :0 \
    -usb -device usb-tablet \
    -device virtio-net-pci,netdev=net0 -netdev user,id=net0 \
    -serial unix:"$VM/serial.sock",server,nowait \
    -monitor unix:"$VM/monitor.sock",server,nowait \
    > "$VM/qemu.log" 2>&1 < /dev/null &
sleep 6

up=""
for tick in $(seq 1 24); do
    sleep 10
    rm -f "$VM/login.ppm"
    (echo "screendump $VM/login.ppm"; sleep 0.4) | timeout 6 socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1 || true
    sleep 2
    if [ -f "$VM/login.ppm" ] && python3 "$SCRIPTS/vm-graphics-probe.py" "$VM/login.ppm" 2>/dev/null; then
        up=1; break
    fi
done
[ -n "$up" ] || { echo "[!] NO GRAPHICS" >> "$OUT/view.log"; exit 1; }
sleep 12
timeout 120 python3 "$SCRIPTS/vm-vnc-login-full.py" >> "$OUT/view.log" 2>&1 || true
sleep 24
echo "[2] logged in" >> "$OUT/view.log"

python3 "$SCRIPTS/vm-session-nopoweroff.py" \
    'ls -la /home/dev/Pictures' \
    'su - dev -c "DISPLAY=:0 DEVOS_DATA_DIR=/tmp dev-view --test" > /tmp/view.json 2>&1; cat /tmp/view.json' \
    >> "$OUT/view.log" 2>&1 || true

python3 "$SCRIPTS/vm-session-nopoweroff.py" "base64 -w0 /tmp/view.png" 2>/dev/null \
    | python3 -c "import base64,sys,re
data = sys.stdin.read()
match = re.findall(r'[A-Za-z0-9+/=]{200,}', data)
sys.stdout.buffer.write(base64.b64decode(match[0]) if match else b'')" > "$OUT/view-render.png"
[ -s "$OUT/view-render.png" ] && echo "pulled view-render.png" >> "$OUT/view.log"

python3 - "$OUT/view-render.png" >> "$OUT/view.log" 2>&1 <<'PY' || true
import sys
from PIL import Image
image = Image.open(sys.argv[1]).convert('RGB')
width, height = image.size
points = [(x, y) for y in range(int(height * 0.55), height - 12, 4)
         for x in range(24, width - 24, 8)]
colors = {image.getpixel(point) for point in points}
lums = [sum(image.getpixel(point)) for point in points]
spread = max(lums) - min(lums)
print('canvas-distinct-colors=%d luma-spread=%d' % (len(colors), spread))
print('VIEW-IMAGE-RENDERED' if len(colors) > 40 and spread > 300
      else 'VIEW-CANVAS-EMPTY')
PY

pkill -9 qemu-system 2>/dev/null || true
echo "[3] done $(date +%H:%M:%S)" >> "$OUT/view.log"
