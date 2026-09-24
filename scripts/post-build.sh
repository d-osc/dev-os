#!/bin/sh
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
target=${1:?Target root is required}
install -D -m 0755 "$project/tools/dev.py" "$target/usr/bin/dev"
install -D -m 0755 "$project/tools/dev_shell.py" "$target/usr/bin/dev-shell"
install -D -m 0755 "$project/rootfs-overlay/etc/init.d/S35dev-recover" "$target/etc/init.d/S35dev-recover"
install -D -m 0644 "$project/tools/dev_runtime.py" "$target/usr/lib/devos/dev_runtime.py"
install -D -m 0644 "$project/tools/dev_repository.py" "$target/usr/lib/devos/dev_repository.py"
install -D -m 0644 "$project/tools/dev_compat.py" "$target/usr/lib/devos/dev_compat.py"
install -D -m 0644 "$project/tools/dev_plan.py" "$target/usr/lib/devos/dev_plan.py"
install -D -m 0644 "$project/tools/dev_boot.py" "$target/usr/lib/devos/dev_boot.py"
install -D -m 0644 "$project/tools/dev_system_release.py" "$target/usr/lib/devos/dev_system_release.py"
install -D -m 0644 "$project/tools/dev_rootfs.py" "$target/usr/lib/devos/dev_rootfs.py"
install -D -m 0644 "$project/tools/dev_slots.py" "$target/usr/lib/devos/dev_slots.py"
install -D -m 0644 "$project/tools/dev_config.py" "$target/usr/lib/devos/dev_config.py"
install -D -m 0644 "$project/tools/dev_preserve.py" "$target/usr/lib/devos/dev_preserve.py"
install -D -m 0644 "$project/tools/dev_deploy.py" "$target/usr/lib/devos/dev_deploy.py"
install -D -m 0644 "$project/tools/dev_gui.py" "$target/usr/lib/devos/dev_gui.py"
install -D -m 0644 "$project/tools/dev_theme.py" "$target/usr/lib/devos/dev_theme.py"
install -D -m 0644 "$project/tools/dev_settings.py" "$target/usr/lib/devos/dev_settings.py"
install -D -m 0644 "$project/tools/dev_background.py" "$target/usr/lib/devos/dev_background.py"
install -D -m 0644 "$project/tools/dev_extensions.py" "$target/usr/lib/devos/dev_extensions.py"
install -D -m 0644 "$project/tools/ext-runner.js" "$target/usr/lib/devos/ext-runner.js"
install -D -m 0644 "$project/examples/extensions/hello-js/manifest.json" "$target/usr/share/devos/extensions/devos.hello-js/manifest.json"
install -D -m 0644 "$project/examples/extensions/hello-js/extension.js" "$target/usr/share/devos/extensions/devos.hello-js/extension.js"
install -D -m 0644 "$project/config/settings.json" "$target/etc/devos/settings.json"
printf 'desktop\n' > "$target/etc/devos/mode"
install -D -m 0755 "$project/scripts/devos-desktop-boot" "$target/usr/bin/devos-desktop-boot"
install -D -m 0755 "$project/tools/dev_greeter.py" "$target/usr/bin/dev-greeter"
install -D -m 0755 "$project/scripts/devos-session" "$target/usr/bin/devos-session"
install -D -m 0755 "$project/tools/dev_files.py" "$target/usr/bin/dev-files"
install -D -m 0755 "$project/tools/dev_edit.py" "$target/usr/bin/dev-edit"
install -D -m 0755 "$project/tools/dev_web.py" "$target/usr/bin/dev-web"
install -D -m 0755 "$project/tools/dev_music.py" "$target/usr/bin/dev-music"
install -D -m 0755 "$project/tools/dev_pointer.py" "$target/usr/bin/dev-pointer"
install -D -m 0755 "$project/tools/dev_view.py" "$target/usr/bin/dev-view"
install -D -m 0755 "$project/tools/dev_wizard.py" "$target/usr/bin/dev-wizard"
install -D -m 0644 "$project/tools/dev_admin.py" "$target/usr/lib/devos/dev_admin.py"
mkdir -p "$target/etc/skel/Music" "$target/etc/skel/Pictures"
# A deterministic sample picture so View has something to show first boot.
python3 - "$target/etc/skel/Pictures/dev-os.png" <<'PY'
import struct, sys, zlib
width, height = 192, 128
rows = bytearray()
for y in range(height):
    rows.append(0)
    for x in range(width):
        rows += bytes(((x * 255) // width,
                       (y * 255) // height,
                       128 if (x // 16 + y // 16) % 2 else 90))
def chunk(tag, data):
    return struct.pack('>I', len(data)) + tag + data \
        + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)
png = b'\x89PNG\r\n\x1a\n'
png += chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
png += chunk(b'IDAT', zlib.compress(bytes(rows), 9))
png += chunk(b'IEND', b'')
open(sys.argv[1], 'wb').write(png)
PY
install -D -m 0755 "$project/scripts/dev-notify" "$target/usr/bin/dev-notify"
mkdir -p "$target/etc/skel/Music"
python3 - "$target/etc/skel/Music/chime.wav" <<'PY'
import math, struct, sys, wave
with wave.open(sys.argv[1], 'wb') as out:
    out.setnchannels(1)
    out.setsampwidth(2)
    out.setframerate(44100)
    frames = bytearray()
    for index in range(17640):
        fade = min(1.0, (17640 - index) / 4410.0)
        sample = int(24000 * fade * math.sin(index * 440.0 * 2 * math.pi / 44100.0))
        frames += struct.pack('<h', sample)
    out.writeframes(bytes(frames))
PY
# The xorg-server package ships S40xorg, which pre-starts "Xorg :0.0" at
# boot; the desktop session must own the server instead (xinit per tty1),
# otherwise xinit collides with the already-active display and respawns.
rm -f "$target/etc/init.d/S40xorg"
install -D -m 0644 "$project/examples/greeter-extensions/welcome/manifest.json" "$target/usr/share/devos/greeter-extensions/devos.greeter-welcome/manifest.json"
install -D -m 0644 "$project/examples/greeter-extensions/welcome/extension.py" "$target/usr/share/devos/greeter-extensions/devos.greeter-welcome/extension.py"
touch "$target/usr/share/devos/greeter-extensions/devos.greeter-welcome/.disabled"
# tty1 runs the desktop/server session; serial consoles keep their getty.
sed -i '/^tty1::/d' "$target/etc/inittab"
printf 'tty1::respawn:/usr/bin/devos-desktop-boot\n' >> "$target/etc/inittab"
install -D -m 0644 "$project/examples/extensions/battery/manifest.json" "$target/usr/share/devos/extensions/devos.battery/manifest.json"
install -D -m 0644 "$project/examples/extensions/battery/extension.py" "$target/usr/share/devos/extensions/devos.battery/extension.py"
install -D -m 0644 "$project/examples/extensions/theme-switch/manifest.json" "$target/usr/share/devos/extensions/devos.theme-switch/manifest.json"
install -D -m 0644 "$project/examples/extensions/theme-switch/extension.py" "$target/usr/share/devos/extensions/devos.theme-switch/extension.py"
install -D -m 0644 "$project/examples/extensions/dashboard/manifest.json" "$target/usr/share/devos/extensions/devos.dashboard/manifest.json"
install -D -m 0644 "$project/examples/extensions/dashboard/extension.py" "$target/usr/share/devos/extensions/devos.dashboard/extension.py"
install -D -m 0644 "$project/themes/dev-dark.json" "$target/usr/share/devos/themes/dev-dark.json"
install -D -m 0644 "$project/themes/terminal-amber.json" "$target/usr/share/devos/themes/terminal-amber.json"
install -D -m 0644 "$project/themes/high-contrast.json" "$target/usr/share/devos/themes/high-contrast.json"
install -D -m 0755 "$project/tools/dev_notifications.py" "$target/usr/lib/devos/dev_notifications.py"
install -D -m 0755 "$project/installer/devos-install.py" "$target/usr/sbin/devos-install"
install -D -m 0755 "$project/tools/memory-probe.py" "$target/usr/lib/devos/memory-probe.py"
install -D -m 0440 "$project/config/sudoers" "$target/etc/sudoers"
install -D -m 0644 "$project/rootfs-overlay/etc/os-release" "$target/usr/lib/os-release"
mkdir -p "$target/var/lib/dev"
python3 "$project/scripts/generate-platform.py" "$target" --build-output "$project/out/buildroot"
python3 "$project/tools/dev.py" build "$project/examples/hello" "$target/opt/hello-0.1.0.dpk"
