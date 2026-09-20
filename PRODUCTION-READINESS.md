# Dev OS production readiness

Status: **NOT READY FOR PRODUCTION**. Source hardening started on 2026-09-19.
This is a release checklist, not a certification or a statement that the current ISO includes source changes.

## Release scope

Proposed first release: x86_64 UEFI, CLI, a dedicated disk, administrator-controlled packages.
Desktop and internet-facing server releases need additional acceptance criteria.
The deployment role, hardware and real workload are not yet confirmed.

## Implemented in source

- Package database uses a nonblocking OS lock, automatically released on process termination.
  The lock file stays on disk; its existence does not mean a process holds the lock.
  An old `var/lib/dev/lock` sentinel is rejected, not automatically removed.
  Do not run old and new package manager versions concurrently.
- `sudo dev verify [package]` audits installed payload, CLI wrappers and desktop entries against
  the installed inventory, checking SHA-256 and exact Unix permission bits, including special bits.
  It takes the package database lock; it does not repair files, detect untracked files, or authenticate
  publishers. An attacker able to modify the database can also change the expected hashes.
- Install/remove/upgrade/rollback now have durable journals and idempotent pre-commit rollback /
  post-commit cleanup. `dev recover` and the source boot hook recover interrupted
  work. Conflicting user changes and corrupt backups are preserved and reported.
  See [transaction design and boundaries](TRANSACTION-RECOVERY.md).
- TUF-backed `dev update` and `dev fetch` verify signed metadata/targets with an
  administrator-provisioned root. See [repository preview](REPOSITORY.md).
  Production policy now enforces signed local installation. `dev install NAME`,
  `dev upgrade NAME` and `dev rollback NAME` integrate TUF authorization with
  transactional replacement and cached previous archives. Rollback refuses a
  revoked old target; ordinary upgrade refuses downgrades.
- `dev trust` provisions a fingerprint-pinned root and enables the strict policy.
  The Linux/WSL publisher generates encrypted keys, uses 2-of-3 root/targets
  thresholds, supports root/role rotation and package revocation, and switches
  immutable local generations atomically. See [PUBLISHING.md](PUBLISHING.md).
  Actual operator keys, remote hosting and custody procedures remain unprovisioned.
- Dependency constraints, runtime versions and static x86_64 ELF library/ABI
  checks are now integrated before installation. Removal and replacement preserve
  declared dependency consistency. Repository install/upgrade now resolve the
  current signed index and use a single durable batch decision; six batch tests
  and four new publisher integration cases cover this path. Candidate image and
  physical-storage acceptance of the batch path remains pending; 12 signed
  candidate QEMU power-cut cases now pass. Explicit multi-package
  rollback is also implemented and checks every old archive against current
  trust before changing the set. See [compatibility scope](COMPATIBILITY.md).

2026-09-20 candidate checkpoint: isolated Buildroot image rebuild completed with
TUF 7.0.1, securesystemslib 1.5.1, pyelftools and the current compatibility code.
Exact upstream hatchling backend requirements are provided by isolated pinned
host wheels. The post-build hook now generates target platform/runtime metadata.
This is a QA candidate with local test credentials, not a released production ISO.
Latest Linux regression passed 143 tests; an additional package-operation
dependency test passed in the 11-test compatibility suite. Latest TypeScript
compile/type checks and six integration tests passed. Candidate normal-boot
verification found that Node was missing: the old configuration set an internal
C++ symbol that Kconfig discarded. Source now enables BR2_TOOLCHAIN_BUILDROOT_CXX
and asserts Node selection after olddefconfig; the clean toolchain rebuild is now complete.
The earlier failed candidate had image hash
193c963be441bbc0d37eb0c216bc9476dc0b2605a21566248a06dfbd957d1275.
Normal login and Ed25519 operations succeeded before the missing-Node failure;
later probe checks were not reached. The evidence below describes older runs.

Last full regression with pinned host dependencies: Windows 131 tests collected,
116 passed, 15 POSIX/publisher skips; Linux 131 passed. Subsequent publisher and
provisioning verification passed 10 focused tests (including two additional tests
for two available signers and fingerprint-pinned setup). TypeScript compilation,
negative type checks and all six SDK integration tests passed.
QEMU abrupt power-cut/reboot tests passed 17 cases on disposable ext4 copies:
`out/test-results/transaction-powercut.json` includes the exact tested core hash.
The source boot hook passed shell syntax validation; full normal-boot integration
with a rebuilt candidate ISO is still pending. SDK release artifacts are unchanged.
The QEMU fixture tests transactions with an explicit unsigned development policy;
signed installation/upgrade/rollback are separately covered by real TUF loopback
integration. The recorded core hash predates the additional `dev trust` CLI command.

