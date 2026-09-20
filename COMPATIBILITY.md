# Package compatibility

The source package manager checks compatibility before publishing installed files.
Repository installation and upgrade now select missing dependencies and commit
the prepared package set with one durable database decision. A dependency
conflict leaves the existing installation intact.

Optional manifest fields are supported by the Python validator and TypeScript SDK:

```json
{
  "name": "example-app",
  "version": "1.0.0",
  "arch": "x86_64",
  "dependencies": { "example-library": ">=2,<3" },
  "runtime_versions": { "node": ">=22,<23" }
}
```

This fragment omits the payload and application entry configuration. Dependency
names refer to installed `.dpk` packages. Constraints use Python packaging version
and specifier semantics (PEP 440), not npm semver ranges; `*` accepts any valid
version. Self-dependencies and the ambiguous `depends` field are rejected.
Runtime keys are `node`, `python`, `bash` and `sh`; `native` is checked through ELF
metadata, not a runtime version. `sh` currently denotes the Buildroot BusyBox
runtime version, not a shell language standard.

Installation and replacement validate the prospective installed database. Removal,
upgrade and rollback are refused if another installed package's declared version
constraint would no longer be satisfied. Dependency declarations do not grant
permissions or select environment variables.

The candidate post-build hook writes `/usr/lib/devos/platform.json` from the
configured Buildroot versions. Architecture-specific packages require this file.
Runtime declarations are checked against target interpreter paths and, when
requested, their recorded versions.

ELF payloads must declare `arch: x86_64`. The checker reads ELF headers, interpreter,
shared-library dependencies, library search paths and GNU symbol version
requirements without executing the payload or calling `ldd`. It resolves target
absolute symlinks within the target root and considers packaged libraries using
`$ORIGIN`. Executable Windows PE files are rejected. Strict installation also
checks executable script shebangs and rejects CRLF interpreter lines.

These are static checks, not a guarantee that arbitrary Linux binaries will work.
Optional `dlopen` libraries, kernel syscall requirements, CPU instruction features,
graphics drivers and application behavior still require target tests. The current
library resolver does not model every glibc search rule, including inherited RPATH
and the loader cache, and can reject binaries needing those rules. Unsupported
dynamic path tokens and version tables without section headers fail closed.

Evidence: `tests/test_compat.py` includes real compiled ELF fixtures with a
versioned shared library, missing loader/library/version, wrong architecture,
runtime constraints, and dependency consistency across package operations.
Passing these tests does not complete the production compatibility gate.

## Repository dependency selection

`dev install NAME` fetches missing dependencies from the authenticated index.
`dev upgrade NAME` also updates dependents when the selected library version no
longer satisfies their old constraints. Every selected archive is independently
verified by TUF before its manifest contributes to the plan. Cycles can be
installed together because no package scripts execute during installation.

The current repository advertises one version per package. Selection considers
the installed version and that advertised version, never silently downgrades,
and fails if this set cannot satisfy all constraints. It is not a solver across
historical repository versions. Limits are 128 selected packages and 1 GiB of
compressed target data. Download caches and rollback archives may remain after a
rejected plan; installed files and the installed database remain unchanged.

Before committing, the checker validates file ownership and ELF requirements
against the planned libraries, including unchanged installed packages. Journal
version 3 recovers the whole package set using the existing durable file-transition
machinery. Process-crash tests cover precommit rollback, postcommit retention,
interrupted recovery and database write failure. File publication is sequential:
running applications can still observe a mixture during the transition, so live
process coordination remains a production requirement.

Local archive installation still requires dependencies to be installed already.
Use `dev rollback APP LIBRARY` to restore the previous versions of explicitly
named packages together. Every cached previous archive must remain authorized
under the current trust policy; one revoked, missing or corrupt member aborts the
whole set. Final dependency and ABI checks apply before the shared commit.
`dev rollback NAME` still refuses a dependency conflict when other packages also
need to be rolled back. Newly installed dependencies are not automatically removed.
Previous-version pointers retain one generation per package, not a complete system
snapshot or an unlimited history of package sets.
The repository batch path passed normal-boot candidate QEMU tests for signed
install, upgrade, rollback and revoked-member refusal; see
`out/test-results/candidate-signed.json` for the exact image hash. Twelve signed
batch QEMU power-cut cases also pass with normal-init recovery; see
`out/test-results/signed-powercut.json`. Physical storage acceptance remains pending.
