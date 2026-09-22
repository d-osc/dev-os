#!/bin/sh
# Copy the freshly built kernel + rootfs to the Windows-shared side so any
# WSL instance can boot them. Retries while the build tree is flapping.
set -eu
SRC=/home/ondev/src/devos-build/project/out/buildroot/images
DEST=/mnt/c/Users/ondev/Projects/dev-os/out/vm/images
mkdir -p "$DEST"
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    if [ -f "$SRC/bzImage" ] && [ -f "$SRC/rootfs.ext2" ]; then
        cp "$SRC/bzImage" "$DEST/bzImage"
        cp --sparse=always "$SRC/rootfs.ext2" "$DEST/rootfs.ext2"
        cp "$SRC/rootfs.tar.gz" "$DEST/rootfs.tar.gz" 2>/dev/null || true
        echo "EXPORTED on attempt $attempt" > "$DEST/status.txt"
        exit 0
    fi
    sleep 3
done
echo "TREE-NEVER-VISIBLE" > "$DEST/status.txt"
exit 1
