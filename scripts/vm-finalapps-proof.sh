#!/bin/sh
# Final-apps proof: boot the rebuilt image with TWO virtio GPUs (the
# multi-monitor simulation), then prove the four remaining desktop items:
#   [A] multi-monitor — two connected DRM connectors, what xrandr sees
#   [B] browser — dev-web fetches a page from the WSL host over QEMU
#       user-net (10.0.2.2) and renders it
#   [C] media — Music lists the seeded chime.wav and aplay plays it
#   [D] HiDPI — display.scale 2.0 doubles the clock text in the bar
#   [E] screen reader — narrator setting: hovering a taskbar icon pops a
#       "Screen reader" toast
set -eu
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
SRC=/home/ondev/src/dev-os-build/project/out/buildroot/images
VM=/home/ondev/devos-vm
OUT=/mnt/c/Users/ondev/Projects/dev-os/out/vm
SCRIPTS=/mnt/c/Users/ondev/Projects/dev-os/scripts
mkdir -p "$VM" "$OUT/webroot"

pkill -9 qemu-system 2>/dev/null || true
sleep 1
cp --sparse=always "$SRC/rootfs.ext2" "$VM/disk.img"
rm -f "$VM"/*.sock "$VM"/*.ppm

# The page the browser will fetch from the host (wallpaper HTML subset).
cat > "$OUT/webroot/index.html" <<'HTML'
<!doctype html>
<html>
<body style="background-color:#0d2416">
<h1 style="left:40px;top:90px;font-size:40px;font-weight:bold;color:#7ee787">Dev OS web proof</h1>
<p style="left:40px;top:170px;font-size:22px;color:#c9d1d9">Fetched live from the WSL host over QEMU user-net.</p>
</body>
</html>
HTML
( cd "$OUT/webroot" && setsid nohup python3 -m http.server 8000 \
    > "$OUT/webroot/http.log" 2>&1 < /dev/null & )

boot_vm() { # $1 = gpu args
    nohup setsid qemu-system-x86_64 -M pc -enable-kvm -cpu host -m 1024 \
        -kernel "$SRC/bzImage" \
        -drive file="$VM/disk.img",if=virtio,format=raw \
        -append "rootwait root=/dev/vda console=tty1 console=ttyS0 quiet" \
        $1 -vnc :0 -device intel-hda -device hda-duplex \
        -netdev user,id=net0 -device virtio-net-pci,netdev=net0 \
        -serial unix:"$VM/serial.sock",server,nowait \
        -monitor unix:"$VM/monitor.sock",server,nowait \
        > "$VM/qemu.log" 2>&1 < /dev/null &
}

wait_graphics() { # sets $up
    up=""
    rm -f "$VM/login.ppm"
    for tick in $(seq 1 "$1"); do
        sleep 10
        (echo "screendump $VM/login.ppm"; sleep 0.4) | timeout 6 socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1 || true
        sleep 2
        if [ -f "$VM/login.ppm" ] && python3 "$SCRIPTS/vm-graphics-probe.py" "$VM/login.ppm" 2>/dev/null; then
            up=1
            return 0
        fi
    done
    return 1
}

echo "[1] boot A: virtio-vga + virtio-gpu-pci $(date +%H:%M:%S)" > "$OUT/finalapps.log"
boot_vm "-vga none -device virtio-vga -device virtio-gpu-pci"
if ! wait_graphics 24; then
    echo "[1b] config A showed no GUI; falling back to std-vga + virtio-gpu-pci" >> "$OUT/finalapps.log"
    pkill -9 qemu-system 2>/dev/null || true
    sleep 2
    rm -f "$VM"/*.sock
    boot_vm "-vga std -device virtio-gpu-pci"
    wait_graphics 24 || { echo "[!] NO GRAPHICS" >> "$OUT/finalapps.log"; exit 1; }
fi
sleep 12

timeout 120 python3 "$SCRIPTS/vm-vnc-login-full.py" >> "$OUT/finalapps.log" 2>&1 || true
echo "[2] login sent" >> "$OUT/finalapps.log"
sleep 25

# ---- [A] multi-monitor + [C] aplay + app launches -------------------------
python3 "$SCRIPTS/vm-session-nopoweroff.py" \
    'ls /sys/class/drm' \
    'grep -H . /sys/class/drm/card*-*/status /sys/class/drm/card*-*/enabled 2>/dev/null' \
    'su - dev -c "DISPLAY=:0 xrandr --listmonitors; DISPLAY=:0 xrandr 2>&1 | head -24"' \
    'ls -la /home/dev/Music' \
    'su - dev -c "id"' \
    'su - dev -c "aplay /home/dev/Music/chime.wav"; echo APLAY_RC=$?' \
    'su - dev -c "DISPLAY=:0 DEVOS_DATA_DIR=/tmp dev-web --test http://10.0.2.2:8000/" > /tmp/web.json 2>&1; cat /tmp/web.json' \
    'su - dev -c "DISPLAY=:0 DEVOS_DATA_DIR=/tmp dev-music --test" > /tmp/music.json 2>&1; cat /tmp/music.json' \
    >> "$OUT/finalapps.log" 2>&1 || true

