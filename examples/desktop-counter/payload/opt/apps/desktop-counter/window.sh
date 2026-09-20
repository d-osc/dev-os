# This script is interpreted by the manifest-selected Bash runtime.
set -euo pipefail
exec /usr/bin/python3 -E -s "$DEVOS_APP_DIR/window.py" "$@"
