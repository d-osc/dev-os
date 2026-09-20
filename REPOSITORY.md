# Signed repository client (source preview)

`dev update` verifies and refreshes repository metadata. `dev fetch NAME` downloads
a target verified against signed metadata. `dev install NAME`, `dev upgrade NAME`
and `dev rollback NAME` now integrate repository trust with package transactions.
Local installs obey the production signature policy. See [publishing and trust
provisioning](PUBLISHING.md).

The implementation uses [python-tuf](https://theupdateframework.readthedocs.io/en/stable/api/tuf.ngclient.updater.html),
with an administrator-provisioned bootstrap root, expiration/version verification,
and TUF root rotation. It does not download a root and trust it on first use.

## Configuration

Provision `/etc/devos/trusted-root.json` through a trusted out-of-band process.
No production key, trust anchor or repository endpoint is generated or shipped by
this change. `/etc/devos/repository.json` has this shape (URLs are placeholders):

```json
{
  "metadata_url": "https://packages.example.org/metadata/",
  "targets_url": "https://packages.example.org/targets/"
}
```

Only HTTPS URLs without credentials, query or fragment are accepted by default.
`allow_loopback_http: true` permits HTTP to literal `127.0.0.1` or `::1` for local
tests. Production needs a correctly provisioned clock and CA certificate store.
The client rejects a clock earlier than its last successful refresh.

The signed `index.json` target has this shape:

```json
{
  "version": 1,
  "packages": {
    "hello": {
      "version": "1",
      "arch": "all",
      "target": "packages/hello/1.dpk"
    }
  }
}
```

The package archive must independently appear in TUF targets metadata. Paths are
restricted to `packages/<name>/<version>.dpk`; the index is limited to 2 MiB and
10,000 entries, and archive downloads to 300 MiB. The archive manifest and ABI are
not validated by `fetch` yet; that belongs to the pending install integration.

Metadata and targets are cached below `/var/lib/dev/repository`. The existing
package database lock serializes repository operations. All verification errors
fail closed; there is no fallback to unsigned downloads.

## Development and tests

Install `config/repository-requirements.txt` in a disposable virtual environment,
then run `python -m unittest discover -s tests -p test_repository.py -v`.
Without these optional dependencies the eight TUF integration tests are skipped,
so the ordinary package-manager suite alone is not evidence of repository support.

Tests create independent ephemeral Ed25519 keys and a loopback HTTP repository.
They cover verified download, same-length payload tampering, unknown signer,
expired metadata, metadata rollback, root and targets key rotation, old-key
revocation, malformed target paths and clock rollback. Test private keys are never
installed as production trust. The fixture uses single-signature roles; it is not
a production signing-key management policy or publisher tool.

Target Buildroot dependencies, operator-managed production keys/hosting, system
release signing and kernel/base-system upgrade/rollback remain required. Local
publisher, pinned trust provisioning and signed package install/upgrade are now
implemented in source. The current ISO does not include these changes.
