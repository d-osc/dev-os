#!/usr/bin/env python3
"""Dev OS local Developer Package Kit manager (prototype formats 1 and 2)."""
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import sys
import tarfile
import tempfile
import uuid

LIMIT = 256 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def safe_path(name):
    p = PurePosixPath(name)
    require(isinstance(name, str) and '\\' not in name and ':' not in name
            and not p.is_absolute() and '..' not in p.parts
            and str(p) == name and bool(p.parts), 'Unsafe package path')
    require(p.parts[0] in ('usr', 'opt') and len(p.parts) > 1,
            'Packages may install only beneath usr/ or opt/')
    require(name != 'usr/bin/dev', 'The package manager is protected')
    return p


def cli_launchers(m):
    """Validate declarations and generate ordinary, unsandboxed Unix commands."""
    if 'cli' not in m:
        return {}
    cli = m['cli']
    require(isinstance(cli, dict) and set(cli) == {'commands'}, 'cli must contain commands')
    commands = cli['commands']
    require(isinstance(commands, dict) and 0 < len(commands) <= 128, 'Invalid cli.commands')
    result = {}
    interpreters = {'node': ['/usr/bin/node', '--'], 'bash': ['/bin/bash', '--noprofile', '--norc', '--'],
                    'sh': ['/bin/sh', '--'], 'python': ['/usr/bin/python3', '-E', '-s', '--']}
    for name, entry in commands.items():
        require(isinstance(name, str) and re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._+-]{0,79}', name),
                'Invalid CLI command name')
        path = 'usr/bin/' + name
        safe_path(path)
        require(path not in m['files'], 'CLI launcher conflicts with payload: ' + path)
        require(isinstance(entry, dict) and set(entry) <= {'runtime', 'entry_point', 'args'}, 'Invalid CLI entry')
        runtime = entry.get('runtime', 'native')
        require(isinstance(runtime, str) and runtime in ('native', 'node', 'bash', 'sh', 'python'), 'Unsupported CLI runtime')
        point = entry.get('entry_point')
        require(isinstance(point, str) and point in m['files'], 'CLI entry point must be a packaged file')
        if runtime == 'native':
            require(point in m.get('executables', []), 'Native CLI entry point must be in executables')
        args = entry.get('args', [])
        require(isinstance(args, list) and len(args) <= 64 and
                all(isinstance(a, str) and '\x00' not in a and len(a) <= 4096 for a in args), 'Invalid CLI args')
        argv = ([] if runtime == 'native' else interpreters[runtime]) + ['/' + point] + args
        result[path] = ('#!/bin/sh\nexec ' + ' '.join(shlex.quote(a) for a in argv) + ' "$@"\n').encode()
    return result


def desktop_launchers(m):
    if 'launcher' not in m:
        return {}
    config = m['launcher']
    require(m.get('format') == 2 and isinstance(m.get('window'), dict), 'launcher requires a format 2 window')
    require(isinstance(config, dict), 'Invalid launcher config')
    require(not any(key in config for key in ('runtime', 'entry_point', 'args')),
            'Configure runtime, entry_point and args under window, not launcher')
    require(set(config) <= {'name', 'comment', 'icon', 'categories'}, 'Invalid launcher config')
    name = config.get('name', m.get('display_name', m['name']))
    comment = config.get('comment', '')
    for value, limit, field in ((name, 128, 'name'), (comment, 512, 'comment')):
        require(isinstance(value, str) and len(value) <= limit and
                not any(ord(c) < 32 or ord(c) == 127 for c in value), 'Invalid launcher.' + field)
    require(bool(name.strip()), 'Invalid launcher.name')
    categories = config.get('categories', ['Utility'])
    require(isinstance(categories, list) and 0 < len(categories) <= 16 and
            all(isinstance(c, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9-]{0,63}', c) for c in categories)
            and len(set(categories)) == len(categories), 'Invalid launcher.categories')
    icon = config.get('icon')
    if 'icon' in config:
        require(isinstance(icon, str) and not any(ord(c) < 32 or ord(c) == 127 for c in icon), 'Invalid launcher.icon')
        safe_path(icon)
        require(icon in m['files'], 'Launcher icon must be a packaged file')
    path = 'usr/share/applications/devos-' + m['name'] + '.desktop'
    require(path not in m['files'], 'Launcher conflicts with payload')
    def escape(value):
        return value.replace('\\', '\\\\').replace(' ', '\\s')
    # The executable and package ID contain no desktop Exec field-code characters.
    lines = ['[Desktop Entry]', 'Type=Application', 'Name=' + escape(name),
             'Exec=/usr/bin/dev launch ' + m['name'], 'TryExec=/usr/bin/dev',
             'Terminal=true', 'Categories=' + ';'.join(categories) + ';']
    if comment:
        lines.append('Comment=' + escape(comment))
    if icon is not None:
        lines.append('Icon=' + escape('/' + icon))
    return {path: ('\n'.join(lines) + '\n').encode('utf-8')}


def installed_files(m):
    return dict(m['files'], **m.get('installed_commands', {}), **m.get('installed_launchers', {}))


def manifest_requirements(m):
    require('depends' not in m, 'Use dependencies instead of the unsupported depends field')
    for field in ('dependencies', 'runtime_versions'):
        requirements = m.get(field, {})
        require(isinstance(requirements, dict) and len(requirements) <= 128, 'Invalid ' + field)
        for name, constraint in requirements.items():
            require(isinstance(name, str) and re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._+-]{0,79}', name),
                    'Invalid requirement name')
            if field == 'dependencies':
                require(name != m.get('name'), 'A package cannot depend on itself')
            else:
                require(name in ('node', 'python', 'bash', 'sh'), 'Invalid runtime version requirement')
            require(isinstance(constraint, str) and 0 < len(constraint) <= 256 and
                    (constraint == '*' or all(re.fullmatch(r'\s*(?:~=|==|!=|<=|>=|<|>)\s*[0-9A-Za-z!.*+_-]+\s*', term)
                                             for term in constraint.split(','))),
                    'Invalid version requirement: ' + field)


