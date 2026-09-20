# Kernel and base-system update work

Status: incomplete; the delivered installer still creates one root partition.
`tools/dev_boot.py` is the A/B boot-policy component. The source installer now
creates EFI (512 MiB), boot (256 MiB), root A/B (4 GiB each) and a remaining-space
shared `/home` partition, requiring a 16 GiB disk. It installs only slot A and
records B as uninitialized in `/etc/devos-system.json`. Source now has
`dev system-fetch` for authenticated download and `dev system-deploy` for the
staging transaction below.
The new installer ISO passed installation and reboot
on QEMU VirtIO, NVMe and SATA, plus USB source-media protection, and is exported
separately as `out/installer/dev-os-0.1-ab-candidate.iso`;
it has not replaced the delivered single-root ISO.

The intended transaction stages an authenticated kernel and root filesystem in
an inactive slot while retaining the confirmed slot. The shared boot filesystem
has a generated GRUB configuration with a literal confirmed default, separate
kernel paths for A/B, and an environment block containing only the next trial.
Before booting a trial, GRUB must successfully consume its marker. If reading or
writing that environment fails, it keeps the confirmed default. This uses GRUB's
environment mechanism, which has storage/firmware restrictions that must be
validated on supported hardware:
[GRUB environment block](https://www.gnu.org/software/grub/manual/grub/html_node/Environment-block.html),
[next_entry](https://www.gnu.org/software/grub/manual/grub/html_node/next_005fentry.html).

The component validates canonical UUIDs, generates both slot entries, atomically
publishes a confirmed configuration and uses the real `grub-editenv` utility to
create/schedule/cancel the trial. Three initial tests pass, including real GRUB
syntax checking and environment creation/modification. The additional real
UEFI/GRUB QEMU test now passes six checks: confirmed A boot, one-shot B trial,
return to A without confirmation, fallback when B's kernel is missing, persistent
B after explicit confirmation, and retaining confirmed B when the environment
block is corrupt. `out/test-results/ab-boot.json` records the exact boot-policy and
base-image hashes. The test uses an ISO only to enter GRUB, then boots kernels
and roots from a writable GPT disk with three partitions; it does not use QEMU's
direct `-kernel` shortcut.

This test found and fixed a real discrepancy: using a menu ID for `fallback`
passed GRUB syntax validation but failed to recover from a missing kernel. The
generated fallback now uses the numeric menu index, matching the tested parser.
These results do not prove installer integration, signed root-image deployment,
kernel-hang watchdog recovery, interrupted boot-state writes or physical hardware.

Remaining integration requirements:

- Complete installer acceptance on physical machines. VirtIO, NVMe and SATA runs
  pass cancellation/erase-confirmation, standalone
  disk boot, sudo/su, boot/home mounts, unsigned rejection, signed package
  operations and package/home persistence. Evidence:
  `out/test-results/installer-ab-{virtio,nvme,sata}.json` and their exact ISO SHA-256.
  `installer-ab-usb.json` additionally verifies raw-written USB boot and rejection
  of the installer's own writable source disk.
- Signed system-release metadata binding kernel, root image, architecture and
  release version, with anti-rollback policy and offline recovery behavior.
- Verify inactive device identity and mount state before writes; never overwrite
  the active/confirmed root or kernel. Flush and verify staged bytes before trial.
- Define how installed `.dpk` packages, `/etc` and mutable service data survive
  base updates and rollback; reject conflicts instead of silently dropping data.
- Health confirmation only after required services and package recovery succeed.
  A trial marker being consumed is not proof that the system is healthy.
- A watchdog/reboot policy for hangs. The current `panic=10` kernel argument only
  addresses panics; `rootwait` or a frozen kernel can still require a reset.
- Extend QEMU UEFI tests to bad root filesystems, kernel hangs, interrupted staging
  and interrupted boot-state writes, then test real hardware. The six boot-policy
  cases above pass, but are not the complete system-update acceptance suite.

Boot helpers assume the caller has already validated a trusted writable boot
mount. They are not a privileged broker for arbitrary user-supplied paths.

## Signed release transport (source only)

`tools/dev_system_release.py` prepares a directory with `manifest.json`, `bzImage`
and `rootfs.tar.gz`. The manifest binds version, monotonic sequence, x86_64 and
the exact length/SHA-256 of both artifacts. It caps kernel bytes at 128 MiB and
compressed rootfs at 1 GiB, validates fixed names and takes bounded verified
copies. Builder, publisher and client also inspect the root archive with
`dev_rootfs.py`: path/link containment, duplicate and non-directory parents,
member/expanded size limits, no devices/FIFOs/sparse payloads, protected system
ownership/modes, required executable/configuration entries, x86_64 platform,
locked account passwords and absence of user/installed-package state.
These checks do not prove kernel bootability. The source publisher accepts `publish --system-release DIRECTORY` and
signs each artifact plus `system-index.json` through the same threshold TUF roles.

```sh
python3 tools/dev_system_release.py --kernel release-inputs/bzImage \
  --rootfs release-inputs/rootfs.tar.gz --output release-0.1.1 \
  --version 0.1.1 --sequence 1
python3 tools/dev_publish.py --keys /private/devos-keys \
  --passphrase-file /private/passphrase publish --system-release release-0.1.1
sudo dev system-fetch
```

Inputs must be sanitized release artifacts, not the QA rootfs with local test
accounts. The builder does not remove accounts or make an arbitrary rootfs safe.
System deployment still requires integration of the staging extractor, device checks,
configuration/package preservation and health confirmation. Archive inspection
does not authorize passing the archive directly to an unrestricted tar extractor.

The client verifies the signed index, manifest and both targets, rejects identity
or hash disagreement, and persists its sequence high-water mark only after all
downloads succeed. Reusing a sequence with different manifest bytes is rejected.
The publisher also refuses non-increasing sequences and replacement of an
existing version. `--minimum-sequence N` adds a caller-supplied floor; integration
with the active installed system's release state remains part of deployment work.
Known-good local slot rollback must be designed separately from this download
anti-rollback policy.

Real TUF loopback tests cover transport round trips, tampered target rejection,
monotonic sequences and changed publisher inputs. Their minimal policy-valid
root filesystems and opaque kernel fixtures are deliberately not boot images.
Five focused archive tests cover traversal, links, special files, account state
and oversized PAX headers rejected before allocation. Inspection of the actual
sanitized rootfs from the A/B candidate passed (3,333 entries, 155,804,203 payload
bytes), recorded in `out/test-results/rootfs-sanitized.json`; the QA rootfs with
test accounts was correctly rejected. This source command is not yet included in
the exported A/B candidate ISO.

`dev_rootfs.extract` now provides a Linux-root staging primitive: it snapshots
bounded compressed bytes privately, checks the caller's authenticated length and
SHA-256, inspects before writing, and extracts only into an empty root-owned
directory without group/world write access. Directory-descriptor traversal uses
`O_NOFOLLOW`; regular files are exclusively created and hash-checked, and links
are created after payload writes. Ownership/modes are restored and files and
directories are synced. Unsupported extended metadata (including capabilities
and ACLs) and contradictory hardlink metadata are rejected rather than dropped.
Nine focused tests pass as Linux root, including actual extraction and rejection
without payload writes. The complete sanitized rootfs from the tested candidate
ISO now passes host extraction and all-entry verification: 306 directories,
2,300 regular files and 727 symlinks, with matching content hashes, ownership,
modes and link text, and no extra/missing entries. See
`out/test-results/rootfs-extraction.json`; the report binds the ISO, payload and
extractor hashes. Reproduce using Linux root:

```sh
python3 scripts/test-rootfs-extraction.py --iso /path/to/candidate.iso \
  --output out/test-results/rootfs-extraction.json
```

This is not inactive-slot or boot acceptance. The caller must validate/isolate the destination mount
and exclude concurrent writers. A failed staging directory is incomplete and must
not be published or booted; this primitive is not a deployment transaction.

`tools/dev_slots.py` adds read-only installed-layout observation. It compares
root-owned A/B metadata with kernel command-line slot/root identifiers, sysfs
partition numbers and device major/minor identifiers, and fresh `blkid` probes.
It rejects duplicate partition/filesystem UUIDs, split-disk layouts, read-only
partitions or device holders, missing/overmounted or mismatched system mounts,
and an inactive partition already mounted or used by swap. Six focused tests
cover these identity and refusal rules. `scripts/test-installer.py` additionally
tests the observer inside a newly installed guest and checks refusal while its
inactive root is temporarily mounted read-only; `--output-dir` allows separate
disposable runs without replacing earlier evidence.

Observation is not a lock or write authorization: a deployer must exclude
concurrent disk/mount changes, account for other mount namespaces and open users,
revalidate identity immediately before writes, and hold its device/mount handles
through staging. No formatting, extraction, boot selection or deployment command
is enabled by this module. Actual collection on the target is a separate
integration gate from the focused validation tests.

Target observation passed in a fresh VirtIO UEFI installation from the existing
A/B candidate ISO: active A/inactive B resolved correctly, mounting B read-only
caused refusal, and unmounting restored the original result. Signed package
operations and installed disk reboot/persistence also passed in the same run.
`out/test-results/slots-installer-virtio.json` records the ISO and observer hashes.
The observer was delivered on the read-only QA fixture disk, not embedded in that
ISO. Source post-build now installs it for the next image build.

## Configuration preservation (source only)

`tools/dev_config.py` snapshots a quiesced live `/etc`, converts an inspected
release inventory to the same comparable shape, and plans a three-way
base/current/incoming merge that selects unchanged upstream defaults, retains
local edits/additions/deletions, and refuses both-sides conflicts instead of
silently choosing one. A missing baseline is an error, never an invitation to
overwrite.

The module now also applies a ready plan to a freshly extracted staged root.
`apply` re-verifies each retained local entry while copying it (bounded by the
snapshot limits), refuses a staged tree that does not exactly equal the
authenticated incoming inventory, applies deletions children-first so a changed
entry type never renames over a populated directory, publishes files and
symlinks through temporary names with fsync and exact mode/ownership
restoration, and re-snapshots the staged tree against the merged plan before
returning. A failed apply leaves an incomplete staged root that must be
discarded, never published or booted: this is a staging step, not a
transaction, and it does not authorize the destination mount or exclude
concurrent writers.

Four focused tests cover the conflict-before-write refusal, local/upstream
merge application, tampered-staged refusal and root-only ownership
restoration; all pass, and the full regression passed 199 tests on both Linux
(41 environment skips) and Windows (56 environment skips). The sanitized A/B
candidate payload passed the complete host round trip — extraction, all-entry
verification, snapshot, plan and apply — with 3,333 entries verified, 359 `/etc`
entries merged, a local addition preserved and every upstream file byte
unchanged: `out/test-results/rootfs-config-extraction.json` records the ISO,
payload and planner hashes, and `regression-linux.json` the tested sources.

This closes planning and staging application for `/etc` only at this layer.
The deployment transaction below assembles it; mount authorization on real
hardware, boot health confirmation and the exported ISO remain outstanding.

### Package preservation (source only)

`tools/dev_preserve.py` plans how installed packages transfer to a staged
release root. It validates each installed record (identity, owned file map
including generated commands/launchers, protected paths, cached-archive
references bound to their content-hash path segments), refuses any overlap
between package-owned files and the release payload — even with identical
bytes, since ownership would stay ambiguous and a later removal could delete
base files — and requires a cached archive plus the rollback archive for
every preserved package. The plan's transferable state is exactly the package
database and the referenced caches under `var/lib/dev/archives/`; archives are
referenced with their recorded hashes, not read. Seven focused tests cover
ready plans, per-package conflict reporting, count limits and input rejection.

The planner also ran against a genuine database and release: installing
`examples/hello` with `dev.py --root` into a disposable live root and planning
its transfer to the authenticated A/B candidate inventory produced a ready plan
whose archive hash matched the cached bytes; the extracted image's strict
signed policy correctly refused an unsigned install first, so the disposable
root shape was used. Recorded in `out/test-results/rootfs-config-extraction.json`
(`package_preservation_ready_with_verified_archive`).

This is planning only. Applying it — authenticating archives under the
deployment's trust policy, copying state, reinstalling payload bytes onto the
staged root, rewriting the staged database and re-running dependency/ABI
checks there — belongs to the undesigned deployment transaction. Mutable
service data outside `var/lib/dev` is not planned anywhere yet.

### Deployment transaction (source only)

`tools/dev_deploy.py` assembles the whole chain into one command:
`sudo dev system-deploy` (plus `--baseline DIRECTORY` and `--cancel`). The CLI
holds an exclusive deploy lock and the package database lock, re-fetches and
re-verifies the signed release, re-observes slot identity immediately before
reformatting the inactive partition (keeping its recorded filesystem UUID),
mounts it privately under `/mnt`, runs the staging transaction, unmounts, and
schedules exactly one GRUB trial boot.

The transaction plans before writing: the `/etc` merge and package
preservation plans must both be ready before anything is touched, and a
conflict aborts with the inactive slot untouched. Writes then run in journaled
phases — prepared, extracted, merged, kernel, published, scheduled — recorded
on the live root; completion removes the journal, and the journal of an
interrupted run is reported and overridden by a fresh one, which rebuilds the
inactive slot from scratch. All live-system writes come last: until the GRUB
configuration and trial marker are published, nothing points the bootloader
at the staged slot. The staged root is also bound to this machine and slot:
fstab root/boot/EFI/home entries are rewritten from installed metadata,
`/etc/devos-system.json` is written for the inactive slot, the installation
record's root identity is rebound, and the release identity with its `/etc`
inventory is recorded on the staged root so the next deployment has its
three-way baseline. The release sequence must strictly exceed the recorded
baseline; the first deployment of an installer-created system needs
`--baseline` because no release record exists there yet.

Evidence: ten focused tests pass on Linux root with real `grub-editenv`,
covering the complete transaction (verified kernel installed for the inactive
slot, confirmed default retained, one-shot trial recorded in a real GRUB
environment), abort-before-write for configuration and package conflicts,
observation/metadata binding and sequence monotonicity; baseline and identity
units also run on Windows. `out/test-results/deploy-transaction.json` records
the checks and source hashes; full regressions passed 209 tests on Linux and
Windows with environment skips only.

Boundaries: this is host-fixture evidence — no real partition was formatted
or mounted and no trial boot executed. In-guest QEMU acceptance on a real A/B
disk, physical hardware, health confirmation after a trial, watchdog policy,
known-good rollback and confirmed-slot switching remain unimplemented. The
exported ISO predates this source; the target image also needs `mkfs.ext4`
and `grub-editenv` present for the command to run.
