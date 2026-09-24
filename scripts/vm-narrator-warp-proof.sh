#!/bin/sh
# Warp the core pointer with an inline payload through the serial console
# and capture the narrator evidence: [narrator] console prints + a toast
# screendump taken within the 5s toast lifetime.
set -eu
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
VM=/home/ondev/devos-vm
OUT=/mnt/c/Users/ondev/Projects/dev-os/out/vm
SCRIPTS=/mnt/c/Users/ondev/Projects/dev-os/scripts

cat > /tmp/warp-payload.py <<'PYEOF'
import os
import sys
sys.path.insert(0, '/usr/lib/devos')
import ctypes as c
import dev_gui
toolkit = dev_gui.Toolkit()
warp = toolkit.x.XWarpPointer
warp.restype = None
warp.argtypes = [c.c_void_p, c.c_ulong, c.c_ulong, c.c_int, c.c_int,
                 c.c_uint, c.c_uint, c.c_int, c.c_int]
x, y = int(os.environ.get('WX', '0')), int(os.environ.get('WY', '0'))
warp(toolkit.display, 0, toolkit.root, 0, 0, 0, 0, x, y)
toolkit.api['flush'](toolkit.display)
print('WARPED-%d-%d' % (x, y))
PYEOF

B64=$(base64 -w0 /tmp/warp-payload.py)
CODE="import base64;exec(base64.b64decode('$B64'))"
runner() { # $1 = x, $2 = y
    printf 'su - dev -c "DISPLAY=:0 WX=%s WY=%s python3 -c \\"%s\\""' "$1" "$2" "$CODE"
}

( sleep 7; echo "screendump $VM/narr-warp-hover.ppm"; sleep 0.5 ) | timeout 12 socat - UNIX-CONNECT:"$VM/monitor.sock" >/dev/null 2>&1 &

python3 "$SCRIPTS/vm-session-nopoweroff.py" \
    "$(runner 30 780)" \
    "$(runner 200 780)" \
    'sleep 2' > "$OUT/narrator-warp.log" 2>&1 || true
wait

cp "$VM"/narr-warp-before.ppm "$VM"/narr-warp-hover.ppm "$OUT/" 2>/dev/null || true
grep -E "WARPED|narrator" "$OUT/narrator-warp.log" | head -6 || true
python3 - "$OUT/narr-warp-before.ppm" "$OUT/narr-warp-hover.ppm" 2>&1 <<'PY' || true
import sys
from PIL import Image
before = Image.open(sys.argv[1]).convert('RGB')
after = Image.open(sys.argv[2]).convert('RGB')
width, height = before.size
# Toasts paint on the bar surface: the card appears inside the bottom strip.
strip = [(x, y) for y in range(height - 42, height)
         for x in range(width - 320, width - 8, 2)]
delta = sum(abs(sum(after.getpixel(point)) - sum(before.getpixel(point)))
            for point in strip)
print('bar-strip-delta=%d' % delta)
print('NARRATOR-TOAST-VISIBLE' if delta > 8000 else 'NARRATOR-TOAST-MISSING')
PY