def manifest_check(m):
    manifest_requirements(m)
    require('ui' not in m, 'The ui field was renamed to window; use window and its permission')
    require(type(m.get('format')) is int and m['format'] in (1, 2), 'Unsupported DPK format')
    version = m.get('manifest_version', 1)
    require(type(version) is int and version in (1, 2) and version == m['format'],
            'Unsupported DPK manifest_version')
    for field in ('display_name', 'short_name', 'description', 'author', 'homepage_url'):
        if field in m:
            require(isinstance(m[field], str) and 0 < len(m[field]) <= 2048,
                    'Invalid ' + field)
    for field in ('optional_permissions', 'host_permissions',
                  'optional_host_permissions', 'content_scripts', 'action'):
        require(field not in m, 'Chrome extension field is not supported by DPK: ' + field)
    for field in ('name', 'version'):
        require(isinstance(m.get(field), str) and
                re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._+-]{0,79}', m[field]),
                'Invalid ' + field)
    require(m.get('arch') in ('all', 'x86_64'), 'Unsupported architecture')
    require(isinstance(m.get('files'), dict) and 0 < len(m['files']) <= 10000,
            'Invalid file inventory')
    for name, spec in m['files'].items():
        safe_path(name)
        require(spec.get('mode') in (0o644, 0o755), 'Invalid file mode')
        require(isinstance(spec.get('sha256'), str) and
                re.fullmatch('[0-9a-f]{64}', spec['sha256']), 'Invalid checksum')
    executables = m.get('executables', [])
    require(isinstance(executables, list), 'Invalid executables')
    for name in executables:
        safe_path(name)
        require(name in m['files'] and m['files'][name]['mode'] == 0o755,
                'Executable is missing or not executable: ' + name)
    launchers = cli_launchers(m)
    if 'installed_commands' in m:
        expected = {name: {'mode': 0o755, 'sha256': hashlib.sha256(data).hexdigest()}
                    for name, data in launchers.items()}
        require(m['installed_commands'] == expected, 'Invalid installed command inventory')
    desktop = desktop_launchers(m)
    if 'installed_launchers' in m:
        expected = {name: {'mode': 0o644, 'sha256': hashlib.sha256(data).hexdigest()}
                    for name, data in desktop.items()}
        require(m['installed_launchers'] == expected, 'Invalid installed launcher inventory')
    icons = m.get('icons', {})
    require(isinstance(icons, dict), 'Invalid icons')
    for size, name in icons.items():
        require(isinstance(size, str) and re.fullmatch(r'[1-9][0-9]{0,3}', size),
                'Invalid icon size')
        safe_path(name)
        require(name in m['files'], 'Icon is missing from payload: ' + name)
    if version == 1:
        require(not any(field in m for field in ('permissions', 'background', 'window')),
                'Runtime features require manifest_version 2')
    else:
        permissions = m.get('permissions')
        require(isinstance(permissions, list) and all(isinstance(p, str) for p in permissions),
                'permissions must be a list of names')
        require(len(set(permissions)) == len(permissions) and
                set(permissions) <= {'background', 'window', 'storage', 'network', 'notifications'}, 'Unknown or duplicate permission')
        prefix = 'opt/apps/' + m['name'] + '/'
        require(all(path.startswith(prefix) for path in m['files']),
                'Format 2 payload must be beneath ' + prefix)
        require('background' in m or 'window' in m or launchers, 'No background, window or CLI entry point')
        for kind in ('background', 'window'):
            if kind not in m:
                require(kind not in permissions, 'Permission has no entry point: ' + kind)
                continue
            entry = m[kind]
            require(kind in permissions, 'Missing permission: ' + kind)
            require(isinstance(entry, dict) and set(entry) <= {'entry_point', 'args', 'type', 'runtime'},
                    'Invalid ' + kind + ' declaration')
            runtime = entry.get('runtime', 'native')
            require(isinstance(runtime, str) and runtime in ('native', 'node', 'bash', 'sh', 'python'),
                    'Unsupported runtime: expected native, node, bash, sh or python')
            if kind == 'window':
                require(entry.get('type') == 'desktop', 'window.type must be desktop')
            else:
                require('type' not in entry, 'background.type is not supported')
            name = entry.get('entry_point')
            require(isinstance(name, str) and name in m['files'], 'Entry point must be a packaged file')
            if runtime == 'native':
                require(name in executables, 'Native entry point must be in executables')
            require(isinstance(entry.get('args', []), list) and len(entry.get('args', [])) <= 64 and
                    all(isinstance(a, str) and '\x00' not in a and len(a) <= 4096
                        for a in entry.get('args', [])), 'Invalid entry point args')


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def prepare_manifest(source):
    source = Path(source)
    manifest = source / 'manifest.json'
    require(manifest.is_file(), 'Missing manifest.json in package source')
    m = json.loads(manifest.read_text(encoding='utf-8'))
    require('installed_commands' not in m, 'installed_commands is reserved for the installer')
    require('installed_launchers' not in m, 'installed_launchers is reserved for the installer')
    require('installed_trust' not in m, 'installed_trust is reserved for the installer')
    require('installed_previous' not in m, 'installed_previous is reserved for the installer')
    m.setdefault('manifest_version', 1)
    require(type(m['manifest_version']) is int and m['manifest_version'] in (1, 2),
            'Unsupported DPK manifest_version')
    m['format'], m['files'] = m['manifest_version'], {}
    payload = source / 'payload'
    require(payload.is_dir() and not payload.is_symlink(), 'payload must be a regular directory')
    total = 0
    for path in sorted(payload.rglob('*')):
        require(not path.is_symlink(), 'Symlinks are not supported')
        if path.is_dir():
            continue
        require(path.is_file(), 'Only regular files are supported')
        name = path.relative_to(payload).as_posix()
        safe_path(name)
        total += path.stat().st_size
        require(total <= LIMIT, 'Package exceeds 256 MiB limit')
        # Explicit executable list works on both Windows and Linux hosts.
        m['files'][name] = {'sha256': digest(path),
                            'mode': 0o755 if name in m.get('executables', []) else 0o644}
    manifest_check(m)
    require(len(json.dumps(m, sort_keys=True).encode()) <= 2 * 1024 * 1024, 'Manifest exceeds 2 MiB limit')
    return m


def build(source, output):
    source, output = Path(source), Path(output)
    require(output.name.endswith(('.dpk', '.tar.gz')), 'Output must end with .dpk or .tar.gz')
    m = prepare_manifest(source)
    payload = source / 'payload'
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, 'w:gz') as tar:
        data = json.dumps(m, sort_keys=True).encode()
        info = tarfile.TarInfo('manifest.json')
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
        for name, spec in m['files'].items():
            path = payload / name
            info = tarfile.TarInfo('payload/' + name)
            info.size, info.mode = path.stat().st_size, spec['mode']
            with path.open('rb') as f:
                tar.addfile(info, f)
    print(output)


