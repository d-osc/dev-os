#!/bin/sh
# Final three proofs in one boot on a FRESH disk (a genuine first boot):
#   [A] viewer  — dev-view --test renders the seeded ~/Pictures sample
#   [B] wizard  — appears on first login, keyboard-driven: creates user
#                 'tester', sets Asia/Bangkok, picks Thai, writes its flag
#   [C] layout  — dev-pointer --click-kb presses the tray badge; the
#                 settings flip and dev-files renders the same keys
#                 differently per layout
set -eu
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
SRC=/home/ondev/src/dev-os-build/project/out/buildroot/images
VM=/home/ondev/devos-vm
OUT=/mnt/c/Users/ondev/Projects/dev-os/out/vm
SCRIPTS=/mnt/c/Users/ondev/Projects/dev-os/scripts

pkill -9 qemu-system 2>/dev/null || true
sleep 1
cp --sparse=always "$SRC/rootfs.ext2" "$VM/disk.img"
rm -f "$VM"/*.sock "$VM"/login.ppm "$VM"/wizard-*.png "$VM"/bar-*.ppm
echo "[1] fresh boot $(date +%H:%M:%S)" > "$OUT/final3.log"

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
[ -n "$up" ] || { echo "[!] NO GRAPHICS" >> "$OUT/final3.log"; exit 1; }
sleep 12
timeout 120 python3 "$SCRIPTS/vm-vnc-login-full.py" >> "$OUT/final3.log" 2>&1 || true
echo "[2] login sent; waiting for the wizard" >> "$OUT/final3.log"
sleep 25

# ---- [B] wizard: drive it entirely from the keyboard ----------------------
shot "$VM/wizard-up.ppm"
python3 "$SCRIPTS/vm-session-nopoweroff.py" \
    'ps | grep dev-wizard | grep -v grep' >> "$OUT/final3.log" 2>&1 || true

python3 - >> "$OUT/final3.log" 2>&1 <<'PY' || true
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
press('return')                       # welcome -> user form
type_chars('tester')
press('tab')
type_chars('Test User')
press('tab')
type_chars('secret1')
press('tab')
type_chars('secret1')
press('tab')
type_chars('yl7VxD1M-oW5O4W0lCw5q0jO')  # sudo password
press('return')                       # create user -> timezone
time.sleep(4)
press('2')                            # Asia/Bangkok
press('return')
time.sleep(2)
press('2')                            # Thai - Kedmanee
press('return')
time.sleep(1)
press('return')                       # finish
time.sleep(2)
client.captureScreen('/home/ondev/devos-vm/wizard-done.png')
client.disconnect()
print('WIZARD-DRIVEN')
PY

python3 "$SCRIPTS/vm-session-nopoweroff.py" \
    'grep tester /etc/passwd' \
    'ls /home/tester | head -3' \
    'su - tester -c id' \
    'date; readlink /etc/localtime' \
    'cat /home/dev/.config/devos/settings.json' \
    'ls /home/dev/.config/devos/wizard-done' \
    >> "$OUT/final3.log" 2>&1 || true

# ---- [A] viewer ------------------------------------------------------------
python3 "$SCRIPTS/vm-session-nopoweroff.py" \
    'su - dev -c "DISPLAY=:0 DEVOS_DATA_DIR=/tmp dev-view --test" > /tmp/view.json 2>&1; cat /tmp/view.json' \
    >> "$OUT/final3.log" 2>&1 || true
python3 "$SCRIPTS/vm-session-nopoweroff.py" "base64 -w0 /tmp/view.png" 2>/dev/null \
    | python3 -c "import base64,sys,re
data = sys.stdin.read()
match = re.findall(r'[A-Za-z0-9+/=]{200,}', data)
sys.stdout.buffer.write(base64.b64decode(match[0]) if match else b'')" > "$OUT/view-render.png"
python3 - "$OUT/view-render.png" >> "$OUT/final3.log" 2>&1 <<'PY' || true
import sys
from PIL import Image
image = Image.open(sys.argv[1]).convert('RGB')
width, height = image.size
points = [(x, y) for y in range(int(height * 0.55), height - 12, 4)
          for x in range(24, width - 24, 8)]
colors = {image.getpixel(point) for point in points}
lums = [sum(image.getpixel(point)) for point in points]
print('canvas-distinct-colors=%d luma-spread=%d'
      % (len(colors), max(lums) - min(lums)))
print('VIEW-IMAGE-RENDERED' if len(colors) > 40 and max(lums) - min(lums) > 300
      else 'VIEW-CANVAS-EMPTY')
PY

# ---- [C] keyboard-layout badge ---------------------------------------------
pull_last() { # $1 = local png
    python3 "$SCRIPTS/vm-session-nopoweroff.py" "base64 -w0 /tmp/files.png" 2>/dev/null \
        | python3 -c "import base64,sys,re
data = sys.stdin.read()
match = re.findall(r'[A-Za-z0-9+/=]{200,}', data)
sys.stdout.buffer.write(base64.b64decode(match[0]) if match else b'')" > "$1"
}

shot "$VM/bar-before.ppm"
# Round 1: toggle OFF (wizard had set Thai) — the same keys render ASCII.
python3 "$SCRIPTS/vm-session-nopoweroff.py" \
    'cat /tmp/devos-bar-1000' \
    'su - dev -c "DISPLAY=:0 dev-pointer --click-kb"' \
    'cat /home/dev/.config/devos/settings.json' \
    'su - dev -c "DISPLAY=:0 DEVOS_DATA_DIR=/tmp dev-files --test --label-thai" > /tmp/f1.json 2>&1; echo FILES1_RC=$?' \
    >> "$OUT/final3.log" 2>&1 || true
pull_last "$OUT/files-layout-off.png"
# Round 2: toggle back ON — the same keys render Thai.
python3 "$SCRIPTS/vm-session-nopoweroff.py" \
    'su - dev -c "DISPLAY=:0 dev-pointer --click-kb"' \
    'cat /home/dev/.config/devos/settings.json' \
    'su - dev -c "DISPLAY=:0 DEVOS_DATA_DIR=/tmp dev-files --test --label-thai" > /tmp/f2.json 2>&1; echo FILES2_RC=$?' \
    >> "$OUT/final3.log" 2>&1 || true
sleep 1
shot "$VM/bar-after.ppm"
pull_last "$OUT/files-layout-on.png"
cp "$VM"/wizard-up.ppm "$VM"/wizard-done.png "$VM"/bar-*.ppm "$OUT/" 2>/dev/null || true

python3 - "$OUT/bar-before.ppm" "$OUT/bar-after.ppm" \
         "$OUT/files-layout-off.png" "$OUT/files-layout-on.png" >> "$OUT/final3.log" 2>&1 <<'PY' || true
import sys
from PIL import Image
before = Image.open(sys.argv[1]).convert('RGB')
after = Image.open(sys.argv[2]).convert('RGB')
width, height = before.size
badge = [(x, y) for y in range(height - 40, height) for x in range(width - 320, width - 180, 2)]
delta = sum(abs(sum(after.getpixel(p)) - sum(before.getpixel(p))) for p in badge)
print('badge-region-delta=%d' % delta)
print('KB-BADGE-TOGGLED' if delta > 1500 else 'KB-BADGE-UNCHANGED')

off = Image.open(sys.argv[3]).convert('RGB')
on = Image.open(sys.argv[4]).convert('RGB')
ow, oh = off.size
pathbar = [(x, y) for y in range(40, 82) for x in range(20, ow - 140, 2)]
diff = sum(abs(sum(on.getpixel(p)) - sum(off.getpixel(p))) for p in pathbar)
print('pathbar-delta=%d' % diff)
print('LAYOUT-CHANGES-RENDERING' if diff > 3000 else 'LAYOUT-NO-VISIBLE-CHANGE')
PY

pkill -9 qemu-system 2>/dev/null || true
echo "[3] done $(date +%H:%M:%S)" >> "$OUT/final3.log"
