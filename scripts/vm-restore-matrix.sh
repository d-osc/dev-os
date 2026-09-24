#!/bin/sh
# Restore-mechanism matrix in ONE boot: minimize a live window, then try
# each deiconify path at protocol level and record what the WM accepts.
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
echo "[1] boot $(date +%H:%M:%S)" > "$OUT/restore-matrix.log"
nohup setsid qemu-system-x86_64 -M pc -enable-kvm -cpu host -m 1024 \
    -kernel "$SRC/bzImage" -drive file="$VM/disk.img",if=virtio,format=raw \
    -append "rootwait root=/dev/vda console=tty1 console=ttyS0 quiet" \
    -vga none -device virtio-vga -vnc :0 -usb -device usb-tablet \
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
[ -n "$up" ] || { echo "[!] NO GRAPHICS" >> "$OUT/restore-matrix.log"; exit 1; }
sleep 12
python3 "$SCRIPTS/vm-session-nopoweroff.py" \
    'mkdir -p /home/dev/.config/devos && touch /home/dev/.config/devos/wizard-done && chown -R dev:dev /home/dev/.config' \
    >> "$OUT/restore-matrix.log" 2>&1 || true
timeout 120 python3 "$SCRIPTS/vm-vnc-login-full.py" >> "$OUT/restore-matrix.log" 2>&1 || true
sleep 22

python3 "$SCRIPTS/vm-session-nopoweroff.py" \
    'su - dev -c "DISPLAY=:0 setsid dev-files >/dev/null 2>&1 &"; sleep 4' \
    'su - dev -c "DISPLAY=:0 dev-ctl windows"' \
    >> "$OUT/restore-matrix.log" 2>&1 || true
WID=$(grep -a "^[0-9a-f]* .iles" "$OUT/restore-matrix.log" | tail -1 | cut -d" " -f1)
echo "[2] files window: $WID" >> "$OUT/restore-matrix.log"
[ -n "$WID" ] || exit 1

step() {  # $1 label, rest = command
    label=$1; shift
    python3 "$SCRIPTS/vm-session-nopoweroff.py" "$@" >> "$OUT/restore-matrix.log" 2>&1 || true
    sleep 2
    python3 "$SCRIPTS/vm-session-nopoweroff.py" \
        "su - dev -c \"DISPLAY=:0 dev-ctl clients\"" >> "$OUT/restore-matrix.log" 2>&1 || true
    echo "== after $label" >> "$OUT/restore-matrix.log"
}

step baseline
step minimize "su - dev -c \"DISPLAY=:0 dev-ctl click 0x$WID 573 12\""
step activate "su - dev -c \"DISPLAY=:0 dev-ctl activate 0x$WID\""
step map "su - dev -c \"DISPLAY=:0 dev-ctl map 0x$WID\""
(echo "screendump $VM/matrix-end.ppm"; sleep 0.5) | timeout 6 socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1 || true
cp "$VM"/matrix-end.ppm "$OUT/" 2>/dev/null || true
pkill -9 qemu-system 2>/dev/null || true
echo "[3] done" >> "$OUT/restore-matrix.log"
