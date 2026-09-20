#!/bin/sh
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
destination=${1:?Provide the absolute Windows checkout path as seen by WSL}
mkdir -p "$destination/out/installer" "$destination/out/installer-tests"
cp "$project"/out/installer/*.iso "$project"/out/installer/SHA256SUMS \
   "$project"/out/installer/payload-manifest.json "$destination/out/installer/"
for kind in virtio nvme sata usb; do
    source="$project/out/installer-tests/$kind"
    if [ -f "$source/result.json" ]; then
        mkdir -p "$destination/out/installer-tests/$kind"
        cp "$source/result.json" "$source"/*.log "$destination/out/installer-tests/$kind/"
        if [ -f "$source/setup-screen.png" ]; then
            cp "$source/setup-screen.png" "$destination/out/installer-tests/$kind/"
        fi
    fi
done