def import_tarball(archive, stage):
    """Import data without executing archive content or guessing install scripts."""
    stem = Path(archive).name[:-len('.tar.gz')]
    match = re.fullmatch(r'(.+?)[-_]v?(\d[0-9A-Za-z.+-]*)', stem)
    name, version = match.groups() if match else (stem, '0.0.0')
    require(re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._+-]{0,79}', name) and
            re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._+-]{0,79}', version),
            'Cannot infer package identity; rename archive to name-version.tar.gz')
    m = {'manifest_version': 1, 'format': 1, 'name': name, 'version': version,
         'arch': 'all', 'files': {}, 'executables': [], 'imported_from': 'tar.gz'}
    with tarfile.open(archive, 'r:gz') as tar:
        members, seen, total = [], set(), 0
        for index, member in enumerate(tar):
            require(index < 10000, 'Too many tarball entries')
            relative = member.name
            while relative.startswith('./'):
                relative = relative[2:]
            if member.isdir():
                relative = relative.rstrip('/')
                if relative in ('', '.'):
                    continue
            parts = relative.split('/')
            require(relative and not any(p in ('', '.', '..') for p in parts)
                    and not any(c in relative for c in ('\\', ':', '\x00')),
                    'Unsafe tarball path')
            require(member.isfile() or member.isdir(), 'Tarball supports only regular files and directories; no links')
            require(relative not in seen, 'Duplicate tarball entry')
            seen.add(relative)
            # A broken/misordered DPK must not bypass its manifest/checksum validation.
            require(relative != 'manifest.json', 'manifest.json must be the first archive member')
            if member.isfile():
                total += member.size
                require(0 <= member.size and total <= LIMIT, 'Package exceeds 256 MiB limit')
                members.append((member, parts))
        require(members, 'Tarball has no regular files')
        tops = {parts[0] for _, parts in members}
        strip = len(tops) == 1 and all(len(parts) > 1 for _, parts in members)
        candidates, relative_files = [], []
        for member, parts in members:
            relative = '/'.join(parts[1:] if strip else parts)
            path = 'opt/' + name + '/' + relative
            safe_path(path)
            dest = stage / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as src, dest.open('xb') as out:
                shutil.copyfileobj(src, out, 1024 * 1024)
            mode = 0o755 if member.mode & 0o111 else 0o644
            dest.chmod(mode)
            m['files'][path] = {'sha256': digest(dest), 'mode': mode}
            if mode == 0o755:
                m['executables'].append(path)
            with dest.open('rb') as stream:
                header = stream.read(64)
            elf = header.startswith(b'\x7fELF')
            if elf:
                require(len(header) >= 20 and header[4:6] == b'\x02\x01' and
                        int.from_bytes(header[18:20], 'little') == 62,
                        'Tarball contains an unsupported ELF architecture; expected x86_64')
                m['arch'] = 'x86_64'
            basename = PurePosixPath(relative).name
            if mode == 0o755 and (elf or header.startswith(b'#!')) and not (
                    basename in ('configure', 'install', 'install.sh', 'setup', 'setup.sh', 'uninstall', 'uninstall.sh', 'build.sh', 'autogen.sh')
                    or re.search(r'\.so(?:\.|$)', basename)):
                candidates.append((relative, path))
            relative_files.append(relative)
        # Source distributions are stored, never built or given an inferred command.
        source_markers = {'Makefile', 'CMakeLists.txt', 'Cargo.toml', 'setup.py', 'pyproject.toml', 'configure'}
        source_only = bool(source_markers.intersection(relative_files))
        preferred = [(r, p) for r, p in candidates if r in (name, 'bin/' + name)]
        selected = preferred if preferred else candidates
        if not source_only and len(selected) == 1:
            executable = selected[0][1]
            command = 'usr/bin/' + name
            safe_path(command)
            dest = stage / command
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text('#!/bin/sh\nexec ' + shlex.quote('/' + executable) + ' "$@"\n', newline='\n')
            dest.chmod(0o755)
            m['files'][command] = {'sha256': digest(dest), 'mode': 0o755}
            m['executables'].append(command)
            m['auto_command'] = name
        else:
            m['auto_command'] = None
        m['description'] = 'Automatically imported tarball; stored under /opt/' + name
        manifest_check(m)
        require(len(json.dumps(m).encode()) <= 2 * 1024 * 1024, 'Manifest exceeds 2 MiB limit')
        return m


def unpack(archive, stage, *, allow_plain_tarball=False):
    require(Path(archive).name.endswith(('.dpk', '.tar.gz')),
            'Only .dpk or .tar.gz packages are accepted')
    with tarfile.open(archive, 'r:gz') as tar:
        first = tar.next()
        if (allow_plain_tarball and Path(archive).name.endswith('.tar.gz') and
                first is not None and first.name != 'manifest.json'):
            return import_tarball(archive, stage)
        require(first is not None and first.name == 'manifest.json' and first.isfile()
                and first.size <= 2 * 1024 * 1024,
                'Invalid manifest: package must begin with manifest.json followed by payload/ files')
        m = json.load(tar.extractfile(first))
        require('installed_commands' not in m, 'installed_commands is reserved for the installer')
        require('installed_launchers' not in m, 'installed_launchers is reserved for the installer')
        require('installed_trust' not in m, 'installed_trust is reserved for the installer')
        require('installed_previous' not in m, 'installed_previous is reserved for the installer')
        manifest_check(m)
        seen, total = set(), 0
        while True:
            member = tar.next()
            if member is None:
                break
            require(member.isfile() and member.name.startswith('payload/'),
                    'Only regular payload files are supported')
            name = member.name[len('payload/'):]
            safe_path(name)
            require(name in m['files'] and name not in seen, 'Unexpected or duplicate file')
            total += member.size
            require(total <= LIMIT, 'Package exceeds 256 MiB limit')
            dest = stage / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as src, dest.open('xb') as out:
                shutil.copyfileobj(src, out, 1024 * 1024)
            require(digest(dest) == m['files'][name]['sha256'], 'Checksum mismatch: ' + name)
            dest.chmod(m['files'][name]['mode'])
            seen.add(name)
        require(seen == set(m['files']), 'Missing payload files')
        return m


