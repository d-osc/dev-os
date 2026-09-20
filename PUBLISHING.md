# Publish and provision signed Dev OS packages

These are source tools, not a deployed production repository. Actual keys, HTTPS
hosting, custody and renewal procedures still need to be provisioned for the
deployment. Current ISO and SDK release artifacts are unchanged.

## Local publisher (Linux / WSL)

Install `config/repository-requirements.txt` in a virtual environment. Store a
passphrase of at least 16 bytes in a mode-0600 file outside the public repository.
The initial public and signing directories must be new and separate:

```sh
python tools/dev_publish.py --keys /secure/devos-keys \
  --passphrase-file /secure/devos-passphrase init --public /srv/devos-repository
python tools/dev_publish.py --keys /secure/devos-keys \
  --passphrase-file /secure/devos-passphrase publish ./hello-1.dpk
```

`init` prints the public bootstrap root fingerprint and writes
`bootstrap-root.json`. Private Ed25519 keys are encrypted PKCS8 files, mode 0600,
inside the mode-0700 signing directory. Root and targets each have three keys and
require two signatures; snapshot and timestamp have separate keys. Two available
root/targets keys suffice. Keeping all keys/passwords on one host is not independent
custody: operators must protect and back up the signing material separately.
No network upload or remote deployment is performed by these commands.

The public tree uses immutable `generations/<number>` directories and an atomic
`current` symlink switch. A static HTTPS server should expose `current/metadata/`
and `current/targets/`. New generations retain old versioned metadata and targets
so requests spanning a switch remain consistent. Do not edit generations or the
pointer manually. The next publish command recovers an interrupted publication.
Old generations are retained; operators still need a capacity/retention policy.

Archives are validated from private snapshots. A published name/version cannot
change bytes; bump its version. Inputs must contain a DPK manifest. A plain
third-party tarball must be converted/repacked first. Manifest-bearing `.tar.gz`
inputs work, but their repository target is named `.dpk`.

Publishing without archives renews metadata. Current lifetimes are root 365 days,
targets 30 days, snapshot 7 days and timestamp 1 day. Renewal is not automatic.

```sh
python tools/dev_publish.py --keys /secure/devos-keys \
  --passphrase-file /secure/devos-passphrase rotate targets
python tools/dev_publish.py --keys /secure/devos-keys \
  --passphrase-file /secure/devos-passphrase rotate root
python tools/dev_publish.py --keys /secure/devos-keys \
  --passphrase-file /secure/devos-passphrase revoke hello 1
```

Rotation publishes a root authenticated by old and new root keys. Revocation
removes a package version from current signed targets; retained bytes alone do not
authorize reinstall/rollback. Clients learn revocation by authenticated refresh.
Expiration bounds freeze attacks; it does not provide instant global revocation.

## GitHub Releases hosting

`github-upload` publishes the current signed generation to one GitHub release
through the `gh` CLI using the operator's credentials; it reads no tokens and
no signing material. Asset names are the generation-relative paths with `/`
encoded as `__`, and both subtrees coexist on one release: top-level metadata
roles become `metadata__<name>` assets and targets become
`targets__<encoded path>` assets. Paths containing `__` are rejected on both
ends to keep the mapping lossless.

```sh
python tools/dev_publish.py github-upload --public /srv/devos-repository \
  --repository OWNER/REPOSITORY --tag tuf-20260920
```

Use a new tag for every published generation: each release then holds one
complete immutable set, and clients configured with
`https://github.com/OWNER/REPOSITORY/releases/latest/download/` as both the
metadata and targets URL always resolve the newest non-prerelease release.
`--clobber` is explicitly required to replace the assets of an existing
release. The upload verifies the final GitHub asset list against the
generation before reporting success. On WSL without a native gh package the
command uses `gh.exe` interop and stages uploads on the Windows drive.

Repository content on GitHub is public: TUF authenticates integrity, not
confidentiality. Releases depend on GitHub availability and retention; keep
the local public generations so a removed release can be re-published.

A live round trip against github.com passed end to end with ephemeral keys:
publish, upload, fingerprint-pinned trust, `update`, `install` and `upgrade`
through `releases/latest/download` (hello 0.1.0 to 1.1.0). Evidence:
`out/test-results/github-releases.json`. This is host evidence, not an
in-guest acceptance, and real key custody remains the operator's job.

## Client provisioning

Obtain the bootstrap root and fingerprint through an independently trusted
channel. Replace the fingerprint/URL placeholders below:

```sh
sudo dev trust ./bootstrap-root.json --sha256 YOUR_VERIFIED_SHA256 \
  --metadata-url https://packages.example.org/current/metadata/ \
  --targets-url https://packages.example.org/current/targets/
sudo dev update
sudo dev install hello
sudo dev upgrade hello
sudo dev rollback hello
```

When app and library versions must move together, explicitly name both:

```sh
sudo dev rollback app library
```

The manager authenticates all previous archives and checks the final dependency
and ABI state before committing their files with one database decision. A revoked
member blocks the whole rollback. This restores one cached previous version per
named package; it does not remove new dependencies or roll back the kernel/base
system. Power-cut validation of this new batch path on the candidate remains pending.

`dev trust` checks fingerprint, expiry and root signatures, and enables required
signatures before writing the initial root/config. An interrupted setup fails
closed. Repeating the same setup is allowed; silently replacing an existing root
or changing endpoints is refused. Root rotation happens through TUF. Use
`dev --root /path/to/root trust ...` to provision an offline target directory.

The source production policy requires signatures and disables `--allow-unsigned`.
A real `/` root without a policy also requires signatures. A disposable development
root without policy retains unsigned testing support. An administrator can enable
the explicit unsigned override in a development policy, not a production policy.

Local installs copy archives into private staging, validate them there and authorize
the exact snapshot against TUF before changing installed files. Swapping the original
path after snapshotting cannot change installed bytes. `installed_trust` and
`installed_previous` are installer-only fields rejected in package manifests by
the manager and TypeScript validator.

Explicit signed rollback checks whether the older archive is still authorized by
current repository metadata, so it requires repository access and a valid clock.
Automatic recovery of interrupted transactions uses durable local backups offline.
