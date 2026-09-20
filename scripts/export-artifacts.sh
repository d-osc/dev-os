#!/bin/sh
# Run from the Linux build copy after build/tests finish.
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
destination=${1:?Provide the absolute Windows checkout path as seen by WSL}
mkdir -p "$destination/out/images" "$destination/out/test-results"
cp "$project/out/buildroot/images/bzImage" "$project/out/buildroot/images/rootfs.ext4" "$destination/out/images/"
cp "$project/out/vm-credentials.json" "$destination/out/vm-credentials.json"
if [ -d "$project/out/test-results" ]; then
    cp "$project"/out/test-results/* "$destination/out/test-results/"
fi
cd "$destination/out/images"
sha256sum bzImage rootfs.ext4 > SHA256SUMS
