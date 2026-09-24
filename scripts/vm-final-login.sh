#!/bin/sh
# Definitive: guest-side auth check via a script file (no quoting), then
# the real GUI login, then capture whatever the screen shows.
set -eu
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
SRC=/home/ondev/src/dev-os-build/project/out/buildroot/images
VM=/home/ondev/devos-vm
OUT=/mnt/c/Users/ondev/Projects/dev-os/out/vm
mkdir -p "$VM" "$OUT"

pkill -9 qemu-system 2>/dev/null || true
sleep 1
cp --sparse=always "$SRC/rootfs.ext2" "$VM/disk.img"
rm -f "$VM"/*.sock "$VM"/*.ppm "$VM"/*.png "$VM"/qemu.log
echo "[1] boot $(date +%H:%M:%S)" > "$OUT/final-login.log"

nohup setsid qemu-system-x86_64 -M pc -enable-kvm -cpu host -m 1024 \
    -kernel "$VM/bzImage" \
    -drive file="$VM/disk.img",if=virtio,format=raw \
    -append "rootwait root=/dev/vda console=tty1 console=ttyS0 quiet" \
    -vga std -vnc :0 \
    -serial unix:"$VM/serial.sock",server,nowait \
    -monitor unix:"$VM/monitor.sock",server,nowait \
    > "$VM/qemu.log" 2>&1 < /dev/null &

for tick in $(seq 1 24); do
    sleep 10
    (echo "screendump $VM/w.ppm"; sleep 0.4) | timeout 6 socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1 || true
    sleep 2
    if [ -f "$VM/w.ppm" ] && python3 /mnt/c/Users/ondev/Projects/dev-os/scripts/vm-graphics-probe.py "$VM/w.ppm" 2>/dev/null; then
        echo "[2] graphics at $((tick*10))s" >> "$OUT/final-login.log"
        break
    fi
done
sleep 12

python3 /mnt/c/Users/ondev/Projects/dev-os/scripts/vm-final-login.py >> "$OUT/final-login.log" 2>&1 || true

sleep 22
(echo "screendump $VM/login-desktop.ppm"; sleep 0.5) | timeout 6 socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1 || true
sleep 8
(echo "screendump $VM/login-desktop2.ppm"; sleep 0.5) | timeout 6 socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1 || true
echo "[4] captured $(date +%H:%M:%S)" >> "$OUT/final-login.log"
cp "$VM"/g-*.png "$VM"/login-*.ppm "$OUT/" 2>/dev/null || true
pkill -9 qemu-system 2>/dev/null || true
echo "[5] done" >> "$OUT/final-login.log"
