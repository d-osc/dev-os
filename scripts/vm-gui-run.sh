#!/bin/sh
# Boot Dev OS GUI in one WSL session and capture the desktop over time:
# X needs several minutes to settle in this VM, so we watch the screen.
set -eu
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
SRC=/mnt/c/Users/ondev/Projects/dev-os/out/vm/images
VM=/home/ondev/devos-vm
OUT=/mnt/c/Users/ondev/Projects/dev-os/out/vm
mkdir -p "$VM" "$OUT"

cp --sparse=always "$SRC/rootfs.ext2" "$VM/disk.img"
cp "$SRC/bzImage" "$VM/bzImage"
rm -f "$VM"/*.sock "$VM"/*.ppm
echo "[1] disk ready" > "$OUT/gui-run.log"

DISPLAY=:0 qemu-system-x86_64 -M pc -enable-kvm -cpu host -m 1024 \
    -kernel "$VM/bzImage" \
    -drive file="$VM/disk.img",if=virtio,format=raw \
    -append "rootwait root=/dev/vda console=tty1 console=ttyS0" \
    -vga std -display none \
    -serial unix:"$VM/serial.sock",server,nowait \
    -monitor unix:"$VM/monitor.sock",server,nowait &
QEMU_PID=$!
echo "[2] qemu $QEMU_PID" >> "$OUT/gui-run.log"

shot() {
    echo "screendump $VM/$1.ppm" | socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1
    sleep 2
}

send() { for key in "$@"; do echo "sendkey $key" | socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1; sleep 0.15; done; }

# Watch every 30s for up to 12 minutes; remember when graphics first appear.
first_gfx=""
for tick in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24; do
    sleep 30
    shot "tick-$tick"
    if python3 /mnt/c/Users/ondev/Projects/dev-os/scripts/vm-graphics-probe.py "$VM/tick-$tick.ppm"; then
        first_gfx="$tick"
        echo "[3] graphics at tick $tick ($((tick*30))s)" >> "$OUT/gui-run.log"
        break
    fi
done

if [ -n "$first_gfx" ]; then
    sleep 20
    shot greeter
    send y l 7 v x d 1 m shift-minus o 5 w 0 l c 5 q 0 j o ret
    sleep 15
    shot desktop
    sleep 10
    shot desktop2
    echo "[4] login sent; desktop captured" >> "$OUT/gui-run.log"
else
    python3 /mnt/c/Users/ondev/Projects/dev-os/scripts/vm-console.py --keep \
        'ps w | grep -vE "grep|\[" | tail -8' \
        'grep -E "\(EE\)" /var/log/Xorg.0.log | head -5' \
        >> "$OUT/gui-run.log" 2>&1 || true
    echo "[4] NO GRAPHICS within 12 minutes" >> "$OUT/gui-run.log"
fi

cp "$VM"/*.ppm "$OUT/" 2>/dev/null || true
echo "[5] done" >> "$OUT/gui-run.log"
kill $QEMU_PID 2>/dev/null || true