pull() { # $1 remote file, $2 local png
    python3 "$SCRIPTS/vm-session-nopoweroff.py" "base64 -w0 $1" 2>/dev/null \
        | python3 -c "import base64,sys,re
data = sys.stdin.read()
match = re.findall(r'[A-Za-z0-9+/=]{200,}', data)
sys.stdout.buffer.write(base64.b64decode(match[0]) if match else b'')" > "$2"
    [ -s "$2" ] && echo "pulled $2" >> "$OUT/finalapps.log" || echo "PULL-FAILED $1" >> "$OUT/finalapps.log"
}
pull /tmp/web.png "$OUT/finalapps-web.png"
pull /tmp/music.png "$OUT/finalapps-music.png"

# ---- [D] HiDPI: same bar at scale 1.0 and 2.0 ------------------------------
python3 "$SCRIPTS/vm-session-nopoweroff.py" \
    'printf "{\"display.scale\": 2.0}" > /tmp/scale.json' \
    'su - dev -c "DISPLAY=:0 dev-shell --screenshot-prefix /tmp/norm" > /dev/null 2>&1; echo NORM_RC=$?' \
    'su - dev -c "DISPLAY=:0 DEVOS_SETTINGS=/tmp/scale.json dev-shell --settings /tmp/scale.json --screenshot-prefix /tmp/scale" > /dev/null 2>&1; echo SCALE_RC=$?' \
    >> "$OUT/finalapps.log" 2>&1 || true
pull /tmp/norm-bar.png "$OUT/finalapps-bar-100.png"
pull /tmp/scale-bar.png "$OUT/finalapps-bar-200.png"
pull /tmp/norm-menu.png "$OUT/finalapps-menu.png"
python3 - "$OUT/finalapps-bar-100.png" "$OUT/finalapps-bar-200.png" >> "$OUT/finalapps.log" 2>&1 <<'PY' || true
import sys
from PIL import Image
def span(path):
    image = Image.open(path).convert('RGB')
    width, height = image.size
    rows = [y for y in range(height)
            if any(all(part > 190 for part in image.getpixel((x, y)))
                   for x in range(width - 170, width - 12, 3))]
    return (rows[-1] - rows[0] + 1) if rows else 0
first, second = span(sys.argv[1]), span(sys.argv[2])
print('clock-text-rows scale1=%d scale2=%d ratio=%.2f' %
      (first, second, (second / first) if first else 0))
PY

# ---- [E] narrator toast over a hovered taskbar icon ------------------------
python3 "$SCRIPTS/vm-session-nopoweroff.py" \
    'printf "{\"accessibility.narrator\": true}" > /home/dev/.config/devos/settings.json' \
    "kill \$(pidof python3) 2>/dev/null; sleep 2; echo SHELL-KILLED" \
    >> "$OUT/finalapps.log" 2>&1 || true
sleep 8
if wait_graphics 24; then
    sleep 10
    timeout 120 python3 "$SCRIPTS/vm-vnc-login-full.py" >> "$OUT/finalapps.log" 2>&1 || true
    sleep 22
    timeout 60 python3 - >> "$OUT/finalapps.log" 2>&1 <<'PY' || true
import sys, time
sys.path.insert(0, '/home/ondev/.local/lib/python3.12/site-packages')
from vncdotool import api
client = api.connect('localhost::5900', timeout=30)
time.sleep(1.0)
client.captureScreen('/home/ondev/devos-vm/narrator-before.png')
client.mouseMove(30, 780)         # over the menu pill in the bottom bar
time.sleep(1.2)
client.captureScreen('/home/ondev/devos-vm/narrator-after.png')
client.disconnect()
print('NARRATOR-CAPTURED')
PY
    cp "$VM"/narrator-*.png "$OUT/" 2>/dev/null || true
    python3 - "$OUT/narrator-before.png" "$OUT/narrator-after.png" >> "$OUT/finalapps.log" 2>&1 <<'PY' || true
import sys
from PIL import Image
before = Image.open(sys.argv[1]).convert('RGB')
after = Image.open(sys.argv[2]).convert('RGB')
width, height = before.size
area = [(x, y) for y in range(6, 92) for x in range(width - 320, width - 12, 4)]
delta = sum(abs(sum(after.getpixel(point)) - sum(before.getpixel(point)))
            for point in area)
print('toast-region-delta=%d' % delta)
print('NARRATOR-TOAST-VISIBLE' if delta > 8000 else 'NARRATOR-TOAST-MISSING')
PY
else
    echo "[E] greeter never came back after narrator restart" >> "$OUT/finalapps.log"
fi

(echo "screendump $VM/final.ppm"; sleep 0.5) | timeout 6 socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1 || true
sleep 3
cp "$VM"/final.ppm "$OUT/" 2>/dev/null || true
pkill -9 qemu-system 2>/dev/null || true
pkill -f "http.server 8000" 2>/dev/null || true
echo "[4] done $(date +%H:%M:%S)" >> "$OUT/finalapps.log"
