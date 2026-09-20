# Build and test Dev OS on this Windows machine

The source checkout is `C:\Users\ondev\Projects\dev-os`. Compilation takes place in Ubuntu WSL at `/home/ondev/src/dev-os-build/project`, so Linux permissions and filesystem performance are preserved. The Buildroot source is in `/home/ondev/src/dev-os-build/buildroot-2026.08`.

## First build

Install host prerequisites in Ubuntu WSL if they are missing:

```sh
sudo apt-get update
sudo apt-get install build-essential bc bison flex cpio rsync unzip wget curl file \
    libncurses-dev libelf-dev libssl-dev python3 python3-pexpect qemu-system-x86
```

Using `apt` here prepares the Ubuntu **build host**. Dev OS itself uses `dev` for its prototype packages.

From PowerShell at the Windows checkout:

```powershell
wsl -d Ubuntu -- sh /mnt/c/Users/ondev/Projects/dev-os/scripts/bootstrap-wsl.sh
```

This downloads the pinned Buildroot 2026.08 archive, checks SHA-256, copies the source into Linux storage, configures the test VM, and builds it. The pinned archive checksum was matched against the signed release message using the release key served by buildroot.org. The fingerprint used was `AB07D806D2CE741FB886EE50B025BA8B59C36319`.

The default build parallelism is eight compiler jobs; set `DEVOS_BUILD_JOBS=2` on a host with less available RAM. The script excludes the Windows PATH entries that Buildroot rejects.

**Rerunning bootstrap resets Buildroot configuration.** To continue an interrupted build or rebuild without resetting configuration, run this inside Ubuntu WSL:

```sh
cd ~/src/dev-os-build/project
sh scripts/build.sh
```

After editing files in the Windows checkout, copy the edits to the Linux source before rebuilding:

```sh
rsync -a --exclude=out --exclude=__pycache__ --exclude=.git \
    /mnt/c/Users/ondev/Projects/dev-os/ ~/src/dev-os-build/project/
chmod +x ~/src/dev-os-build/project/scripts/*.sh
```

Changes to package selection need a Buildroot reconfigure; toolchain changes may need a clean build. See the Buildroot manual rather than assuming an incremental build updates every component.

## Accounts

The test configuration creates `dev` (UID 1000, member of `wheel`) and `root`, with separate randomly generated passwords. They are saved locally in `out/vm-credentials.json` and excluded from version control. Reconfiguration preserves existing credentials. These accounts are for the local prototype image; configure accounts for your intended deployment before distributing an image.

The regular configure script still locks root login by default. `DEVOS_TEST_VM=1` explicitly enables the local test accounts. `sudo` requires the `dev` user's password, and `su -` requires the root password.

## Automated boot tests

In the Linux copy:

```sh
python3 scripts/smoke-vm.py --memory 256
python3 scripts/smoke-vm.py --memory 512
python3 scripts/smoke-vm.py --memory 1024
```

Use `--accel tcg` if `/dev/kvm` is unavailable. Each run uses a temporary disk snapshot, verifies actual guest operations, and terminates the VM at the end. Reports and serial logs go to `out/test-results/`. Credentials are not sent to the log.

The tests cover unprivileged install rejection, password-authenticated `sudo` and `su`, local `.dpk` install/list/execute/remove, DHCP, and a bounded memory allocation. The memory probe touches half of `MemAvailable` and holds it for 12 seconds; it does not deliberately exhaust memory. Boot timing is host wall time to the login prompt, and shell round-trip measurements include host scheduling and the test harness. These are smoke-test observations, not a guarantee of latency under every workload.

## Export and run interactively

After a successful build and test, inside the Linux copy:

```sh
sh scripts/export-artifacts.sh /mnt/c/Users/ondev/Projects/dev-os
sh scripts/run-qemu.sh
```

Or use the exported files directly from PowerShell at the Windows checkout:

```powershell
.\scripts\run-qemu.ps1
```

To repeat the Windows boot-only smoke test, run `python scripts/smoke-windows.py` from the Windows checkout. It starts QEMU without a visible window, waits for the login prompt, records the result, and closes the test VM.

The prompt update is exported as `out/images/rootfs-prompt.ext4` because the running VM locks the original disk. `run-qemu.ps1` selects this file when it is newer than `rootfs.ext4`; a later full export with a newer `rootfs.ext4` takes precedence. Existing running VMs keep their current disk until closed and relaunched.

The Windows runner defaults to software emulation; `-Acceleration whpx` is available if Windows Hypervisor Platform is already enabled. Both runners use disk snapshots, so installed packages disappear when you exit. The exported kernel and ext4 image are in `out/images`, together with their SHA-256 checksums. These direct-kernel VM artifacts are separate from the UEFI installer ISO in `out/installer`; see [INSTALL.md](INSTALL.md) for building and using the installer.

Exit QEMU with `Ctrl+A`, then `X`. Login as `dev`, then try:

```sh
sudo dev install /opt/hello-0.1.0.dpk
dev-hello
dev list
sudo dev remove hello
su -
```