## Blocking release gates

| Gate | Required evidence | Current state |
| --- | --- | --- |
| Crash-safe package operations | Durable transaction journal; kill/power interruption tests at each commit boundary; restart recovery without losing user changes | All four operations implemented; earlier 17 cuts plus 12 signed candidate cuts and real ext4 exhaustion pass; physical storage checks pending |
| Trusted distribution | Signed packages and release metadata, trust/key rotation and revocation policy, tamper and stale-metadata tests | Local publisher/provisioning/strict install and adversarial tests pass; production custody/hosting and system-release signing pending |
| System servicing | Tested security update delivery for kernel/base system, failed-update rollback, documented recovery media | Signed package upgrade/rollback, repository batch source and explicit set rollback implemented; batch target validation and kernel/base-system rollback pending |
| Package compatibility | Dependency and ABI policy; target architecture enforcement; representative binaries tested on target | Static checks, dependency consistency and current-index batch resolution tests pass; full target acceptance remains |
| Permission enforcement | Explicit CLI trust model; sandbox escape review; per-user grants and revocation if persisted; no silent elevation | Incomplete |
| Supported image | Rebuild from pinned sources including current manager/runtime; versioned artifacts, checksums and build provenance | Current ISO predates recent source changes |
| Vulnerability management | Buildroot package inventory/SBOM, current vulnerability triage, assigned patch owner and response policy | Missing |
| Failure and load tests | Disk-full, OOM, repeated reboot, sustained real workload, backup restore; recorded acceptance limits | Incomplete |
| Physical target | Install/boot/network/storage tests on each supported hardware configuration | VM only |
| Release acceptance | All above evidence belongs to the exact candidate image hash; no shared test credentials shipped | Not met |

## Sequence

1. Confirm the first deployment role and measurable workload requirements.
2. Integrate the implemented install/remove recovery into the candidate image and normal boot tests.
3. Implement package/release trust and the update/recovery path before publishing a repository.
4. Complete permission enforcement and target compatibility checks.
5. Build a versioned candidate and test it end to end in QEMU.
6. Run target hardware and workload acceptance tests, then review remaining vulnerabilities.

Do not relabel a passing unit suite, a new ISO, or this document as production readiness.

## Active seven-item goal

The user's goal remains all seven items, not just these completed source changes.
Next work: verify the rebuilt candidate through normal boot and signed package
operations, test the new dependency/batch path on the target, then complete
image-level kernel/base-system rollback. Live-process coordination during file
replacement, archive/generation retention and legacy cache migration are also
unresolved production concerns; see TRANSACTION-RECOVERY.md and PUBLISHING.md.
Full dependency/ABI acceptance, permissions review, rebuilt ISO, sustained failure
tests and physical-hardware acceptance all remain in scope. No physical hardware
result may be replaced with a VM result. Consult live tool sessions for active
build/test state; this document is not a process monitor.

Latest batch source checkpoint: Linux regression passed 156 tests with source
hashes recorded in `out/test-results/regression-linux.json`, including planned
library ABI checks, coordinated explicit rollback, revoked-member rejection and
restoration after an injected rollback write failure. The native candidate now
includes this source. End-to-end signed batch operations in the image passed;
12 batch power-cut cases inside the image now pass.

Runtime checkpoint: the expanded real bubblewrap/WSLg test passed in
`out/runtime-tests/result.json`. It covers grant denial, network/storage isolation,
hidden host files/PIDs/environment, no-new-privileges, zero effective capabilities,
read-only app snapshot and descendant termination on stop. This is host Linux
evidence, not candidate/physical acceptance. Aggregate cgroup memory/CPU/PID
enforcement and OOM acceptance remain incomplete.

The clean C++/Node toolchain build completed successfully. Generated target
metadata now includes Node 22.23.2. The latest dependency/batch/rollback source
has been copied into the isolated candidate and an incremental rootfs rebuild
completed. Normal BusyBox init/login in QEMU passed the candidate smoke probe:
Node 22.23.2 and Python 3.14.7 match metadata, Ed25519 sign/verify works, TUF and
crypto imports work, unsigned installation is rejected, recover/verify commands
work, and the target Python ELF passes static dependency/ABI validation.
`out/test-results/candidate.json` records image SHA-256
e0536e6b5a25107252414cbe0dad98916f24bd81b021448fe7a850dde28420b8 and core SHA-256
9c1209e41a35990e673bf537e74fa947a6cc58cc61581f7e5a4677fa6a12b940.
This probe does not test pending-journal boot recovery, signed package downloads,
batch operations or physical hardware. The image contains QA credentials and is
not the sanitized installer release ISO.

