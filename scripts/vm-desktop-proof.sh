#!/bin/sh
# Boot to the greeter, then — over ONE serial session — swap the greeter
# for the desktop shell on the same X server and capture the taskbar.
set -eu
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
SRC=/home/ondev/src/dev-os-build/project/out/buildroot/images
VM=/home/ondev/devos-vm
OUT=/mnt/c/Users/ondev/Projects/dev-os/out/vm
mkdir -p "$VM" "$OUT"

cp --sparse=always "$SRC/rootfs.ext2" "$VM/disk.img"
cp "$SRC/bzImage" "$VM/bzImage"
rm -f "$VM"/*.sock "$VM"/*.ppm
echo "[1] boot $(date +%H:%M:%S)" > "$OUT/desktop-run.log"

DISPLAY=:0 qemu-system-x86_64 -M pc -enable-kvm -cpu host -m 1024 \
    -kernel "$VM/bzImage" \
    -drive file="$VM/disk.img",if=virtio,format=raw \
    -append "rootwait root=/dev/vda console=tty1 console=ttyS0 quiet" \
    -vga std -display none \
    -serial unix:"$VM/serial.sock",server,nowait \
    -monitor unix:"$VM/monitor.sock",server,nowait &
QEMU_PID=$!

shot() {
    echo "screendump $VM/$1.ppm" | socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1
    sleep 2
}

for tick in $(seq 1 20); do
    sleep 10
    shot wait-$tick
    python3 /mnt/c/Users/ondev/Projects/dev-os/scripts/vm-graphics-probe.py "$VM/wait-$tick.ppm" && break
done
sleep 15
shot greeter
echo "[2] greeter captured $(date +%H:%M:%S)" >> "$OUT/desktop-run.log"

echo "--- one-session login + swap" >> "$OUT/desktop-run.log"
python3 /mnt/c/Users/ondev/Projects/dev-os/scripts/vm-session-nopoweroff.py \
    'pkill -f dev-greeter; sleep 1; DISPLAY=:0 XAUTHORITY=/root/.Xauthority nohup /usr/bin/dev-shell > /tmp/shell.log 2>&1 & echo LAUNCHED' \
    'sleep 6; cat /tmp/shell.log; echo PIDS: $(pidof dev-shell) $(pidof Xorg)' \
    >> "$OUT/desktop-run.log" 2>&1 || true

sleep 12
shot desktop
sleep 8
shot desktop2
echo "[3] desktop captured $(date +%H:%M:%S)" >> "$OUT/desktop-run.log"

cp "$VM"/*.ppm "$OUT/" 2>/dev/null || true
echo "[4] done $(date +%H:%M:%S)" >> "$OUT/desktop-run.log"
kill $QEMU_PID 2>/dev/null || true