def target(root, name):
    path = root
    for part in PurePosixPath(name).parts:
        path = path / part
        require(not path.is_symlink(), 'Symlink in destination: ' + str(path))
        if root == Path('/') and os.name == 'posix' and path.exists():
            info = path.stat()
            require(info.st_uid == 0 and info.st_mode & 0o022 == 0,
                    'System package path must be root-owned and not group/world-writable: ' + str(path))
    require(path.resolve().is_relative_to(root), 'Destination escapes root')
    return path


@contextlib.contextmanager
def database(root):
    if root == Path('/'):
        require(hasattr(os, 'geteuid') and os.geteuid() == 0, 'Use sudo dev or su first')
    state = target(root, 'var/lib/dev')
    durable_mkdir(state)
    # Keep the legacy sentinel fail-closed: an older dev may still be running.
    require(not target(root, 'var/lib/dev/lock').exists(),
            'Package database locked by legacy dev; check running processes before recovery')
    lock = target(root, 'var/lib/dev/database.lock')
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        try:
            if os.name == 'nt':
                import msvcrt
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b'\0')
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError('Package database locked or lock unavailable') from exc
        path = target(root, 'var/lib/dev/installed.json')
        recover_transaction(root, path)
        collect_transaction_garbage(root, state)
        db = json.loads(path.read_text()) if path.exists() else {}
        require(isinstance(db, dict), 'Invalid package database')
        yield db, path
    finally:
        # Never unlink: another process could otherwise lock a different inode.
        # Closing releases the OS lock even when the owner exits unexpectedly.
        os.close(fd)


def verify_installed(root, name=None):
    """Audit installed inventory; hashes do not authenticate the publisher."""
    problems = []
    with database(root) as (db, _):
        require(name is None or name in db, 'Package is not installed')
        for package, manifest in sorted(db.items()):
            if name is not None and package != name:
                continue
            manifest_check(manifest)
            require(manifest['name'] == package, 'Package database name mismatch')
            for file, spec in installed_files(manifest).items():
                try:
                    dest = target(root, file)
                    require(dest.is_file(), 'missing or not a regular file')
                    require(digest(dest) == spec['sha256'], 'checksum mismatch')
                    if os.name != 'nt':
                        require(dest.stat().st_mode & 0o7777 == spec['mode'], 'mode mismatch')
                except (ValueError, OSError) as exc:
                    problems.append(package + ': ' + file + ': ' + str(exc))
    require(not problems, 'Installed package verification failed:\n' + '\n'.join(problems))
    print('Installed package verification passed')


def sync_directory(path):
    # Windows is a development host, not the production durability target.
    if os.name != 'nt':
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def durable_mkdir(path):
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o755)
        sync_directory(directory.parent)


def write_json_atomic(value, path):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='db-')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(value, f, indent=2)
            os.chmod(name, 0o644)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save(db, path):
    write_json_atomic(db, path)


def transaction_checkpoint(label):
    """Fault-injection seam for tests; never controlled by environment variables."""


def collect_transaction_garbage(root, state):
    # Called only under the database lock. These directories cannot be active:
    # prepare/unpack precede publication, gc follows the durable detach decision.
    for child in state.iterdir():
        if re.fullmatch(r'(?:prepare|unpack)-[a-z0-9_]{8}|gc-[0-9a-f]{32}', child.name):
            checked = target(root, 'var/lib/dev/' + child.name)
            require(checked.is_dir() and checked.resolve().parent == state.resolve(),
                    'Invalid transaction garbage path')
            shutil.rmtree(checked)
            sync_directory(state)


def durable_copy(src, dest, mode):
    durable_mkdir(dest.parent)
    with dest.open('xb') as out, src.open('rb') as inp:
        shutil.copyfileobj(inp, out, 1024 * 1024)
        dest.chmod(mode)
        out.flush()
        os.fsync(out.fileno())
    sync_directory(dest.parent)


def transaction_scratch(root, journal, file, index):
    return target(root, str(PurePosixPath(file).parent /
                           ('.dev-' + journal['id'] + '-' + str(index))))


def publish_file(src, dest, scratch, mode):
    # A same-directory hard link publishes complete, flushed bytes exclusively.
    # This also works when /usr and /var are on different filesystems.
    durable_copy(src, scratch, mode)
    transaction_checkpoint('copy:' + dest.name)
    os.link(scratch, dest)
    sync_directory(dest.parent)
    transaction_checkpoint('publish:' + dest.name)
    # Keep the second link until the commit decision. It proves which inode
    # this transaction created, even if a conflicting file has identical bytes.


def finish_transaction(txn):
    # Detach before deleting backups: recovery must never see half-cleaned state.
    garbage = txn.parent / ('gc-' + uuid.uuid4().hex)
    os.rename(txn, garbage)
    sync_directory(txn.parent)
    transaction_checkpoint('detached')
    shutil.rmtree(garbage)
    sync_directory(garbage.parent)


