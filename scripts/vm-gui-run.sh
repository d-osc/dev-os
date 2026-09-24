#!/bin/sh
# Boot the built Dev OS desktop in QEMU inside ONE WSL session: serial goes
# to a file from the first second (nothing is lost to socket races), the
# screen is sampled every 30s until real graphics appear, then the login
# password is typed through the QEMU monitor and the desktop is captured.
set -eu
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
SRC=/home/ondev/src/dev-os-build/project/out/buildroot/images
VM=/home/ondev/devos-vm
OUT=/mnt/c/Users/ondev/Projects/dev-os/out/vm
mkdir -p "$VM" "$OUT"

test -f "$SRC/bzImage" && test -f "$SRC/rootfs.ext2"
cp --sparse=always "$SRC/rootfs.ext2" "$VM/disk.img"
cp "$SRC/bzImage" "$VM/bzImage"
rm -f "$VM"/*.sock "$VM"/*.ppm "$VM"/serial.log
echo "[1] disk ready $(date +%H:%M:%S)" > "$OUT/gui-run.log"

DISPLAY=:0 qemu-system-x86_64 -M pc -enable-kvm -cpu host -m 1024 \
    -kernel "$VM/bzImage" \
    -drive file="$VM/disk.img",if=virtio,format=raw \
    -append "rootwait root=/dev/vda console=tty1 console=ttyS0 quiet" \
    -vga std -display none \
    -serial file:"$VM/serial.log" \
    -monitor unix:"$VM/monitor.sock",server,nowait &
QEMU_PID=$!
echo "[2] qemu $QEMU_PID" >> "$OUT/gui-run.log"

shot() {
    echo "screendump $VM/$1.ppm" | socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1
    sleep 2
}

send() { for key in "$@"; do echo "sendkey $key" | socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1; sleep 0.15; done; }

first_gfx=""
for tick in $(seq 1 30); do
    sleep 30
    shot "tick-$tick"
    if python3 /mnt/c/Users/ondev/Projects/dev-os/scripts/vm-graphics-probe.py "$VM/tick-$tick.ppm"; then
        first_gfx="$tick"
        echo "[3] graphics at $((tick*30))s $(date +%H:%M:%S)" >> "$OUT/gui-run.log"
        break
    fi
    # keep the tail of the serial log to see what the VM is doing
    tail -c 2000 "$VM/serial.log" > "$OUT/serial-tail.txt" 2>/dev/null || true
done

if [ -n "$first_gfx" ]; then
    sleep 25
    shot greeter
    send y l 7 v x d 1 m shift-minus o 5 w 0 l c 5 q 0 j o ret
    sleep 20
    shot desktop
    sleep 12
    shot desktop2
    echo "[4] login sent; desktop captured" >> "$OUT/gui-run.log"
else
    cp "$VM/serial.log" "$OUT/serial-full.log" 2>/dev/null || true
    echo "[4] NO GRAPHICS within 15 minutes" >> "$OUT/gui-run.log"
fi

cp "$VM"/*.ppm "$OUT/" 2>/dev/null || true
echo "[5] done $(date +%H:%M:%S)" >> "$OUT/gui-run.log"
kill $QEMU_PID 2>/dev/null || true
