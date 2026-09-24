#!/bin/sh
# Start the Dev OS desktop for hands-on use.
#
#   sh scripts/devos-run.sh            # desktop window (WSLg/SDL)
#   sh scripts/devos-run.sh --vnc      # headless, VNC on localhost:5900
#   sh scripts/devos-run.sh --fresh    # reset the disk to the built image
#
# The disk is a persistent copy at ~/devos-vm/disk.img: users you create,
# the wizard state and your files survive reboots. --fresh re-copies it
# from the build tree (that image is never written to directly).
set -eu
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

IMAGES=$HOME/src/dev-os-build/project/out/buildroot/images
DISK=$HOME/devos-vm/disk.img
mode_display="-display sdl,gl=off"
fresh=false
while [ "${1:-}" ]; do
    case "$1" in
    --vnc) mode_display="-display vnc=:0"; shift;;
    --fresh) fresh=true; shift;;
    *) echo "unknown option: $1" >&2; exit 1;;
    esac
done
[ -f "$IMAGES/bzImage" ] && [ -f "$IMAGES/rootfs.ext2" ] || {
    echo "built image not found under $IMAGES" >&2; exit 1; }

mkdir -p "$HOME/devos-vm"
if $fresh || [ ! -f "$DISK" ]; then
    echo "[devos] copying a fresh disk image..."
    cp --sparse=always "$IMAGES/rootfs.ext2" "$DISK"
fi

accel="-accel kvm"; [ -w /dev/kvm ] || accel="-accel tcg"
echo "[devos] booting — login: dev / 0000 (root / 0000 on the serial console)"
exec qemu-system-x86_64 -M pc $accel -cpu max -m 1024 \
    -kernel "$IMAGES/bzImage" \
    -drive file="$DISK",if=virtio,format=raw \
    -append "rootwait root=/dev/vda console=tty1 console=ttyS0 quiet" \
    -vga std -usb -device usb-tablet \
    -device virtio-net-pci,netdev=net0 -netdev user,id=net0 \
    -device intel-hda -device hda-duplex \
    $mode_display -serial mon:stdio \
    -monitor unix:$HOME/devos-vm/monitor.sock,server,nowait