def recover_transaction(root, dbpath):
    txn = target(root, 'var/lib/dev/transaction')
    if not txn.exists():
        return
    journal_path = target(root, 'var/lib/dev/transaction/journal.json')
    journal = json.loads(journal_path.read_text())
    if journal.get('version') in (2, 3):
        return recover_replacement(root, dbpath, txn, journal)
    require(journal.get('version') == 1 and journal.get('operation') in ('install', 'remove'),
            'Unsupported transaction journal; recovery refused')
    require(isinstance(journal.get('id'), str) and re.fullmatch('[0-9a-f]{32}', journal['id']),
            'Invalid transaction identity')
    m = journal['manifest']
    manifest_check(m)
    files = installed_files(m)
    before, after = journal['before'], journal['after']
    require(isinstance(before, dict) and isinstance(after, dict), 'Invalid transaction database')
    expected = dict(before)
    if journal['operation'] == 'install':
        require(m['name'] not in expected, 'Invalid install journal')
        expected[m['name']] = m
    else:
        require(expected.get(m['name']) == m, 'Invalid remove journal')
        del expected[m['name']]
    require(expected == after, 'Invalid transaction database transition')
    current = json.loads(dbpath.read_text()) if dbpath.exists() else {}
    require(current == before or current == after, 'Database changed; automatic recovery refused')
    sync_directory(dbpath.parent)
    committed = current == after
    # Preflight the entire rollback before changing anything; preserve user changes.
    if not committed:
        for index, (file, spec) in enumerate(files.items()):
            dest = target(root, file)
            if dest.exists():
                if journal['operation'] == 'install':
                    scratch = transaction_scratch(root, journal, file, index)
                    require(scratch.is_file() and os.path.samefile(scratch, dest),
                            'Recovery conflict; preserve unowned file: ' + file)
                require(dest.is_file() and digest(dest) == spec['sha256'],
                        'Recovery conflict; preserve modified file: ' + file)
                if os.name != 'nt':
                    require(dest.stat().st_mode & 0o7777 == spec['mode'],
                            'Recovery conflict; preserve modified mode: ' + file)
            if journal['operation'] == 'remove':
                backup = target(root, 'var/lib/dev/transaction/payload/' + file)
                require(backup.is_file() and digest(backup) == spec['sha256'],
                        'Missing or corrupt recovery backup: ' + file)
    for index, (file, spec) in enumerate(files.items()):
        scratch = transaction_scratch(root, journal, file, index)
        if not committed:
            dest = target(root, file)
            if journal['operation'] == 'install' and dest.exists():
                dest.unlink()
                sync_directory(dest.parent)
            elif journal['operation'] == 'remove' and not dest.exists():
                if scratch.exists():
                    require(scratch.is_file(), 'Invalid recovery scratch file')
                    scratch.unlink()
                    sync_directory(scratch.parent)
                publish_file(txn / 'payload' / file, dest, scratch, spec['mode'])
            transaction_checkpoint('recover:' + str(index))
        if scratch.exists():
            require(scratch.is_file(), 'Invalid recovery scratch file')
            scratch.unlink()
            sync_directory(scratch.parent)
    finish_transaction(txn)


def run_transaction(root, dbpath, before, m, operation, source=None):
    files = installed_files(m)
    after = dict(before)
    if operation == 'install':
        after[m['name']] = m
    else:
        del after[m['name']]
    journal = {'version': 1, 'id': uuid.uuid4().hex, 'operation': operation,
               'manifest': m, 'before': before, 'after': after}
    txn = target(root, 'var/lib/dev/transaction')
    prepared = Path(tempfile.mkdtemp(dir=dbpath.parent, prefix='prepare-'))
    try:
        for index, (file, spec) in enumerate(files.items()):
            require(not transaction_scratch(root, journal, file, index).exists(), 'Scratch file conflict')
            src = source / file if operation == 'install' else target(root, file)
            durable_copy(src, prepared / 'payload' / file, spec['mode'])
            require(digest(prepared / 'payload' / file) == spec['sha256'],
                    'File changed while preparing transaction: ' + file)
        write_json_atomic(journal, prepared / 'journal.json')
        sync_directory(prepared)
        transaction_checkpoint('prepared')
        os.rename(prepared, txn)
        sync_directory(txn.parent)
        transaction_checkpoint('journal')
        for index, (file, spec) in enumerate(files.items()):
            dest = target(root, file)
            if operation == 'install':
                publish_file(txn / 'payload' / file, dest,
                             transaction_scratch(root, journal, file, index), spec['mode'])
            else:
                require(dest.is_file() and digest(dest) == spec['sha256'],
                        'File changed during removal: ' + file)
                dest.unlink()
                sync_directory(dest.parent)
            transaction_checkpoint('file:' + str(index))
        save(after, dbpath)
        transaction_checkpoint('commit')
        recover_transaction(root, dbpath)
    except Exception:
        # Read the on-disk commit decision, including errors after DB replacement.
        recover_transaction(root, dbpath)
        raise
    finally:
        if prepared.exists():
            shutil.rmtree(prepared)


def matches_file(path, spec):
    return (spec is not None and path.is_file() and digest(path) == spec['sha256'] and
            (os.name == 'nt' or path.stat().st_mode & 0o7777 == spec['mode']))


def replace_file(src, dest, scratch, mode):
    durable_copy(src, scratch, mode)
    swap = scratch.with_name(scratch.name + '-swap')
    os.link(scratch, swap)
    sync_directory(swap.parent)
    transaction_checkpoint('replace-copy:' + dest.name)
    os.replace(swap, dest)
    sync_directory(dest.parent)
    transaction_checkpoint('replace-publish:' + dest.name)


def recover_replacement(root, dbpath, txn, journal):
    require(isinstance(journal.get('id'), str) and re.fullmatch('[0-9a-f]{32}', journal['id']),
            'Invalid replacement journal')
    before, after = journal['before'], journal['after']
    if journal['version'] == 3:
        require(journal.get('operation') == 'batch', 'Invalid batch journal operation')
        old_files, new_files = batch_files(before, after)
    else:
        require(journal.get('operation') in ('upgrade', 'rollback'), 'Invalid replacement operation')
        old, new = journal['old'], journal['new']
        manifest_check(old)
        manifest_check(new)
        require(old['name'] == new['name'], 'Replacement package name mismatch')
        require(isinstance(before, dict) and before.get(old['name']) == old and
                after == dict(before, **{new['name']: new}), 'Invalid replacement database transition')
        old_files, new_files = installed_files(old), installed_files(new)
    current = json.loads(dbpath.read_text()) if dbpath.exists() else {}
    require(current in (before, after), 'Database changed; replacement recovery refused')
    sync_directory(dbpath.parent)
    committed = current == after
    names = sorted(set(old_files) | set(new_files))
    if not committed:
        for index, name in enumerate(names):
            dest = target(root, name)
            scratch = transaction_scratch(root, journal, name, index)
            if name in old_files:
                backup = target(root, 'var/lib/dev/transaction/old/' + name)
                require(matches_file(backup, old_files[name]), 'Missing or corrupt replacement backup: ' + name)
            if dest.exists() and not matches_file(dest, old_files.get(name)):
                require(matches_file(dest, new_files.get(name)) and scratch.is_file() and
                        os.path.samefile(dest, scratch), 'Recovery conflict; preserve modified file: ' + name)
    for index, name in enumerate(names):
        dest = target(root, name)
        scratch = transaction_scratch(root, journal, name, index)
        restore = scratch.with_name(scratch.name + '-restore')
        if not committed:
            if name in old_files and not matches_file(dest, old_files[name]):
                for temp in (restore, restore.with_name(restore.name + '-swap')):
                    if temp.exists():
                        require(not temp.is_symlink() and temp.is_file(), 'Invalid restore scratch')
                        temp.unlink()
                        sync_directory(temp.parent)
                replace_file(txn / 'old' / name, dest, restore, old_files[name]['mode'])
            elif name not in old_files and dest.exists():
                dest.unlink()
                sync_directory(dest.parent)
            transaction_checkpoint('recover:' + str(index))
        for temp in (scratch, scratch.with_name(scratch.name + '-swap'), restore,
                     restore.with_name(restore.name + '-swap')):
            if temp.exists():
                require(not temp.is_symlink() and temp.is_file(), 'Invalid replacement scratch')
                temp.unlink()
                sync_directory(temp.parent)
    finish_transaction(txn)


