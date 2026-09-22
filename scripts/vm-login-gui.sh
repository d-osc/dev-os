#!/bin/sh
# Boot to the greeter, then log in through the GUI: click-free typing via
# the QEMU monitor. Verifies the screen CHANGED after the password (the
# greeter disappears and the desktop shell takes over the same X server).
set -eu
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
SRC=/home/ondev/src/dev-os-build/project/out/buildroot/images
VM=/home/ondev/devos-vm
OUT=/mnt/c/Users/ondev/Projects/dev-os/out/vm
mkdir -p "$VM" "$OUT"

cp --sparse=always "$SRC/rootfs.ext2" "$VM/disk.img"
cp "$SRC/bzImage" "$VM/bzImage"
rm -f "$VM"/*.sock "$VM"/*.ppm "$VM"/serial.log
echo "[1] boot $(date +%H:%M:%S)" > "$OUT/login-run.log"

DISPLAY=:0 qemu-system-x86_64 -M pc -enable-kvm -cpu host -m 1024 \
    -kernel "$VM/bzImage" \
    -drive file="$VM/disk.img",if=virtio,format=raw \
    -append "rootwait root=/dev/vda console=tty1 console=ttyS0 quiet" \
    -vga std -display none \
    -serial file:"$VM/serial.log" \
    -monitor unix:"$VM/monitor.sock",server,nowait &
QEMU_PID=$!

shot() {
    echo "screendump $VM/$1.ppm" | socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1
    sleep 2
}
send() { for key in "$@"; do echo "sendkey $key" | socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1; sleep 0.18; done; }

for tick in $(seq 1 20); do
    sleep 10
    shot wait-$tick
    python3 /mnt/c/Users/ondev/Projects/dev-os/scripts/vm-graphics-probe.py "$VM/wait-$tick.ppm" && break
done
sleep 20
shot before
echo "[2] greeter ready $(date +%H:%M:%S)" >> "$OUT/login-run.log"

# Password for the prefilled 'dev' account, then Enter. spc deletes the
# field first in case a stray key landed in the user field earlier.
send spc spc spc ctrl-u
sleep 1
send shift-d e v tab
send y l 7 v x d 1 m shift-minus o 5 w 0 l c 5 q 0 j o ret
echo "[3] typed $(date +%H:%M:%S)" >> "$OUT/login-run.log"

for tick in $(seq 1 12); do
    sleep 10
    shot after-$tick
    if ! cmp -s "$VM/before.ppm" "$VM/after-$tick.ppm"; then
        echo "[4] screen changed at $((tick*10))s after login" >> "$OUT/login-run.log"
        sleep 8
        shot desktop
        break
    fi
done

cp "$VM"/*.ppm "$OUT/" 2>/dev/null || true
echo "[5] done $(date +%H:%M:%S)" >> "$OUT/login-run.log"
kill $QEMU_PID 2>/dev/null || true
