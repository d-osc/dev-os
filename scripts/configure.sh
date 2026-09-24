#!/bin/sh
# Usage: sh scripts/configure.sh /absolute/path/to/buildroot-2026.08
set -eu
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
br=$(CDPATH= cd -- "${1:?Provide a Buildroot 2026.08 source directory}" && pwd)
case "$project:$br" in *' '*) echo 'Build paths must not contain spaces' >&2; exit 1;; esac
out="$project/out/buildroot"
make -C "$br" O="$out" BR2_EXTERNAL="$project/buildroot-external" qemu_x86_64_defconfig
cat >> "$out/.config" <<EOF
BR2_TARGET_GENERIC_HOSTNAME="dev-os"
BR2_TARGET_GENERIC_ISSUE="Welcome to Dev OS 0.1 (prototype)"
BR2_USE_WCHAR=y
BR2_PACKAGE_PYTHON3=y
BR2_PACKAGE_PYTHON3_ZLIB=y
BR2_PACKAGE_PYTHON3_PYEXPAT=y
BR2_PACKAGE_PYTHON_TUF=y
BR2_PACKAGE_BUSYBOX_SHOW_OTHERS=y
BR2_PACKAGE_BASH=y
BR2_PACKAGE_BUBBLEWRAP=y
BR2_PACKAGE_XORG7=y
BR2_PACKAGE_XLIB_LIBX11=y
BR2_PACKAGE_LIBGLIB2=y
BR2_PACKAGE_DBUS=y
BR2_PACKAGE_EUDEV=y
BR2_PACKAGE_LIBXCRYPT=y
BR2_PACKAGE_OPENBOX=y
BR2_PACKAGE_XTERM=y
BR2_PACKAGE_ALSA_LIB=y
BR2_PACKAGE_ALSA_UTILS=y
BR2_PACKAGE_ALSA_UTILS_AMIXER=y
BR2_PACKAGE_ALSA_UTILS_APLAY=y
BR2_PACKAGE_CONNMAN=y
BR2_PACKAGE_CONNMAN_ETHERNET=y
BR2_PACKAGE_CONNMAN_WIFI=y
BR2_PACKAGE_WPA_SUPPLICANT=y
BR2_PACKAGE_WPA_SUPPLICANT_NL80211=y
BR2_PACKAGE_WPA_SUPPLICANT_CLI=y
BR2_PACKAGE_IPROUTE2=y
BR2_PACKAGE_SUDO=y
BR2_PACKAGE_UTIL_LINUX=y
BR2_PACKAGE_UTIL_LINUX_BINARIES=y
BR2_PACKAGE_UTIL_LINUX_MOUNT=y
BR2_PACKAGE_DOSFSTOOLS=y
BR2_PACKAGE_DOSFSTOOLS_MKFS_FAT=y
BR2_PACKAGE_DOSFSTOOLS_FSCK_FAT=y
BR2_PACKAGE_E2FSPROGS=y
# Desktop stack: the default desktop mode boots X with dev-shell on tty1,
# so the GUI libraries, fonts and the X server belong in the main config.
# Modular Xorg (full server + separate drivers) needs a C++ toolchain;
# without it Buildroot falls back to Kdrive, which hides the drivers.
BR2_TOOLCHAIN_BUILDROOT_CXX=y
BR2_ROOTFS_DEVICE_CREATION_DYNAMIC_EUDEV=y
BR2_PACKAGE_CAIRO=y
BR2_PACKAGE_CAIRO_PNG=y
BR2_PACKAGE_FONTCONFIG=y
BR2_PACKAGE_JPEG=y
BR2_PACKAGE_DEJAVU=y
BR2_PACKAGE_DEJAVU_SANS=y
BR2_PACKAGE_XSERVER_XORG_SERVER=y
BR2_PACKAGE_XSERVER_XORG_SERVER_MODULAR=y
BR2_PACKAGE_XAPP_XINIT=y
BR2_PACKAGE_XDRIVER_XF86_VIDEO_FBDEV=y
BR2_PACKAGE_XDRIVER_XF86_INPUT_EVDEV=y
BR2_PACKAGE_XKEYBOARD_CONFIG=y
BR2_TARGET_GRUB2=y
BR2_TARGET_GRUB2_X86_64_EFI=y
BR2_TARGET_GRUB2_INSTALL_TOOLS=y
BR2_LINUX_KERNEL_CONFIG_FRAGMENT_FILES="$project/config/installer-linux.fragment"
BR2_TARGET_ROOTFS_TAR=y
BR2_TARGET_ROOTFS_TAR_GZIP=y
BR2_PACKAGE_BUSYBOX_CONFIG_FRAGMENT_FILES="$project/config/busybox.fragment"
BR2_ROOTFS_OVERLAY="$project/rootfs-overlay"
BR2_ROOTFS_POST_BUILD_SCRIPT="board/qemu/x86_64/post-build.sh $project/scripts/post-build.sh"
BR2_TARGET_ROOTFS_EXT2_4=y
BR2_TARGET_ROOTFS_EXT2_SIZE="2048M"
# BR2_PACKAGE_HOST_QEMU is not set
# BR2_PACKAGE_HOST_QEMU_SYSTEM_MODE is not set
# BR2_TARGET_GENERIC_GETTY_PORT is not set
BR2_TARGET_GENERIC_GETTY_PORT="ttyS0"
# BR2_TARGET_ENABLE_ROOT_LOGIN is not set
EOF
if [ "${DEVOS_WITH_NODE:-0}" = 1 ]; then
    # Node requires a C++ toolchain. Use a fresh build tree when enabling it.
    printf '\nBR2_TOOLCHAIN_BUILDROOT_CXX=y\nBR2_PACKAGE_NODEJS=y\n' >> "$out/.config"