def run_replacement(root, dbpath, before, old, new, source, operation):
    require(old != new, 'Replacement must change package metadata')
    old_files, new_files = installed_files(old), installed_files(new)
    names = sorted(set(old_files) | set(new_files))
    for name in names:
        dest = target(root, name)
        if name in old_files:
            require(matches_file(dest, old_files[name]), 'Missing or modified file; replacement refused: ' + name)
        else:
            require(not dest.exists(), 'File conflict: ' + name)
    # A different package may own a path even if its file is currently missing.
    for package, manifest in before.items():
        if package != old['name']:
            require(not (set(installed_files(manifest)) & set(new_files)), 'Package ownership conflict: ' + package)
    journal = {'version': 2, 'operation': operation, 'id': uuid.uuid4().hex,
               'old': old, 'new': new, 'before': before,
               'after': dict(before, **{new['name']: new})}
    run_file_transition(root, dbpath, journal, old_files, new_files,
                        {name: source / name for name in new_files})


def batch_files(before, after):
    """Validate the entire ownership map, then collect changed packages' files."""
    require(isinstance(before, dict) and isinstance(after, dict) and before != after and
            set(before) <= set(after), 'Invalid batch database transition')
    changed = {name for name in after if before.get(name) != after[name]}
    maps = []
    for database_state in (before, after):
        owned = set()
        files = {}
        for name, manifest in database_state.items():
            manifest_check(manifest)
            require(name == manifest['name'], 'Batch package identity mismatch')
            inventory = installed_files(manifest)
            require(not (owned & inventory.keys()), 'Batch package ownership conflict: ' + name)
            owned.update(inventory)
            if name in changed:
                files.update(inventory)
        maps.append(files)
    return maps


def run_batch(root, dbpath, before, updates, sources):
    """Commit fully prepared packages together. Caller holds the database lock."""
    require(isinstance(updates, dict) and 0 < len(updates) <= 128, 'Invalid package batch size')
    after = dict(before, **updates)
    old_files, new_files = batch_files(before, after)
    compatibility_module().check_dependencies(after, core_api())
    for name in set(old_files) | set(new_files):
        dest = target(root, name)
        if name in old_files:
            require(matches_file(dest, old_files[name]), 'Missing or modified file; batch refused: ' + name)
        else:
            require(not dest.exists(), 'File conflict: ' + name)
    journal = {'version': 3, 'operation': 'batch', 'id': uuid.uuid4().hex,
               'before': before, 'after': after}
    run_file_transition(root, dbpath, journal, old_files, new_files, sources)


def run_file_transition(root, dbpath, journal, old_files, new_files, sources):
    names = sorted(set(old_files) | set(new_files))
    for index, name in enumerate(names):
        scratch = transaction_scratch(root, journal, name, index)
        require(not any(path.exists() for path in (scratch, scratch.with_name(scratch.name + '-swap'),
                    scratch.with_name(scratch.name + '-restore'), scratch.with_name(scratch.name + '-restore-swap'))),
                'Scratch file conflict')
    txn = target(root, 'var/lib/dev/transaction')
    prepared = Path(tempfile.mkdtemp(dir=dbpath.parent, prefix='prepare-'))
    try:
        for section, files in (('old', old_files), ('new', new_files)):
            for name, spec in files.items():
                src = target(root, name) if section == 'old' else sources[name]
                durable_copy(src, prepared / section / name, spec['mode'])
                require(matches_file(prepared / section / name, spec), 'File changed while preparing replacement')
        write_json_atomic(journal, prepared / 'journal.json')
        sync_directory(prepared)
        transaction_checkpoint('prepared')
        os.rename(prepared, txn)
        sync_directory(txn.parent)
        transaction_checkpoint('journal')
        for index, name in enumerate(names):
            dest = target(root, name)
            scratch = transaction_scratch(root, journal, name, index)
            if name in old_files:
                require(matches_file(dest, old_files[name]), 'File changed during replacement: ' + name)
            if name not in new_files:
                dest.unlink()
                sync_directory(dest.parent)
            elif name not in old_files:
                publish_file(txn / 'new' / name, dest, scratch, new_files[name]['mode'])
            elif old_files[name] != new_files[name]:
                replace_file(txn / 'new' / name, dest, scratch, new_files[name]['mode'])
            transaction_checkpoint('file:' + str(index))
        save(journal['after'], dbpath)
        transaction_checkpoint('commit')
        recover_transaction(root, dbpath)
    except Exception:
        recover_transaction(root, dbpath)
        raise
    finally:
        if prepared.exists():
            shutil.rmtree(prepared)


def package_policy(root):
    path = target(root, 'etc/devos/package-policy.json')
    if not path.exists():
        # Disposable roots support development; real systems fail closed by default.
        return {'version': 1, 'require_signed': root == Path('/'), 'allow_unsigned_override': False}
    policy = json.loads(path.read_text())
    require(isinstance(policy, dict) and set(policy) == {
        'version', 'require_signed', 'allow_unsigned_override'} and
        type(policy['version']) is int and policy['version'] == 1 and
        type(policy['require_signed']) is bool and type(policy['allow_unsigned_override']) is bool,
        'Invalid package policy')
    return policy


def repository_module():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.append('/usr/lib/devos')
    import dev_repository
    return dev_repository


def compatibility_module():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.append('/usr/lib/devos')
    import dev_compat
    return dev_compat


def system_release_module():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.append('/usr/lib/devos')
    import dev_system_release
    return dev_system_release


def core_api():
    return sys.modules.get(__name__) or __import__('types').SimpleNamespace(**globals())


