#!/bin/sh
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
images="$project/out/buildroot/images"
accel=tcg
if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then accel=kvm; fi
# Snapshot keeps the built image pristine; omit -snapshot for persistent testing.
exec qemu-system-x86_64 -accel "${DEVOS_ACCEL:-$accel}" -machine pc -m "${DEVOS_RAM:-512}" -smp 2 -nographic -snapshot \
  -kernel "$images/bzImage" \
  -drive "file=$images/rootfs.ext4,format=raw,if=virtio" \
  -append 'root=/dev/vda rw console=ttyS0' \
  -netdev user,id=net0 -device virtio-net-pci,netdev=net0
