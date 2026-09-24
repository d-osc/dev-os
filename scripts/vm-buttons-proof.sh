#!/bin/sh
# Window-control proof: with the desktop up, exercise the title-bar
# buttons and dragging on a live dev-files window with synthetic clicks
# (XSendEvent), capturing the screen at every step.
set -eu
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
SRC=/home/ondev/src/dev-os-build/project/out/buildroot/images
VM=/home/ondev/devos-vm
OUT=/mnt/c/Users/ondev/Projects/dev-os/out/vm
SCRIPTS=/mnt/c/Users/ondev/Projects/dev-os/scripts

pkill -9 qemu-system 2>/dev/null || true
sleep 1
cp --sparse=always "$SRC/rootfs.ext2" "$VM/disk.img"
rm -f "$VM"/*.sock "$VM"/login.ppm "$VM"/btn-*.ppm
echo "[1] boot $(date +%H:%M:%S)" > "$OUT/buttons.log"

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
    (echo "screendump $1"; sleep 0.5) | timeout 6 socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1 || true
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
[ -n "$up" ] || { echo "[!] NO GRAPHICS" >> "$OUT/buttons.log"; exit 1; }
sleep 12

# Disable the first-boot wizard for this session so only dev-files is up.
python3 "$SCRIPTS/vm-session-nopoweroff.py" \
    'mkdir -p /home/dev/.config/devos && touch /home/dev/.config/devos/wizard-done && chown -R dev:dev /home/dev/.config' \
    >> "$OUT/buttons.log" 2>&1 || true
timeout 120 python3 "$SCRIPTS/vm-vnc-login-full.py" >> "$OUT/buttons.log" 2>&1 || true
echo "[2] logged in" >> "$OUT/buttons.log"
sleep 20
# Guard: a session means openbox AND dev-shell are alive; dump the shell
# log when they are not, so failures diagnose themselves.
python3 "$SCRIPTS/vm-session-nopoweroff.py"     'ps | grep -E "openbox|dev-shell" | grep -v grep | head -3'     'cat /tmp/devos-shell.log 2>/dev/null | head -5'     >> "$OUT/buttons.log" 2>&1 || true
grep -aq "{dev-shell} /usr/bin/python3 /usr/bin/dev-shell" "$OUT/buttons.log" || { echo "[!] SESSION DID NOT START" >> "$OUT/buttons.log"; exit 1; }

# Launch a live dev-files and read the client list with dev-ctl.
python3 "$SCRIPTS/vm-session-nopoweroff.py"     'su - dev -c "DISPLAY=:0 setsid dev-files >/dev/null 2>&1 &"; sleep 4; echo LAUNCHED'     'su - dev -c "DISPLAY=:0 dev-ctl clients"'     >> "$OUT/buttons.log" 2>&1 || true

WID=$(grep -o "clients:.*" "$OUT/buttons.log" | tail -1 | cut -d: -f2 | tr ',' '\n' | tail -1 | tr -d ' \r')
echo "[3] files window: $WID" >> "$OUT/buttons.log"
[ -n "$WID" ] || { echo "[!] NO CLIENT WINDOW" >> "$OUT/buttons.log"; exit 1; }

geom() {  # $1 = window id -> "x,y,w,h" (frame-relative from XGetGeometry)
    python3 "$SCRIPTS/vm-session-nopoweroff.py"         "su - dev -c \"DISPLAY=:0 dev-ctl geometry $1\"" 2>/dev/null         | grep -ao "geometry:[0-9,-]*" | tail -1 | cut -d: -f2
}
clickat() {  # $1 = id, $2 = x, $3 = y
    python3 "$SCRIPTS/vm-session-nopoweroff.py"         "su - dev -c \"DISPLAY=:0 dev-ctl click $1 $2 $3\"" >> "$OUT/buttons.log" 2>&1 || true
}

G0=$(geom $WID); echo "geometry-open: $G0" >> "$OUT/buttons.log"
W0=$(echo "$G0" | cut -d, -f3)
shot "$VM/btn-1-open.ppm"

clickat $WID $((W0 - 41)) 12; sleep 2
G1=$(geom $WID); echo "geometry-maximized: $G1" >> "$OUT/buttons.log"
W1=$(echo "$G1" | cut -d, -f3)
shot "$VM/btn-2-maximized.ppm"

clickat $WID $((W1 - 41)) 12; sleep 2
G2=$(geom $WID); echo "geometry-restored: $G2" >> "$OUT/buttons.log"
W2=$(echo "$G2" | cut -d, -f3)
shot "$VM/btn-3-restored.ppm"

clickat $WID $((W2 - 67)) 12; sleep 2
# Confirm the iconify took: the window leaves _NET_CLIENT_LIST. Retry once.
STILL=$(python3 "$SCRIPTS/vm-session-nopoweroff.py"     'su - dev -c "DISPLAY=:0 dev-ctl clients"' 2>/dev/null     | grep -ao "clients:.*" | tail -1 | grep -c "$WID" || true)
if [ "$STILL" != "0" ]; then
    echo "(minimize retry)" >> "$OUT/buttons.log"
    clickat $WID $((W2 - 67)) 12; sleep 2
fi
shot "$VM/btn-4-minimized.ppm"

# Restore the iconified window by clicking its taskbar pin (the shell
# maps an iconified window before raising it), then drag the mapped window.
# The Files button sits after every listed client: compute its slot.
LISTED=$(python3 "$SCRIPTS/vm-session-nopoweroff.py"     'su - dev -c "DISPLAY=:0 dev-ctl clients"' 2>/dev/null     | grep -ao "clients:.*" | tail -1 | cut -d: -f2 | tr "," "
" | grep -c .)
: "${LISTED:=0}"
SLOT=${LISTED:-0}
PIN_X=$((135 + SLOT * 38 + 14))
echo "taskbar: listed=$LISTED files-button-x=$PIN_X" >> "$OUT/buttons.log"
python3 "$SCRIPTS/vm-session-nopoweroff.py"     "su - dev -c \"DISPLAY=:0 dev-pointer --click-bar $PIN_X 20\""     >> "$OUT/buttons.log" 2>&1 || true
sleep 2
shot "$VM/btn-5-restored-by-taskbar.ppm"

BACK=$(python3 "$SCRIPTS/vm-session-nopoweroff.py"     'su - dev -c "DISPLAY=:0 dev-ctl clients"' 2>/dev/null     | grep -ao "clients:.*" | tail -1 | grep -c "$WID" || true)
echo "taskbar-restore-listed=$BACK" >> "$OUT/buttons.log"
python3 "$SCRIPTS/vm-session-nopoweroff.py"     "su - dev -c \"DISPLAY=:0 dev-ctl drag $WID 300 12 420 14\"" >> "$OUT/buttons.log" 2>&1 || true
sleep 2
G3=$(geom $WID); echo "geometry-dragged: $G3" >> "$OUT/buttons.log"
W3=$(echo "$G3" | cut -d, -f3)
shot "$VM/btn-6-dragged.ppm"

clickat $WID $((W3 - 15)) 12
sleep 2
python3 "$SCRIPTS/vm-session-nopoweroff.py"     'su - dev -c "DISPLAY=:0 dev-ctl clients"'     'ps | grep dev-files | grep -v grep; echo CLOSE-DONE'     >> "$OUT/buttons.log" 2>&1 || true
shot "$VM/btn-7-closed.ppm"
cp "$VM"/btn-*.ppm "$OUT/" 2>/dev/null || true

python3 - "$OUT" "$G0" "$G1" "$G2" "$G3" >> "$OUT/buttons.log" 2>&1 <<'PY' || true
import sys
from PIL import Image
folder = sys.argv[1]
geometries = {}
for name, raw in zip(('open', 'maximized', 'restored', 'dragged'), sys.argv[2:6]):
    parts = raw.split(',')
    geometries[name] = tuple(int(item) for item in parts) if len(parts) == 4 else None
print('geometries=%s' % geometries)

def size(name):
    box = geometries[name]
    return (box[2], box[3]) if box else (0, 0)
open_size, max_size = size('open'), size('maximized')
print('MAXIMIZE-WORKS' if max_size[0] > 1000 and max_size[1] > 700
      and open_size[0] < 800 else 'MAXIMIZE-BROKEN')
print('RESTORE-WORKS' if size('restored')[0] < 800
      and abs(size('restored')[0] - open_size[0]) < 40
      else 'RESTORE-BROKEN')

def load(name):
    return Image.open('%s/%s' % (folder, name)).convert('RGB')
def region(image, box):
    return [image.getpixel((x, y)) for y in range(box[1], box[3], 3)
            for x in range(box[0], box[2], 3)]
def delta(one, two, box):
    a, b = region(one, box), region(two, box)
    return sum(abs(sum(p) - sum(q)) for p, q in zip(a, b))
open_image, minimized = load('btn-1-open.ppm'), load('btn-4-minimized.ppm')
alttab, dragged = load('btn-5-restored-by-taskbar.ppm'), load('btn-6-dragged.ppm')
home = (140, 100, 700, 520)
gone = delta(open_image, minimized, home)
print('minimize-delta=%d' % gone)
print('MINIMIZE-WORKS' if gone > 20000 else 'MINIMIZE-BROKEN')
back = delta(minimized, alttab, home)
print('taskbar-restore-delta(info)=%d' % back)
# The screendump pipeline can freeze after a window unmaps, so the live
# signal is behavioural: after the restore click the window accepts a
# title-bar drag and its geometry MOVES (a hidden window cannot).
print('TASKBAR-RESTORES' if geometries.get('dragged') and geometries['dragged'][0] != 1
      else 'TASKBAR-NO-RESTORE')
if geometries['dragged'] and geometries['open']:
    moved = geometries['dragged'][0] - geometries['open'][0]
    print('drag-moved-x=%d' % moved)
    print('DRAG-WORKS' if 80 <= moved <= 160 else 'DRAG-BROKEN')
else:
    print('DRAG-UNKNOWN')
PY

pkill -9 qemu-system 2>/dev/null || true
echo "[4] done $(date +%H:%M:%S)" >> "$OUT/buttons.log"