def archive_snapshot(archive, stage):
    archive = Path(archive)
    require(archive.is_file(), 'Archive must be a regular file')
    dest = stage / 'archive' / archive.name
    dest.parent.mkdir()
    total = 0
    with archive.open('rb') as source, dest.open('xb') as out:
        while chunk := source.read(1024 * 1024):
            total += len(chunk)
            require(total <= 300 * 1024 * 1024, 'Archive exceeds 300 MiB limit')
            out.write(chunk)
    return dest


def cache_archive(root, archive):
    sha = digest(archive)
    name = 'var/lib/dev/archives/' + sha + '/' + archive.name
    dest = target(root, name)
    if dest.exists():
        require(dest.is_file() and digest(dest) == sha, 'Corrupt cached archive')
    else:
        durable_mkdir(dest.parent)
        scratch = dest.parent / ('.cache-' + uuid.uuid4().hex)
        try:
            durable_copy(archive, scratch, 0o644)
            os.link(scratch, dest)
            sync_directory(dest.parent)
        finally:
            if scratch.exists():
                scratch.unlink()
                sync_directory(scratch.parent)
    return name


def history_archive(root, item):
    require(isinstance(item, dict) and 'archive' in item and 'sha256' in item,
            'Previous installation has no rollback archive; migrate it before upgrading')
    name = item['archive']
    require(isinstance(name, str) and re.fullmatch(r'var/lib/dev/archives/[0-9a-f]{64}/[^/\\]+', name),
            'Invalid cached archive reference')
    path = target(root, name)
    require(path.is_file() and digest(path) == item['sha256'], 'Missing or corrupt rollback archive')
    return path


def prepare_install(root, archive, stage, db, *, allow_unsigned=False, repository=None, replacement=None):
    """Validate, authenticate and stage one package without publishing installed files."""
    policy = package_policy(root)
    require(not allow_unsigned or policy['allow_unsigned_override'],
            'Unsigned override is disabled by package policy')
    archive = archive_snapshot(archive, stage)
    m = unpack(archive, stage, allow_plain_tarball=True)
    if repository is None and policy['require_signed'] and not allow_unsigned:
        repository = repository_module().Repository(root, core_api())
    if repository is not None:
        try:
            m['installed_trust'] = repository.verify_archive(archive, m, historical=replacement == 'rollback')
        except Exception as exc:
            if type(exc).__module__.startswith(('tuf.', 'securesystemslib.', 'urllib3.')):
                raise ValueError('Package signature verification failed: ' + str(exc)) from exc
            raise
    else:
        m['installed_trust'] = {'type': 'unsigned', 'sha256': digest(archive)}
    old = db.get(m['name'])
    if replacement:
        require(replacement in ('upgrade', 'rollback') and old is not None, 'Package is not installed')
        require(old['version'] != m['version'], 'Requested version is already installed')
        if replacement == 'upgrade':
            try:
                from packaging.version import Version
            except ImportError as exc:
                raise ValueError('Upgrade requires the packaging runtime dependency') from exc
            require(Version(m['version']) > Version(old['version']), 'Upgrade would downgrade; use explicit rollback')
        history_archive(root, old.get('installed_trust', {}))
        m['installed_previous'] = {'name': old['name'], 'version': old['version'],
                                  'archive': old['installed_trust']['archive'],
                                  'sha256': old['installed_trust']['sha256']}
    else:
        require(old is None, 'Already installed; use dev upgrade')
    m['installed_trust']['archive'] = cache_archive(root, archive)
    launchers = cli_launchers(m)
    if launchers:
        m['installed_commands'] = {}
        for name, data in launchers.items():
            dest = stage / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open('xb') as out:
                out.write(data)
            m['installed_commands'][name] = {'mode': 0o755, 'sha256': digest(dest)}
    desktop = desktop_launchers(m)
    if desktop:
        m['installed_launchers'] = {}
        for name, data in desktop.items():
            dest = stage / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open('xb') as out:
                out.write(data)
            m['installed_launchers'][name] = {'mode': 0o644, 'sha256': digest(dest)}
    return m


def install_locked(root, archive, db, dbpath, *, allow_unsigned=False, repository=None, replacement=None):
    with tempfile.TemporaryDirectory(dir=dbpath.parent, prefix='unpack-') as tmp:
        stage = Path(tmp)
        m = prepare_install(root, archive, stage, db, allow_unsigned=allow_unsigned,
                            repository=repository, replacement=replacement)
        compatibility_module().check_install(root, m, stage, db, core_api(),
                                             strict=package_policy(root)['require_signed'])
        old = db.get(m['name'])
        files = installed_files(m)
        if replacement:
            run_replacement(root, dbpath, db, old, m, stage, replacement)
        else:
            for name in files:
                require(not target(root, name).exists(), 'File conflict: ' + name)
            for package, manifest in db.items():
                require(not (set(installed_files(manifest)) & set(files)), 'Package ownership conflict: ' + package)
            run_transaction(root, dbpath, db, m, 'install', stage)
        print('Installed ' + m['name'] + ' ' + m['version'])
        if m.get('imported_from') == 'tar.gz':
            print('Imported into /opt/' + m['name'])
            print('Command: ' + m['auto_command'] if m['auto_command'] else
                  'No command selected automatically; inspect the files in /opt/' + m['name'])


def install(root, archive, *, allow_unsigned=False):
    with database(root) as (db, dbpath):
        install_locked(root, archive, db, dbpath, allow_unsigned=allow_unsigned)


def rollback(root, name):
    if isinstance(name, list):
        require(bool(name), 'At least one rollback package is required')
        if len(name) == 1:
            name = name[0]
        else:
            with database(root) as (db, dbpath):
                compatibility_module()  # Initialize the installed/source module search path.
                import dev_plan
                return dev_plan.rollback(root, name, db, dbpath, core_api())
    with database(root) as (db, dbpath):
        require(name in db and 'installed_previous' in db[name], 'No previous package version is available')
        previous = db[name]['installed_previous']
        require(previous.get('name') == name, 'Previous package identity mismatch')
        archive = history_archive(root, previous)
        install_locked(root, archive, db, dbpath, replacement='rollback')


