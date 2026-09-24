#!/bin/sh
# Network proof: boot with connman, wait for DHCP on eth0, and read the
# live address from inside the guest.
set -eu
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
SRC=/home/ondev/src/dev-os-build/project/out/buildroot/images
VM=/home/ondev/devos-vm
OUT=/mnt/c/Users/ondev/Projects/dev-os/out/vm
mkdir -p "$VM" "$OUT"

pkill -9 qemu-system 2>/dev/null || true
sleep 1
cp --sparse=always "$SRC/rootfs.ext2" "$VM/disk.img"
rm -f "$VM"/*.sock "$VM"/*.ppm
echo "[1] boot $(date +%H:%M:%S)" > "$OUT/network.log"

nohup setsid qemu-system-x86_64 -M pc -enable-kvm -cpu host -m 1024 \
    -kernel "$SRC/bzImage" \
    -drive file="$VM/disk.img",if=virtio,format=raw \
    -append "rootwait root=/dev/vda console=tty1 console=ttyS0 quiet" \
    -vga std -vnc :0 -device intel-hda -device hda-duplex \
    -device virtio-net-pci,netdev=net0 -netdev user,id=net0 \
    -serial unix:"$VM/serial.sock",server,nowait \
    -monitor unix:"$VM/monitor.sock",server,nowait \
    > "$VM/qemu.log" 2>&1 < /dev/null &
echo "[2] qemu up" >> "$OUT/network.log"

up=""
for tick in $(seq 1 30); do
    sleep 10
    (echo "screendump $VM/login.ppm"; sleep 0.4) | timeout 6 socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1 || true
    sleep 2
    if [ -f "$VM/login.ppm" ] && python3 /mnt/c/Users/ondev/Projects/dev-os/scripts/vm-graphics-probe.py "$VM/login.ppm" 2>/dev/null; then
        up=1
        break
    fi
done
[ -n "$up" ] || { echo "[!] NO GRAPHICS" >> "$OUT/network.log"; exit 1; }
sleep 25

python3 /mnt/c/Users/ondev/Projects/dev-os/scripts/vm-session-nopoweroff.py \
    'ip -4 addr show scope global' \
    'connmanctl state 2>&1 | head -3' \
    'connmanctl services 2>&1 | head -3' \
    'pidof connmand' \
    >> "$OUT/network.log" 2>&1 || true
echo "[3] checked" >> "$OUT/network.log"
pkill -9 qemu-system 2>/dev/null || true
echo "[4] done" >> "$OUT/network.log"
