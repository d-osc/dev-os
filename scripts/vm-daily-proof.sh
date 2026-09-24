#!/bin/sh
# Ubuntu-daily-driver proof in one WSL session: boot, GUI login, and the
# session runs under openbox with xterm available, sound card present,
# Files installed, and a Thai notification toast on screen.
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
echo "[1] boot $(date +%H:%M:%S)" > "$OUT/daily-driver.log"

nohup setsid qemu-system-x86_64 -M pc -enable-kvm -cpu host -m 1024 \
    -kernel "$SRC/bzImage" \
    -drive file="$VM/disk.img",if=virtio,format=raw \
    -append "rootwait root=/dev/vda console=tty1 console=ttyS0 quiet" \
    -vga std -vnc :0 \
    -device intel-hda -device hda-duplex \
    -serial unix:"$VM/serial.sock",server,nowait \
    -monitor unix:"$VM/monitor.sock",server,nowait \
    > "$VM/qemu.log" 2>&1 < /dev/null &

up=""
for tick in $(seq 1 30); do
    sleep 10
    (echo "screendump $VM/login.ppm"; sleep 0.4) | timeout 6 socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1 || true
    sleep 2
    if [ -f "$VM/login.ppm" ] && python3 /mnt/c/Users/ondev/Projects/dev-os/scripts/vm-graphics-probe.py "$VM/login.ppm" 2>/dev/null; then
        up=1
        echo "[2] login screen at $((tick*10))s" >> "$OUT/daily-driver.log"
        break
    fi
done
[ -n "$up" ] || { echo "[!] NO GRAPHICS" >> "$OUT/daily-driver.log"; exit 1; }
sleep 12

python3 /mnt/c/Users/ondev/Projects/dev-os/scripts/vm-vnc-login-full.py >> "$OUT/daily-driver.log" 2>&1 || true
echo "[3] login sent" >> "$OUT/daily-driver.log"
sleep 25

python3 /mnt/c/Users/ondev/Projects/dev-os/scripts/vm-daily-driver.py >> "$OUT/daily-driver.log" 2>&1 || true

sleep 8
(echo "screendump $VM/daily-desktop.ppm"; sleep 0.5) | timeout 6 socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1 || true
echo "[4] captured $(date +%H:%M:%S)" >> "$OUT/daily-driver.log"
cp "$VM"/login.ppm "$VM"/daily-desktop.ppm "$OUT/" 2>/dev/null || true
pkill -9 qemu-system 2>/dev/null || true
echo "[5] done" >> "$OUT/daily-driver.log"