def remove(root, name):
    with database(root) as (db, dbpath):
        require(name in db, 'Package is not installed')
        compatibility_module().check_dependencies({key: value for key, value in db.items() if key != name}, core_api())
        m = db[name]
        manifest_check(m)
        files = installed_files(m)
        for file, spec in files.items():
            dest = target(root, file)
            require(dest.is_file() and digest(dest) == spec['sha256'],
                    'Missing or modified file; removal refused: ' + file)
            if os.name != 'nt':
                require(dest.stat().st_mode & 0o7777 == spec['mode'],
                        'Modified mode; removal refused: ' + file)
        run_transaction(root, dbpath, db, m, 'remove')
        print('Removed ' + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='/', help='target root (default: /)')
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('build'); p.add_argument('source'); p.add_argument('output')
    p = commands.add_parser('install', help='install .dpk or .tar.gz; import plain tarballs automatically')
    p.add_argument('package', help='path to a .dpk or .tar.gz package')
    p.add_argument('--allow-unsigned', action='store_true', help='explicit development override, only if administrator policy permits')
    p = commands.add_parser('remove'); p.add_argument('name')
    commands.add_parser('list')
    commands.add_parser('update', help='refresh and verify signed TUF repository metadata')
    p = commands.add_parser('trust', help='provision a fingerprint-pinned out-of-band repository root')
    p.add_argument('root_file')
    p.add_argument('--sha256', required=True)
    p.add_argument('--metadata-url', required=True)
    p.add_argument('--targets-url', required=True)
    p.add_argument('--allow-loopback-http', action='store_true')
    p = commands.add_parser('fetch', help='download a package verified by signed repository metadata')
    p.add_argument('name')
    p = commands.add_parser('system-fetch', help='authenticate and download a system release; does not deploy or reboot')
    p.add_argument('--minimum-sequence', type=int, default=0)
    p = commands.add_parser('system-deploy', help='stage the fetched system release into the inactive slot and schedule one trial boot')
    p.add_argument('--baseline', help='system release directory to use as the merge baseline when none is recorded')
    p.add_argument('--cancel', action='store_true', help='cancel a scheduled trial boot and clear the deploy journal')
    p = commands.add_parser('upgrade', help='transactionally upgrade an installed package from the signed repository')
    p.add_argument('name')
    p = commands.add_parser('rollback', help='restore previous package versions together, subject to current trust policy')
    p.add_argument('name', nargs='+')
    commands.add_parser('recover', help='recover interrupted package operations under the database lock')
    p = commands.add_parser('verify', help='audit installed file hashes and Unix modes (requires database lock)')
    p.add_argument('name', nargs='?')
    commands.add_parser('install-system', help='launch the interactive installer from Dev OS live media')
    p = commands.add_parser('mode', help='show the system mode, or set it: desktop (default) or server')
    p.add_argument('action', nargs='?', help='omit to show the mode; "set" to change it (needs root on the real system)')
    p.add_argument('value', nargs='?', help='desktop or server')
    p = commands.add_parser('ext', help='manage desktop extensions: list, install <dir>, uninstall/enable/disable <id>, dedup')
    p.add_argument('action',
                   choices=('list', 'install', 'uninstall', 'enable', 'disable', 'dedup'))
    p.add_argument('target', nargs='?', help='extension id, or source directory for install')
    p = commands.add_parser('info'); p.add_argument('package')
    for command in ('start', 'open', 'launch', 'stop', 'status', '_background'):
        p = commands.add_parser(command)
        p.add_argument('name')
        if command in ('start', 'open', '_background'):
            p.add_argument('--allow', default='', help='explicit comma-separated permission grants for this launch')
        elif command == 'launch':
            p.add_argument('--allow', default=None, help='explicit grants; otherwise ask interactively before opening the window')
    args = parser.parse_args()
    try:
        root = Path(args.root).resolve()
        if args.command == 'trust':
            return repository_module().provision(root, args, sys.modules[__name__])
        elif args.command in ('update', 'fetch', 'upgrade', 'system-fetch'):
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            sys.path.append('/usr/lib/devos')
            import dev_repository
            return dev_repository.dispatch(root, args, sys.modules[__name__])
        elif args.command == 'system-deploy':
            require(args.root == '/', 'system-deploy does not accept --root')
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            sys.path.append('/usr/lib/devos')
            import dev_deploy
            return dev_deploy.dispatch(root, args, sys.modules[__name__])
        elif args.command in ('start', 'open', 'launch', 'stop', 'status', '_background'):
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            sys.path.append('/usr/lib/devos')
            import dev_runtime
            return dev_runtime.dispatch(args, root, sys.modules[__name__])
        elif args.command == 'install-system':
            require(args.root == '/', 'install-system does not accept --root')
            require(Path('/etc/devos-live').is_file(), 'Boot the Dev OS installer USB/ISO first')
            os.execv('/usr/sbin/devos-install', ['devos-install'])
        elif args.command == 'mode':
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            sys.path.append('/usr/lib/devos')
            import dev_settings
            if args.action is None:
                print(dev_settings.read_mode(root))
            else:
                require(args.action == 'set', 'Usage: dev mode [set desktop|server]')
                require(args.value is not None, 'Usage: dev mode set desktop|server')
                dev_settings.write_mode(root, args.value)
                print('Mode set to ' + args.value + ' (takes effect at next boot)')
        elif args.command == 'ext':
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            sys.path.append('/usr/lib/devos')
            import dev_extensions
            return dev_extensions.manage(args, root)
        elif args.command == 'build':
            build(args.source, args.output)
        elif args.command == 'install':
            if re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._+-]{0,79}', args.package) and not Path(args.package).exists():
                require(not args.allow_unsigned, 'Repository installs never allow unsigned override')
                return repository_module().dispatch(root, args, sys.modules[__name__])
            install(root, args.package, allow_unsigned=args.allow_unsigned)
        elif args.command == 'remove':
            remove(root, args.name)
        elif args.command == 'rollback':
            rollback(root, args.name)
        elif args.command == 'verify':
            verify_installed(root, args.name)
        elif args.command == 'recover':
            with database(root):
                print('Package transaction recovery complete')
        elif args.command == 'info':
            with tempfile.TemporaryDirectory() as tmp:
                print(json.dumps(unpack(args.package, Path(tmp), allow_plain_tarball=True), indent=2))
        else:
            require(not target(root, 'var/lib/dev/transaction').exists(),
                    'Package transaction pending; run sudo dev recover first')
            path = target(root, 'var/lib/dev/installed.json')
            db = json.loads(path.read_text()) if path.exists() else {}
            for name, m in sorted(db.items()):
                print(name, m['version'])
    except (ValueError, OSError, tarfile.TarError, KeyError, TypeError, AttributeError) as exc:
        print('dev: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
