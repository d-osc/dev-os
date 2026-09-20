# Package transaction recovery

The source package manager now journals install/remove/upgrade/rollback operations under
`/var/lib/dev/transaction`. This is not yet part of the delivered ISO.

Repository install/upgrade now use journal version 3 to commit several packages
with one database decision. The journal records the entire before/after database;
recovery validates package identity and unique ownership, then applies the same
durable backup/restore machinery as single-package replacement. All package
dependencies are checked against the final set before publication. Precommit
recovery restores the whole old set; postcommit cleanup retains the whole new set.
`tests/test_batch.py` covers process termination at file/commit boundaries,
interruption during recovery, ownership conflicts, modified files and database
write failure. Twelve signed batch QEMU power-cut cases now pass with normal-init
recovery (`out/test-results/signed-powercut.json`); physical storage acceptance
remains pending. Files
are published sequentially, so existing processes can observe mixed contents;
a durable batch commit does not provide live filesystem snapshot isolation.

The real ext4 exhaustion test now passes on the candidate recorded in
`out/test-results/disk-full-recovery.json`: a signed batch runs out of space after
its first file replacement. The old database and complete backups survive.
After deleting the QA filler and rebooting the same disk, the normal init hook
restores both old packages before login. Recovery itself can require free space;
this test deliberately reclaims space before reboot and does not claim that an
exhausted filesystem can always recover without administrator intervention.

```sh
sudo dev recover
sudo dev verify
```

`install`, `remove` and `verify` recover a pending transaction before proceeding,
under the same OS database lock. The source boot hook `S35dev-recover` also calls
recovery. A failed boot hook reports the problem; it does not itself stop all
other init scripts or enter a rescue shell. Runtime metadata lookup and `dev list`
refuse a pending transaction. Existing unsandboxed CLI processes are not stopped.

## Commit protocol

1. Validate and stage package contents. Check existing destination conflicts.
2. Copy complete new files (install) or backups (remove) to a private preparation
   directory. Flush data, modes, the journal and directory entries.
3. Publish the prepared directory as `transaction` and flush its parent.
4. For install, flush a scratch file on each destination filesystem and publish it
   using an exclusive hard link. Keep the scratch link as proof of inode ownership.
   For remove, unlink verified originals after their backups are durable.
5. Atomically replace and flush the package database. Its before/after contents
   are the recovery commit decision.
6. Remove scratch links, detach the completed journal by a directory rename, then
   delete it. An interrupted cleanup cannot expose half-deleted active backups.

Before database commit, recovery rolls back. After commit, recovery retains the
new state. Recovery is idempotent, including when interrupted while restoring a
file. It preflights all destinations and backups before rollback. Modified bytes,
modified Unix modes, replaced install inodes, symlinks, corrupt backups or an
unexpected database prevent automatic recovery; they are never silently overwritten.

Do not delete a journal to bypass a recovery conflict. Preserve a copy of the
state and the conflicting files, investigate, and resolve the conflict before
retrying `dev recover`. After freeing disk space, a retained journal can be retried.

## Validation and boundaries

- Subprocess abrupt-exit tests cover preparation, journal publication, copying,
  file publication, each file operation, database commit and cleanup detach.
- Tests interrupt recovery itself, preserve post-crash user changes (including
  identical-byte replacements), reject corrupt backups, and exercise write errors
  both before and after database replacement.
- `scripts/test-transaction-powercut.py` kills QEMU with SIGKILL at seven
  checkpoints, reboots the same writable ext4 disk and checks database/files.
  Includes interrupting recovery after an earlier interruption.
- Results: `out/test-results/transaction-powercut.json`, tied to the tested
  `tools/dev.py` SHA-256. Input images and user VMs are untouched.

Linux filesystems must implement hard links, atomic rename and truthful fsync.
The tested production filesystem is ext4 in QEMU. Windows is a development host;
directory durability is not claimed there. These tests do not simulate physical
controller cache failure or establish compatibility with every filesystem.

The operation requires additional disk space for the journal backups, staging and
temporary published links. A power interruption can leave preparation/cleanup
directories; they are collected under the database lock on the next operation.
Hostile concurrent changes to administrator-controlled directories remain outside
the current security guarantee. Image-level kernel/base-system rollback remains
separate work required for production.

## Replacement transactions (journal version 2)

Upgrade stages both old and new files, then handles added, changed, removed and
unchanged paths in one journaled database transition. Changed files are replaced
by atomic rename from same-directory scratch links. Before commit, recovery
restores the previous files/database; after commit it retains the new version.

New installs cache archives by hash in `/var/lib/dev/archives`. Replacement records
the prior archive reference. `dev rollback NAME` restores that version under the
current trust policy; a second rollback can switch back. Missing/corrupt caches
prevent rollback. Old installs without caches require migration before upgrade.
Upgrade compares PEP 440 versions using `packaging` and rejects silent downgrades.

This does not yet solve dependency transitions across multiple packages, stop
running applications, or switch every file atomically for existing CLI processes.
A live process can observe a mixture while files are replaced; coordination or
versioned deployment remains a production concern. Modified package data is
refused rather than merged. Unreferenced caches require a retention policy.

Validation now includes upgrade/rollback crash cases and recovery interrupted
again. The QEMU harness passed 17 cuts/reboots across all four operations. Its
fixture explicitly permits unsigned packages and supplies the pure-Python
`packaging` library; signed install/upgrade is tested separately through TUF.
