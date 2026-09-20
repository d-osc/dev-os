"""Static target compatibility checks. Never execute a package or invoke ldd."""
import json
import os
from pathlib import Path, PurePosixPath

RUNTIMES = {'node': 'usr/bin/node', 'python': 'usr/bin/python3', 'bash': 'bin/bash', 'sh': 'bin/sh'}
LIBRARIES = ['lib', 'lib64', 'usr/lib', 'usr/lib64']


def resolve_base(root, name, dev):
    """Resolve symlinks using target-root semantics, not the host filesystem."""
    parts = list(PurePosixPath(name).parts)
    resolved = []
    links = 0
    while parts:
        part = parts.pop(0)
        if part in ('/', '', '.'):
            continue
        if part == '..':
            dev.require(bool(resolved), 'Compatibility path escapes target root')
            resolved.pop()
            continue
        path = root.joinpath(*resolved, part)
        if path.is_symlink():
            links += 1
            dev.require(links <= 40, 'Too many target symlinks')
            link = PurePosixPath(os.readlink(path))
            if link.is_absolute():
                resolved = []
            parts = list(link.parts) + parts
        else:
            resolved.append(part)
    return root.joinpath(*resolved)


def check_dependencies(database, dev):
    if not any(m.get('dependencies') for m in database.values()):
        return
    try:
        from packaging.specifiers import SpecifierSet
        from packaging.version import Version
    except ImportError as exc:
        raise ValueError('Dependency checking requires packaging') from exc
    for name, manifest in database.items():
        dev.manifest_requirements(manifest)
        for dependency, requirement in manifest.get('dependencies', {}).items():
            dev.require(dependency in database, f'Missing dependency: {name} requires {dependency} {requirement}')
            version = Version(database[dependency]['version'])
            dev.require(version in SpecifierSet('' if requirement == '*' else requirement),
                        f'Dependency conflict: {name} requires {dependency} {requirement}, found {version}')


