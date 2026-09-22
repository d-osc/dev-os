#!/bin/sh
# Boot the built Dev OS desktop in QEMU: greeter on tty1, log in and the
# desktop shell starts. Defaults to the WSL build tree; pass an images
# directory to use another one (must contain bzImage and rootfs.ext4).
#
#   sh scripts/run-gui-vm.sh                     # window on this display
#   sh scripts/run-gui-vm.sh --vnc               # headless on VNC :0
#   sh scripts/run-gui-vm.sh --serial            # console only (no GUI)
set -eu

images=""
mode_window=true
mode_vnc=false
mode_serial=false
while [ "$1" ]; do
    case "$1" in
    --vnc) mode_window=false; mode_vnc=true; shift;;
    --serial) mode_window=false; mode_serial=true; shift;;
    --images) images=$2; shift 2;;
    *) echo "unknown option: $1" >&2; exit 1;;
    esac
done
[ -n "$images" ] || images="$HOME/src/dev-os-build/project/out/buildroot/images"
for needed in bzImage rootfs.ext4; do
    [ -f "$images/$needed" ] || { echo "missing $images/$needed" >&2; exit 1; }
done

accel="-accel kvm" ; [ -w /dev/kvm ] || accel="-accel tcg"
if $mode_window; then
    display="-display sdl,gl=off"
elif $mode_vnc; then
    display="-display vnc=:0"
else
    display="-nographic"
fi

mkdir -p /tmp/devos-vm
exec qemu-system-x86_64 -M pc $accel -cpu max -m 1024 \
    -kernel "$images/bzImage" \
    -drive file="$images/rootfs.ext4",if=virtio,format=raw \
    -append "rootwait root=/dev/vda console=tty1 console=ttyS0" \
    -vga std -device virtio-net-pci,netdev=net0 -netdev user,id=net0 \
    $display -serial mon:stdio \
    -monitor unix:/tmp/devos-vm/monitor.sock,server,nowait