fi
if [ "${DEVOS_WITH_RUST:-0}" = 1 ]; then
    # rustc + cargo on the target; a long build, hence opt-in like Node.
    printf '\nBR2_PACKAGE_RUST=y\n' >> "$out/.config"
fi
make -C "$br" O="$out" olddefconfig
for symbol in BR2_PACKAGE_CAIRO BR2_PACKAGE_FONTCONFIG BR2_PACKAGE_JPEG \
             BR2_PACKAGE_DEJAVU BR2_PACKAGE_DEJAVU_SANS \
             BR2_PACKAGE_XSERVER_XORG_SERVER BR2_PACKAGE_XAPP_XINIT \
             BR2_PACKAGE_XDRIVER_XF86_VIDEO_FBDEV \
             BR2_PACKAGE_XSERVER_XORG_SERVER_MODULAR \
             BR2_PACKAGE_OPENBOX BR2_PACKAGE_XTERM BR2_PACKAGE_ALSA_LIB \
             BR2_PACKAGE_CONNMAN BR2_PACKAGE_WPA_SUPPLICANT BR2_PACKAGE_IPROUTE2 \
             BR2_PACKAGE_EUDEV BR2_PACKAGE_LIBXCRYPT \
             BR2_PACKAGE_XDRIVER_XF86_INPUT_EVDEV; do
    grep -qx "$symbol=y" "$out/.config" || {
        echo "Desktop symbol $symbol was not selected by Buildroot" >&2
        exit 1
    }
done
if [ "${DEVOS_WITH_NODE:-0}" = 1 ]; then
    grep -qx 'BR2_TOOLCHAIN_BUILDROOT_CXX=y' "$out/.config" &&
    grep -qx 'BR2_PACKAGE_NODEJS=y' "$out/.config" || {
        echo 'Requested Node runtime was not selected by Buildroot' >&2
        exit 1
    }
fi
if [ "${DEVOS_WITH_RUST:-0}" = 1 ]; then
    grep -qx 'BR2_PACKAGE_RUST=y' "$out/.config" || {
        echo 'Requested Rust toolchain was not selected by Buildroot' >&2
        exit 1
    }
fi
if [ "${DEVOS_TEST_VM:-0}" = 1 ]; then
    python3 "$project/scripts/test-accounts.py" "$out/.config" "$project/out"
    make -C "$br" O="$out" olddefconfig
fi
if [ "${DEVOS_TEST_VM:-0}" = 1 ]; then
    printf '\nConfigured with unique local test-VM credentials.\n'
else
    printf '\nConfigured. Set users/passwords with make -C "%s" menuconfig before building.\n' "$out"
fi
printf 'Build: sh "%s/scripts/build.sh"\n' "$project"