The separate signed candidate probe now passed on the same image hash:
`out/test-results/candidate-signed.json` records fingerprint-pinned trust,
authenticated dependency installation, library/app batch upgrade, conflicting
single rollback refusal, explicit set rollback, revoked-member rollback refusal,
dependency-safe removal and installed-file verification. The guest uses the
actual image's package manager and TUF/crypto libraries, with an ephemeral public
repository served over explicitly enabled guest-loopback HTTP. Private signing
keys remain on the host and are destroyed with the fixture. No guest code/policy
replacement or unsigned override is used. This does not exercise production
HTTPS hosting, pending-journal boot recovery, power interruption or physical hardware.

Real disk-exhaustion acceptance passed on the same candidate image:
`out/test-results/disk-full-recovery.json`. The guest fills its disposable ext4
after the first file of a signed two-package upgrade, observes ENOSPC, verifies
that the database still equals the journal's before-state and all old backups
remain intact, then reclaims the test filler. After SIGKILL/reboot, normal init
recovers both previous versions before login; the verifier checks the absence of
a pending journal before invoking any `dev` command. This proves this specific
failure boundary and recovery after space is available, not all disk-full cases
or recovery without enough free space. The separate signed power-cut suite also
completed: `out/test-results/signed-powercut.json` records all 12 cases passing
on the same candidate image. Each case kills QEMU at a transaction boundary,
boots the same disk through normal init, and checks that recovery finished before
invoking any package command. Recovery is offline after the test repository
process disappears with the killed guest. This simulates guest power loss, not
a physical storage controller losing power or every possible interruption point.

Kernel/base-system servicing now has an initial A/B GRUB boot-policy component
(`tools/dev_boot.py`) with three passing tests using real GRUB syntax/environment
utilities and six passing UEFI/GRUB QEMU checks in `out/test-results/ab-boot.json`.
The missing-trial-kernel case found a numeric fallback-index bug that is now fixed.
The component is now connected to the source installer layout, but not signed
system releases or automatic health confirmation. See [remaining system-update work](SYSTEM-UPDATES.md).

Installer integration checkpoint: source now uses the A/B boot policy with EFI,
separate boot, two 4 GiB root slots and shared `/home`; minimum disk is 16 GiB.
Slot A is populated and B is marked uninitialized. Real `sfdisk` tests on a
disposable regular file verify the GPT layout; target-configuration tests verify
mount ordering and GRUB configuration. Linux regression passed 161 tests.
The isolated candidate rootfs and sanitized installer ISO rebuilt successfully.
VirtIO installation and standalone disk reboot passed, including sudo/su,
separate boot/home mounts, unsigned rejection, signed package operations and
package/home persistence. Evidence: `out/test-results/installer-ab-virtio.json`.
The separately exported `out/installer/dev-os-0.1-ab-candidate.iso` has SHA-256
b2e46992db90ec60af2de1c76e5a7a831f113e3929b50d71df15d0d8a8bc0505.
It has not replaced the old ISO. The same ISO subsequently passed the NVMe and
SATA installation/reboot suites and USB raw-write boot/source-media protection.
Evidence is in `out/test-results/installer-ab-{nvme,sata,usb}.json`. Physical
hardware, signed base deployment and automatic health confirmation remain incomplete.

Signed system transport checkpoint: source now supports release manifests,
publisher `--system-release` and client `dev system-fetch`. Kernel/rootfs bytes
are separately TUF-authorized and bound to the release manifest, with bounded
copies and monotonic sequence checks. The full Linux regression passed 166 tests,
including the CLI, 18-test publisher suite and two manifest/copy tests. This is download
and publication only: safe extraction, inactive-slot staging, preservation of
configuration/packages and health confirmation remain missing. The exported ISO
predates these source changes. See SYSTEM-UPDATES.md for precise boundaries.

Rootfs validation checkpoint: builder, publisher and fetch now inspect archive
paths/links, ownership, bounded expansion, required executables/configuration,
architecture, locked accounts and absence of installed/user state. Five focused
adversarial tests pass. The actual sanitized candidate rootfs passed inspection,
while the QA archive was rejected; `out/test-results/rootfs-sanitized.json`
records the sanitized payload hash. A safe extractor and preservation/deployment
transaction are still required before any inactive-slot writes can be enabled.

