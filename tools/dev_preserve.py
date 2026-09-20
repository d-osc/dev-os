"""Plan how installed packages survive a base-system release. No writes.

Pure logic over the installed database and an inspected release inventory.
The deployment transaction remains responsible for authenticating archives,
transferring state and re-verifying every byte on the destination.
"""
import re
from pathlib import PurePosixPath

ARCHIVE_PATH = re.compile(r'var/lib/dev/archives/([0-9a-f]{64})/[^/\\]+')
DATABASE_PATH = 'var/lib/dev/installed.json'
LIMIT = 512


def _files(record):
    """Validate one installed record and return its complete owned file map."""
    name = record.get('name') if isinstance(record, dict) else None
    if not isinstance(name, str) or not isinstance(record.get('version'), str):
        raise ValueError('Invalid installed package identity')
    files = dict(record.get('files', {}), **record.get('installed_commands', {}),
                 **record.get('installed_launchers', {}))
    if not files:
        raise ValueError('Installed package has no file inventory: ' + name)
    for path, spec in files.items():
        parts = PurePosixPath(path).parts if isinstance(path, str) else ()
        if (not parts or parts[0] not in ('usr', 'opt') or len(parts) < 2 or '..' in parts
                or '\\' in path or ':' in path or str(PurePosixPath(path)) != path):
            raise ValueError('Invalid installed package path: ' + name)
        if path == 'usr/bin/dev':
            raise ValueError('The package manager is protected')
        if (not isinstance(spec, dict) or spec.get('mode') not in (0o644, 0o755)
                or not isinstance(spec.get('sha256'), str)
                or not re.fullmatch('[0-9a-f]{64}', spec['sha256'])):
            raise ValueError('Invalid installed file record: ' + name)
    return files


def _archive(item, label):
    """Validate one cached-archive reference, binding its path hash segment."""
    if not isinstance(item, dict): return None
    path, sha = item.get('archive'), item.get('sha256')
    match = ARCHIVE_PATH.fullmatch(path) if isinstance(path, str) else None
    if not match or not isinstance(sha, str) or match.group(1) != sha:
        raise ValueError('Invalid cached archive reference: ' + label)
    return {'path': path, 'sha256': sha}


def plan(database, release_files):
    """Select packages that can transfer to a staged release root.

    database maps package names to installed records; release_files is an
    inspected release inventory. Any overlap between a package's owned files
    and the release payload is a conflict, even with identical bytes: ownership
    would stay ambiguous and a later removal could delete base files. Archives
    are referenced, not read; authenticating and copying them, rewriting the
    staged database and ABI re-checks belong to the deployment transaction.
    Mutable service data outside var/lib/dev is not planned here.
    """
    if not isinstance(database, dict) or not isinstance(release_files, dict):
        raise ValueError('An installed database and a release inventory are required')
    if len(database) > LIMIT:
        return {'ready': False, 'packages': {}, 'state': {},
                'conflicts': [{'reason': 'Installed package count exceeds ' + str(LIMIT)}]}
    entries, state, conflicts = {}, {DATABASE_PATH: None}, []
    for name in sorted(database):
        record = database[name]
        if not isinstance(record, dict) or record.get('name') != name:
            conflicts.append({'package': name, 'reason': 'Record name does not match the database key'})
            continue
        try:
            files = _files(record)
            archive = _archive(record.get('installed_trust'), name)
            previous = _archive(record.get('installed_previous'), name + ' previous')
        except ValueError as exc:
            conflicts.append({'package': name, 'reason': str(exc)})
            continue
        if archive is None:
            conflicts.append({'package': name, 'reason': 'No cached archive is available to preserve the package'})
            continue
        overlap = sorted(set(files) & set(release_files))
        if overlap:
            more = ' and ' + str(len(overlap) - 1) + ' more file(s)' if len(overlap) > 1 else ''
            conflicts.append({'package': name, 'reason': 'Release also ships ' + overlap[0] + more})
            continue
        entry = {'version': record['version'], 'files': files, 'archive': archive,
                 'dependencies': record.get('dependencies', {}),
                 'runtime_versions': record.get('runtime_versions', {}), 'arch': record.get('arch', 'all')}
        if previous is not None: entry['previous'] = previous
        entries[name] = entry
    for name, entry in entries.items():
        for item in [entry['archive']] + ([entry['previous']] if 'previous' in entry else []):
            known = state.get(item['path'])
            if known is not None and known != item['sha256']:
                conflicts.append({'package': name, 'reason': 'Conflicting cached archive state: ' + item['path']})
            else:
                state[item['path']] = item['sha256']
    # No partial plan may be applied when any conflict exists.
    ready = not conflicts
    return {'ready': ready, 'packages': entries if ready else {}, 'state': state if ready else {},
            'conflicts': conflicts}
