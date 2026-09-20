#!/bin/sh
# Run from the Windows checkout using WSL; all build files stay in Linux storage.
set -eu
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
workspace=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
base=${DEVOS_BUILD_DIR:-"$HOME/src/dev-os-build"}
mkdir -p "$base/downloads" "$base/project"
cd "$base/downloads"
archive=buildroot-2026.08.tar.xz
if [ ! -f "$archive" ]; then
    curl -fL --retry 3 -o "$archive.part" "https://buildroot.org/downloads/$archive"
    mv "$archive.part" "$archive"
fi
printf '%s  %s\n' 87aaca4164ea9d5c8085854953018263f7963f07c22e73a2a2185cc98c581c34 "$archive" | sha256sum -c -
if [ ! -d "$base/buildroot-2026.08" ]; then
    tar -xf "$archive" -C "$base"
fi
if [ "$workspace" != "$base/project" ]; then
    rsync -a --exclude=out --exclude=__pycache__ --exclude=.git "$workspace/" "$base/project/"
fi
cd "$base/project"
chmod +x scripts/*.sh
DEVOS_TEST_VM=1 sh scripts/configure.sh "$base/buildroot-2026.08"
sh scripts/build.sh
