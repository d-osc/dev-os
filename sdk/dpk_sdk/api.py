import contextlib
import gzip
import io
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from ._core import core

RUNTIMES = ('native', 'node', 'bash', 'sh', 'python')


def validate(source):
    """Return generated archive metadata after hashing and validating source files."""
    return core.prepare_manifest(Path(source))


def inspect_package(package):
    """Verify the entire archive and return its manifest (no installation)."""
    with tempfile.TemporaryDirectory(prefix='dpk-inspect-') as temporary:
        return core.unpack(Path(package), Path(temporary))


def verify(package):
    return inspect_package(package)


def pack(source, output=None, *, force=False):
    """Pack deterministically and publish atomically; never overwrite by default."""
    source = Path(source).resolve()
    manifest = validate(source)
    output = Path(output) if output is not None else source / 'dist' / (
        f"{manifest['name']}-{manifest['version']}-{manifest['arch']}.dpk")
    # Keep the final path lexical until after the symlink check.
    if output.is_symlink():
        raise ValueError('Refusing a symlink output')
    output = output.absolute()
    if output.resolve().is_relative_to((source / 'payload').resolve()):
        raise ValueError('Output must be outside payload/')
    if output.suffix != '.dpk':
        raise ValueError('Output must end with .dpk')
    if output.exists() and not force:
        raise FileExistsError('Output exists; use --force to replace it: ' + str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.dpk-pack-', dir=output.parent) as temporary:
        temporary = Path(temporary)
        raw = temporary / 'raw.dpk'
        finished = temporary / 'finished.dpk'
        with contextlib.redirect_stdout(io.StringIO()):
            core.build(source, raw)
        # The core writes sorted tar members with zero timestamps. Normalize gzip's
        # filename/time as well so output path and build time cannot change the bytes.
        with gzip.open(raw, 'rb') as src, finished.open('wb') as dest:
            with gzip.GzipFile(filename='', mode='wb', fileobj=dest, mtime=0, compresslevel=9) as stream:
                shutil.copyfileobj(src, stream, 1024 * 1024)
            dest.flush(); os.fsync(dest.fileno())
        inspect_package(finished)  # Also catches files changing during the build.
        if force:
            os.replace(finished, output)
        else:
            # Atomic no-clobber publication on the same filesystem.
            os.link(finished, output)
    return output


def _asset(name):
    # importlib.resources supports both wheel installs and zipapps.
    from importlib.resources import files
    packaged = files('dpk_sdk').joinpath('assets', name)
    if packaged.is_file():
        return packaged.read_text(encoding='utf-8')
    repository = Path(__file__).resolve().parents[2]
    mapping = {
        'background.py': 'examples/desktop-counter/payload/opt/apps/desktop-counter/background.py',
        'background.cjs': 'examples/desktop-counter/payload/opt/apps/desktop-counter/background.cjs',
        'window.py': 'examples/desktop-counter/payload/opt/apps/desktop-counter/window.py',
        'background.c': 'examples/native-counter/background.c',
        'window.c': 'examples/native-counter/window.c',
        'label.c': 'examples/native-counter/label.c',
    }
    return (repository / mapping[name]).read_text(encoding='utf-8')


def init_project(directory, *, name=None, runtime='python', kind='both',
                 background_runtime=None, window_runtime=None, permissions=()):
    directory = Path(directory)
    name = name or directory.name
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', name):
        raise ValueError('Use a lowercase package name: letters, digits and hyphens (max 64 characters)')
    if kind not in ('background', 'window', 'both'):
        raise ValueError('kind must be background, window or both')
    selected = {'background': background_runtime or runtime, 'window': window_runtime or runtime}
    if any(value not in RUNTIMES for value in selected.values()):
        raise ValueError('Unsupported runtime')
    if set(permissions) - {'network', 'notifications', 'storage'}:
        raise ValueError('Additional permissions: network, notifications, storage')
    if directory.exists():
        raise FileExistsError('Project directory already exists: ' + str(directory))
    directory.mkdir(parents=True)
    prefix = 'opt/apps/' + name
    payload = directory / 'payload' / prefix
    payload.mkdir(parents=True)
    kinds = ('background', 'window') if kind == 'both' else (kind,)
    manifest = {'manifest_version': 2, 'name': name, 'display_name': name.replace('-', ' ').title(),
                'version': '0.1.0', 'arch': 'all', 'description': 'A Dev OS counter starter app',
                'permissions': sorted(set(kinds) | {'storage'} | set(permissions)), 'executables': []}
    native = False

    def write(relative, text):
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8', newline='\n')

    for entry_kind in kinds:
        chosen = selected[entry_kind]
        if chosen == 'native':
            native = True
            manifest['arch'] = 'x86_64'
            filename = 'bin/' + entry_kind
            manifest['executables'].append(prefix + '/' + filename)
            write('src/' + entry_kind + '.c', _asset(entry_kind + '.c'))
            if entry_kind == 'window':
                write('src/label.c', _asset('label.c'))
        elif entry_kind == 'background':
            if chosen in ('python', 'node'):
                filename = 'background.py' if chosen == 'python' else 'background.cjs'
                write('payload/' + prefix + '/' + filename, _asset(filename))
            else:
                filename = 'background.sh'
                write('payload/' + prefix + '/' + filename, r'''set -eu
cd "$DEVOS_DATA_DIR"
ticks=0
if [ -f counter.json ]; then
    ticks=$(sed -n 's/.*"ticks": *\([0-9][0-9]*\).*/\1/p' counter.json)
fi
case "$ticks" in ''|*[!0-9]*) ticks=0;; esac
while :; do
    ticks=$((ticks + 1))
    printf '{"ticks": %s, "updated": %s}\n' "$ticks" "$(date +%s)" > counter.new
    mv counter.new counter.json
    sleep 1
done
''')
        else:
            window = _asset('window.py').replace("b'Dev Counter - Native DPK App'", repr(manifest['display_name'].encode()))
            write('payload/' + prefix + '/window.py', window)
            if chosen == 'python':
                filename = 'window.py'
            elif chosen == 'node':
                filename = 'window.cjs'
                write('payload/' + prefix + '/' + filename,
                      "const {spawnSync} = require('node:child_process');\n"
                      "const r = spawnSync('/usr/bin/python3', ['-E', '-s', process.env.DEVOS_APP_DIR + '/window.py', ...process.argv.slice(2)], {stdio:'inherit'});\n"
                      "if (r.error) console.error(r.error.message);\nprocess.exit(r.status ?? 1);\n")
            else:
                filename = 'window.sh'
                write('payload/' + prefix + '/' + filename,
                      'set -eu\nexec /usr/bin/python3 -E -s "$DEVOS_APP_DIR/window.py" "$@"\n')
        entry = {'runtime': chosen, 'entry_point': prefix + '/' + filename}
        if entry_kind == 'window':
            entry['type'] = 'desktop'
        manifest[entry_kind] = entry
    write('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    if native:
        write('build.py', NATIVE_BUILD)
    write('.gitignore', 'dist/\n__pycache__/\n*.pyc\n')
    write('README.md', '# ' + manifest['display_name'] + '\n\n'
          'This is a counter starter. Edit manifest.json and payload/ for your app.\n\n'
          + ('Compile on Linux first: `python3 build.py` (C compiler; X11 headers/library for windows).\n\n' if native else '')
          + 'Pack: `dpk validate .` then `dpk pack .`\n\n'
          + 'Install the archive on Dev OS with `sudo dev install <archive.dpk>`.\n'
          + 'Launch with `dev start ' + name + ' --allow ' + ','.join(manifest['permissions']) + '` (background)\n'
          + 'or `dev open ' + name + ' --allow ' + ','.join(manifest['permissions']) + '` (window).\n\n'
          + 'The starter window uses Python 3 + libX11 even when launched through Node/Bash/sh.\n'
          + 'Native C windows use libX11. A local X11 desktop session is required.\n'
          + 'Storage permission keeps counter data across restarts. Other permissions are opt-in.\n'
          + 'Pack does not install runtimes, compile code, or run package scripts.\n')
    return directory.absolute()


NATIVE_BUILD = '''import json, os, subprocess
from pathlib import Path
root = Path(__file__).resolve().parent
manifest = json.loads((root / 'manifest.json').read_text())
cc = os.environ.get('CC', 'cc')
for kind in ('background', 'window'):
    entry = manifest.get(kind, {})
    if entry.get('runtime') != 'native': continue
    output = root / 'payload' / entry['entry_point']
    output.parent.mkdir(parents=True, exist_ok=True)
    flags = ['-O2', '-Wall', '-Wextra', '-Werror']
    if kind == 'background': flags += ['-static']
    else:
        if os.environ.get('DEVOS_X11_INCLUDE'): flags += ['-I', os.environ['DEVOS_X11_INCLUDE']]
        flags += [str(root / 'src/label.c'), '-l:libX11.so.6']
    subprocess.run([cc, str(root / 'src' / (kind + '.c')), *flags, '-o', str(output)], check=True)
'''