def check_install(root, manifest, stage, database, dev, *, strict=False, planned_files=None, removed_files=()):
    check_dependencies(dict(database, **{manifest['name']: manifest}), dev)
    path = dev.target(root, 'usr/lib/devos/platform.json')
    platform = json.loads(path.read_text()) if path.exists() else None
    if platform is not None:
        dev.require(isinstance(platform, dict) and platform.get('arch') == 'x86_64', 'Unsupported target platform')
        dev.require(manifest['arch'] in ('all', platform['arch']), 'Package architecture does not match target')
    elif manifest['arch'] != 'all':
        raise ValueError('Target platform metadata is required for architecture-specific packages')
    entries = [manifest[kind] for kind in ('background', 'window') if kind in manifest]
    entries += list(manifest.get('cli', {}).get('commands', {}).values())
    required = {entry.get('runtime', 'native') for entry in entries} - {'native'}
    required.update(manifest.get('runtime_versions', {}))
    if strict or platform is not None:
        for runtime in required:
            binary = resolve_base(root, RUNTIMES[runtime], dev)
            dev.require(binary.is_file() and (os.name == 'nt' or binary.stat().st_mode & 0o111),
                        'Missing target runtime: ' + runtime)
    if manifest.get('runtime_versions'):
        from packaging.specifiers import SpecifierSet
        from packaging.version import Version
        for runtime, constraint in manifest['runtime_versions'].items():
            version = (platform or {}).get('runtimes', {}).get(runtime)
            dev.require(isinstance(version, str), 'Missing target runtime version: ' + runtime)
            dev.require(Version(version) in SpecifierSet('' if constraint == '*' else constraint),
                        f'Incompatible runtime: {runtime} {version} does not satisfy {constraint}')
    inspectors = {}
    def inspect(file):
        key = str(file)
        if key in inspectors:
            return inspectors[key]
        from elftools.elf.elffile import ELFFile
        with file.open('rb') as stream:
            elf = ELFFile(stream)
            dev.require(elf.elfclass == 64 and elf.little_endian and elf['e_machine'] == 'EM_X86_64',
                        'Only x86_64 Linux ELF is supported: ' + str(file))
            info = {'needed': [], 'paths': [], 'versions': {}, 'defines': set(), 'interpreter': None}
            needs_versions = False
            for segment in elf.iter_segments():
                if segment['p_type'] == 'PT_INTERP':
                    info['interpreter'] = segment.get_interp_name()
                if segment['p_type'] == 'PT_DYNAMIC':
                    for tag in segment.iter_tags():
                        if tag.entry.d_tag == 'DT_NEEDED':
                            info['needed'].append(tag.needed)
                        elif tag.entry.d_tag in ('DT_RUNPATH', 'DT_RPATH'):
                            info['paths'].extend(getattr(tag, 'runpath', getattr(tag, 'rpath', '')).split(':'))
                        elif tag.entry.d_tag == 'DT_VERNEED':
                            needs_versions = True
            section = elf.get_section_by_name('.gnu.version_r')
            dev.require(not needs_versions or section is not None,
                        'Unsupported ELF version table without section headers')
            if section is not None:
                for dependency, auxiliaries in section.iter_versions():
                    info['versions'][dependency.name] = {item.name for item in auxiliaries if not item['vna_flags'] & 2}
            section = elf.get_section_by_name('.gnu.version_d')
            if section is not None:
                for _, auxiliaries in section.iter_versions():
                    info['defines'].update(item.name for item in auxiliaries)
        inspectors[key] = info
        return info
    def candidate(name):
        relative = PurePosixPath(name).as_posix().lstrip('/')
        # Resolve . and .. before testing inventory membership.
        normalized = []
        for part in PurePosixPath(relative).parts:
            if part == '..':
                dev.require(bool(normalized), 'Library path escapes target root')
                normalized.pop()
            elif part not in ('', '.'):
                normalized.append(part)
        relative = '/'.join(normalized)
        if planned_files is not None and relative in planned_files:
            return planned_files[relative], relative
        if relative in manifest['files']:
            return stage / relative, relative
        if relative in removed_files:
            return None, relative
        file = resolve_base(root, relative, dev)
        return (file, relative) if file.is_file() else (None, relative)
    visited = set()
    def validate_elf(file, relative):
        if str(file) in visited:
            return
        visited.add(str(file))
        dev.require(len(visited) <= 1024, 'Too many ELF dependencies')
        info = inspect(file)
        if info['interpreter']:
            loader, loader_name = candidate(info['interpreter'])
            dev.require(loader is not None, 'Missing ELF interpreter: ' + info['interpreter'])
            validate_elf(loader, loader_name)
        search = []
        origin = '/' + str(PurePosixPath(relative).parent)
        for path in info['paths']:
            expanded = path.replace('${ORIGIN}', origin).replace('$ORIGIN', origin)
            dev.require(expanded.startswith('/') and '$' not in expanded,
                        'Unsupported relative or dynamic ELF library search path')
            search.append(expanded)
        search += (platform or {}).get('library_dirs', LIBRARIES)
        for needed in info['needed']:
            dev.require('/' not in needed and '\\' not in needed, 'Unsupported path in ELF DT_NEEDED')
            provider = None
            for directory in search:
                provider, provider_name = candidate(str(PurePosixPath(directory) / needed))
                if provider is not None:
                    break
            dev.require(provider is not None, 'Missing shared library: ' + needed + ' required by ' + relative)
            provider_info = inspect(provider)
            missing = info['versions'].get(needed, set()) - provider_info['defines']
            dev.require(not missing, 'Missing ABI symbol versions in ' + needed + ': ' + ', '.join(sorted(missing)))
            validate_elf(provider, provider_name)
    for name, spec in manifest['files'].items():
        file = stage / name
        with file.open('rb') as stream:
            header = stream.read(4096)
        if header.startswith(b'\x7fELF'):
            dev.require(manifest['arch'] == 'x86_64', 'Native ELF payload must declare arch: x86_64')
            dev.require(platform is not None, 'Target platform metadata is required for ELF packages')
            try:
                validate_elf(file, name)
            except ImportError as exc:
                raise ValueError('ELF validation requires pyelftools') from exc
            except Exception as exc:
                if type(exc).__module__.startswith(('elftools.', 'construct.')):
                    raise ValueError('Invalid ELF metadata: ' + str(exc)) from exc
                raise
        elif spec['mode'] == 0o755 and header.startswith(b'MZ'):
            raise ValueError('Windows executable cannot run as a Linux program: ' + name)
        elif strict and spec['mode'] == 0o755 and header.startswith(b'#!'):
            raw = header.split(b'\n', 1)[0][2:]
            dev.require(b'\r' not in raw, 'Invalid CRLF script interpreter')
            first = raw.strip().decode('utf-8')
            dev.require(bool(first), 'Invalid script interpreter')
            interpreter = first.split()[0]
            binary = resolve_base(root, interpreter, dev)
            dev.require(interpreter.startswith('/') and binary.is_file() and
                        (os.name == 'nt' or binary.stat().st_mode & 0o111),
                        'Missing script interpreter: ' + interpreter)
            if PurePosixPath(interpreter).name == 'env':
                arguments = first.split()[1:]
                dev.require(len(arguments) == 1 and not arguments[0].startswith('-') and '=' not in arguments[0],
                            'Unsupported env shebang; use one explicit interpreter')
                command = arguments[0]
                dev.require('/' not in command and any(
                    resolve_base(root, directory + '/' + command, dev).is_file() for directory in ('usr/bin', 'bin')),
                    'Missing env script runtime: ' + command)
