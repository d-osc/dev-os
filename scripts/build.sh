#!/bin/sh
set -eu
# WSL imports Windows PATH entries with spaces, which Buildroot rejects.
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec make -C "$project/out/buildroot" BR2_JLEVEL="${DEVOS_BUILD_JOBS:-8}" "$@"
