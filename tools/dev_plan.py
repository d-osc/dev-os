"""Resolve authenticated repository packages and commit their files as one batch."""
from pathlib import Path
import tempfile


def install(root, name, database, dbpath, repository, dev, *, upgrade=False):
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version

    dev.require((name in database) == upgrade,
                'Package is not installed' if upgrade else 'Already installed; use dev upgrade')
    if repository.packages is None:
        repository.refresh()
    selected = {}
    stages = {}
    total_bytes = 0
    with tempfile.TemporaryDirectory(dir=dbpath.parent, prefix='unpack-') as temporary:
        workspace = Path(temporary)

        def select(package):
            nonlocal total_bytes
            dev.require(package not in selected, 'Repository version cannot satisfy dependency constraints: ' + package)
            dev.require(len(selected) < 128, 'Dependency plan exceeds 128 packages')
            dev.require(package in repository.packages, 'Missing repository dependency: ' + package)
            entry = repository.packages[package]
            if package in database:
                dev.require(Version(entry['version']) > Version(database[package]['version']),
                            'No newer repository version can satisfy dependencies: ' + package)
            # Bound planned downloads before fetching each target.
            info = repository.updater.get_targetinfo(entry['target'])
            dev.require(info is not None and 0 < info.length <= 300 * 1024 * 1024,
                        'Missing or oversized signed dependency target')
            total_bytes += info.length
            dev.require(total_bytes <= 1024 * 1024 * 1024, 'Dependency plan exceeds 1 GiB compressed data')
            archive, _ = repository.fetch(package)
            stage = workspace / package
            stage.mkdir()
            manifest = dev.prepare_install(root, archive, stage, database, repository=repository,
                                           replacement='upgrade' if package in database else None)
            dev.require(manifest['name'] == package, 'Dependency archive identity mismatch')
            selected[package] = manifest
            stages[package] = stage

        select(name)
        # The index advertises one current version per package. Choices only move
        # from installed to that authenticated version, so this loop is bounded.
        while True:
            prospective = dict(database, **selected)
            needed = None
            for package, manifest in prospective.items():
                dev.manifest_requirements(manifest)
                for dependency, constraint in manifest.get('dependencies', {}).items():
                    current = prospective.get(dependency)
                    allowed = SpecifierSet('' if constraint == '*' else constraint)
                    if current is not None and Version(current['version']) in allowed:
                        continue
                    # A selected dependency can invalidate an older dependent.
                    # Upgrade that dependent as part of the same transaction.
                    if dependency in selected and package not in selected:
                        needed = package
                    elif dependency not in selected:
                        needed = dependency
                    else:
                        raise ValueError(f'Dependency conflict: {package} requires {dependency} {constraint}')
                    break
                if needed is not None:
                    break
            if needed is None:
                break
            select(needed)

        commit(root, database, dbpath, selected, stages, dev)
        return selected


def commit(root, database, dbpath, selected, stages, dev):
    prospective = dict(database, **selected)
    old_files, new_files = dev.batch_files(database, prospective)
    sources = {file: stages[package] / file for package, manifest in selected.items()
               for file in dev.installed_files(manifest)}
    removed = set(old_files) - set(new_files)
    strict = dev.package_policy(root)['require_signed']
    compatibility = dev.compatibility_module()
    # Check unchanged dependents too: they may use a replaced library without
    # declaring it as a package dependency.
    for package, manifest in prospective.items():
        compatibility.check_install(root, manifest, stages.get(package, root), prospective, dev,
                                    strict=strict, planned_files=sources, removed_files=removed)
    dev.run_batch(root, dbpath, database, selected, sources)
    for package, manifest in selected.items():
        print('Installed ' + package + ' ' + manifest['version'])


def rollback(root, names, database, dbpath, dev):
    dev.require(1 <= len(names) <= 128 and len(set(names)) == len(names),
                'Rollback requires 1 to 128 unique package names')
    # Authenticate all previous targets with one current repository view before
    # publishing any file. A revoked member aborts the complete rollback.
    repository = None
    if dev.package_policy(root)['require_signed']:
        repository = dev.repository_module().Repository(root, dev)
        repository.refresh()
    selected, stages = {}, {}
    with tempfile.TemporaryDirectory(dir=dbpath.parent, prefix='unpack-') as temporary:
        for name in names:
            dev.require(name in database and 'installed_previous' in database[name],
                        'No previous package version is available: ' + name)
            previous = database[name]['installed_previous']
            dev.require(previous.get('name') == name, 'Previous package identity mismatch')
            archive = dev.history_archive(root, previous)
            stage = Path(temporary) / name
            stage.mkdir()
            manifest = dev.prepare_install(root, archive, stage, database, repository=repository,
                                           replacement='rollback')
            dev.require(manifest['name'] == name and manifest['version'] == previous['version'],
                        'Previous package archive identity mismatch')
            selected[name], stages[name] = manifest, stage
        commit(root, database, dbpath, selected, stages, dev)
        return selected