Rootfs extraction checkpoint: `dev_rootfs.extract` now authenticates a bounded
private snapshot before inspecting and writing an empty protected destination.
It uses descriptor-relative no-follow traversal, exclusive file creation,
payload verification, deferred links, ownership/mode restoration and fsync.
Unsupported extended metadata and conflicting hardlink modes are rejected.
The Linux regression run passed 172 of 174 tests with two root-only tests skipped;
the separate Linux-root focused suite passed all nine tests (including one extra
hardlink-conflict case added after the full suite started). No extractor failures
were observed. The earlier 171-test JSON report predates this change.
This is a staging primitive only: mount authorization, real release extraction,
configuration/package preservation, transactional deployment and boot health
confirmation remain outstanding. It is not yet included in the exported ISO.

Real rootfs extraction checkpoint: `scripts/test-rootfs-extraction.py` reads the
sanitized payload and its manifest from the existing A/B candidate ISO without
extracting cpio paths on the host, then invokes the authenticated extractor in a
temporary Linux directory. All 3,333 entries passed independent verification of
content, type, ownership, permissions and link targets; no missing/extra paths
were found. The report `out/test-results/rootfs-extraction.json` binds the ISO
hash b2e46992db90ec60af2de1c76e5a7a831f113e3929b50d71df15d0d8a8bc0505,
payload hash and extractor source hash. The harness removed its temporary data.
This closes real-payload host extraction testing only; inactive-slot identity,
mount safety, preservation, deployment recovery and updated-system boot remain
unimplemented/unverified. The ISO itself has not changed.

Slot identity checkpoint: `tools/dev_slots.py` now validates the installed A/B
layout against kernel root/slot arguments, sysfs identities, direct filesystem
probes and actual mounts/swap. Six focused tests pass. A fresh VirtIO UEFI
installation passed target observation, mounted-inactive-slot refusal and
successful re-observation after unmount, alongside signed package and reboot
persistence checks. Evidence: `out/test-results/slots-installer-virtio.json`.
The observer ran from the QA disk; the released candidate ISO is unchanged.
This is read-only validation, not complete deployment exclusion: other mount
namespaces/open users and concurrent changes still require handling before any
inactive-slot write path is enabled. Preservation, staging transactions and boot
health confirmation remain outstanding.

Configuration preservation checkpoint: `/etc` merge planning now has a staging
apply step. `tools/dev_config.py` refuses conflicting plans before writing,
re-verifies every retained local entry during the copy, requires the staged
tree to exactly equal the authenticated incoming inventory, restores exact
modes and ownership through temporary names with fsync, and verifies the
applied tree against the merged plan before returning. Evidence: four focused
tests including a Linux-root ownership case, full 199-test regressions on
Linux and Windows with only environment skips, and a real-payload round trip
on the sanitized A/B candidate rootfs recorded in
`out/test-results/rootfs-config-extraction.json` (3,333 entries, 359 merged
`/etc` entries, local addition preserved, upstream bytes unchanged).

Package preservation checkpoint: `tools/dev_preserve.py` plans the transfer of
installed packages to a staged release root. It validates installed records
and cached-archive references, refuses package/release file overlap even with
identical bytes, and limits the transferable state to the database plus
referenced archives. Seven focused tests pass, and a genuine `dev.py`-produced
database planned cleanly against the authenticated A/B candidate inventory
with its archive hash verified (same evidence file,
`package_preservation_ready_with_verified_archive`). Planning only: applying
it inside a deployment transaction, re-running target ABI checks there, and
mutable service data outside `var/lib/dev` remain outstanding, and the
exported ISO still predates this source.

Deployment transaction checkpoint: `sudo dev system-deploy` now assembles the
chain — signed re-fetch, slot re-observation, inactive-partition rebuild
(keeping its filesystem UUID), private mount, extraction, `/etc` merge,
package-state transfer with per-file drift checks, machine/slot adaptation
(fstab, `devos-system.json`, installation record), verified kernel
installation, GRUB confirmed-default publication and a one-shot trial — under
a deploy lock, the package database lock and a journaled phase sequence, with
all conflict checks passing before any write. Evidence: ten focused Linux-root
tests with real `grub-editenv` in `out/test-results/deploy-transaction.json`,
and full 209-test regressions on Linux and Windows. Host fixtures only: no
in-guest A/B disk acceptance, physical hardware, trial boot, health
confirmation, watchdog or confirmed-slot switching yet, and the delivered ISO
predates this source (it also must ship `mkfs.ext4` and `grub-editenv`).
