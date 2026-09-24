#!/bin/sh
# Greeter up -> screendump -> ONE sendkey -> screendump -> pixel diff:
# do keys from QEMU reach the X greeter at all?
set -eu
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
SRC=/home/ondev/src/dev-os-build/project/out/buildroot/images
VM=/home/ondev/devos-vm
OUT=/mnt/c/Users/ondev/Projects/dev-os/out/vm
mkdir -p "$VM" "$OUT"

cp --sparse=always "$SRC/rootfs.ext2" "$VM/disk.img"
cp "$SRC/bzImage" "$VM/bzImage"
rm -f "$VM"/*.sock "$VM"/*.ppm

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
    shot w
    python3 /mnt/c/Users/ondev/Projects/dev-os/scripts/vm-graphics-probe.py "$VM/w.ppm" && break
done
sleep 12
shot key-before
echo "sendkey d" | socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1
sleep 3
shot key-after
echo "sendkey x" | socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1
sleep 3
shot key-after2

python3 /mnt/c/Users/ondev/Projects/dev-os/scripts/vm-diff-ppm.py \
    "$VM/key-before.ppm" "$VM/key-after.ppm" "$VM/key-after2.ppm" \
    > "$OUT/keytest-result.txt" 2>&1 || true

cp "$VM"/key-*.ppm "$OUT/" 2>/dev/null || true
kill $QEMU_PID 2>/dev/null || true
