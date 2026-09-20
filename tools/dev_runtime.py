"""Per-user native DPK launcher. Requires Linux user namespaces and bubblewrap."""
import contextlib
import functools
import hashlib
import json
import os
import platform
from pathlib import Path
import re
import select
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time


def check(condition, message):
    if not condition:
        raise ValueError(message)


def private_directory(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.lstat()
    check(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and
          stat.S_IMODE(info.st_mode) == 0o700, 'Runtime directory must be owned by you with mode 0700: ' + str(path))
    return path


def locations(root, name):
    key = hashlib.sha256((str(root) + '\0' + name).encode()).hexdigest()[:24]
    run = private_directory(Path('/tmp') / ('devos-runtime-' + str(os.getuid())))
    data = private_directory(Path.home() / '.local/share/devos' / key)
    return run / (key + '.sock'), data


def rpc(path, command):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(2)
        client.connect(str(path))
        client.sendall(command.encode() + b'\n')
        data = bytearray()
        while b'\n' not in data:
            chunk = client.recv(4096)
            if not chunk:
                break
            data.extend(chunk)
            check(len(data) <= 16384, 'Invalid runtime response')
        return json.loads(data)


def metadata(root, name, dev):
    check(not dev.target(root, 'var/lib/dev/transaction').exists(),
          'Package transaction pending; run sudo dev recover first')
    path = dev.target(root, 'var/lib/dev/installed.json')
    db = json.loads(path.read_text()) if path.exists() else {}
    check(name in db, 'Package is not installed')
    m = db[name]
    dev.manifest_check(m)
    check(m['name'] == name and m['format'] == 2, 'This command requires a format 2 app')
    return m


def grants(m, allowed):
    allowed = set(filter(None, allowed.split(',')))
    requested = set(m['permissions'])
    check(allowed == requested,
          'Explicit launch grants required. Review dev info first, then use --allow ' +
          ','.join(sorted(requested)) + '. Requested: ' + ', '.join(sorted(requested)))
    return allowed


def limits(runtime='native'):
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    # V8 reserves a large virtual address space; this is not resident memory.
    address_space = 8 * 1024**3 if runtime == 'node' else 256 * 1024**2
    resource.setrlimit(resource.RLIMIT_AS, (address_space, address_space))
    resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024**2, 4 * 1024**2))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    resource.setrlimit(resource.RLIMIT_NPROC, (256, 256))


def validate_native(path, arch):
    """Check ELF headers without executing the file or using ldd on app code."""
    with Path(path).open('rb') as stream:
        header = stream.read(64)
        if header.startswith(b'#!'):
            return  # Existing native shebang scripts remain supported.
        check(header.startswith(b'\x7fELF'),
              'Native entry must be a Linux ELF binary or a script with a shebang')
        check(len(header) == 64 and header[4:7] == b'\x02\x01\x01',
              'Only 64-bit little-endian ELF binaries are supported')
        check(header[7] in (0, 3), 'Unsupported ELF OS ABI; build for Linux')
        kind, machine = struct.unpack_from('<HH', header, 16)
        check(kind in (2, 3) and machine == 62, 'Only x86_64 ELF executables are supported')
        check(arch == 'x86_64', 'Linux ELF packages must declare arch: x86_64')
        check(platform.machine().lower() in ('x86_64', 'amd64'), 'ELF binary does not match this host CPU')
        offset = struct.unpack_from('<Q', header, 32)[0]
        entry_size, count = struct.unpack_from('<HH', header, 54)
        size = os.fstat(stream.fileno()).st_size
        check(entry_size == 56 and 0 < count < 65535 and offset >= 64 and
              offset + entry_size * count <= size, 'Invalid ELF program headers')
        loader_seen = False
        for index in range(count):
            stream.seek(offset + index * entry_size)
            program = stream.read(entry_size)
            if struct.unpack_from('<I', program)[0] != 3:  # PT_INTERP
                continue
            check(not loader_seen, 'Duplicate ELF interpreter')
            loader_seen = True
            position = struct.unpack_from('<Q', program, 8)[0]
            length = struct.unpack_from('<Q', program, 32)[0]
            check(1 < length <= 4096 and position + length <= size, 'Invalid ELF interpreter')
            stream.seek(position)
            data = stream.read(length)
            check(data.endswith(b'\0') and b'\0' not in data[:-1], 'Invalid ELF interpreter path')
            try:
                loader = Path(data[:-1].decode('utf-8'))
            except UnicodeError:
                raise ValueError('Invalid ELF interpreter path') from None
            check(loader.is_absolute() and '..' not in loader.parts and len(loader.parts) > 2
                  and loader.parts[1] in ('usr', 'lib', 'lib64', 'bin', 'sbin'),
                  'ELF interpreter must be in the system runtime mounts')
            check(loader.is_file() and os.access(loader, os.X_OK),
                  'Missing ELF loader: ' + str(loader) + '. Build for the target OS libc/ABI.')


def runtime_command(entry):
    runtime = entry.get('runtime', 'native')
    path = '/app/' + entry['entry_point']
    if runtime == 'native':
        return [], [path] + entry.get('args', [])
    candidates = {'node': ('/usr/bin/node', '/usr/local/bin/node'),
                  'bash': ('/bin/bash', '/usr/bin/bash'),
                  'sh': ('/bin/sh',), 'python': ('/usr/bin/python3',)}
    check(runtime in candidates, 'Unsupported runtime: ' + str(runtime))
    override = os.environ.get('DEVOS_RUNTIME_' + runtime.upper())
    interpreter = Path(override) if override else next(
        (Path(p) for p in candidates[runtime] if Path(p).is_file()), None)
    check(interpreter is not None and interpreter.is_absolute() and interpreter.is_file()
          and os.access(interpreter, os.X_OK),
          'Runtime ' + runtime + ' is not installed. Install it before launching this app.')
    # Preserve argv[0] basename (e.g. BusyBox sh) while mounting a trusted host-selected binary.
    mapped = '/run/devos-runtime/' + ('python3' if runtime == 'python' else runtime)
    flags = {'node': ['--max-old-space-size=128', '--'],
             'bash': ['--noprofile', '--norc', '--'], 'sh': ['--'], 'python': ['-E', '-s', '--']}
    return ['--dir', '/run/devos-runtime', '--ro-bind', str(interpreter.resolve()), mapped], \
        [mapped] + flags[runtime] + [path] + entry.get('args', [])


def sandbox(snapshot, data, m, kind, notification=None):
    mounts, command = runtime_command(m[kind])
    binary = os.environ.get('DEVOS_BWRAP') or shutil.which('bwrap')
    check(binary and Path(binary).is_file(), 'bubblewrap is required; refusing to run without sandbox')
    args = [binary, '--unshare-all', '--unshare-user', '--die-with-parent', '--new-session', '--cap-drop', 'ALL',
            '--clearenv', '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp']
    if 'network' in m['permissions']:
        args += ['--share-net']
    for directory in ('usr', 'bin', 'sbin', 'lib', 'lib64'):
        source = Path('/') / directory
        if source.is_symlink():
            args += ['--symlink', os.readlink(source), '/' + directory]
        elif source.is_dir():
            args += ['--ro-bind', str(source), '/' + directory]
    args += ['--dir', '/etc']
    for filename in ('/etc/ld.so.cache', '/etc/resolv.conf' if 'network' in m['permissions'] else ''):
        if filename and Path(filename).is_file():
            args += ['--ro-bind', filename, filename]
    if 'network' in m['permissions'] and Path('/etc/ssl/certs').is_dir():
        args += ['--ro-bind', '/etc/ssl/certs', '/etc/ssl/certs']
    args += ['--ro-bind', str(snapshot), '/app']
    if 'storage' in m['permissions']:
        args += ['--bind', str(data), '/data']
    else:
        args += ['--tmpfs', '/data']
    args += ['--setenv', 'HOME', '/data', '--setenv', 'DEVOS_DATA_DIR', '/data',
             '--setenv', 'DEVOS_APP_DIR', '/app/opt/apps/' + m['name'],
             '--setenv', 'PATH', '/run/devos:/usr/bin:/bin', '--setenv', 'LANG', 'C.UTF-8',
             '--chdir', '/app/opt/apps/' + m['name']]
    if kind == 'window':
        display = os.environ.get('DISPLAY', '')
        check(re.fullmatch(r':[0-9]+(?:\.[0-9]+)?', display),
              'A local X11 desktop session is required (DISPLAY=:N). CLI-only images cannot show windows.')
        number = display[1:].split('.')[0]
        x_socket = Path('/tmp/.X11-unix') / ('X' + number)
        check(x_socket.exists(), 'X11 display socket is unavailable')
        args += ['--dir', '/tmp/.X11-unix', '--ro-bind', str(x_socket.resolve()), str(x_socket),
                 '--setenv', 'DISPLAY', display]
        authority = Path(os.environ.get('XAUTHORITY', str(Path.home() / '.Xauthority')))
        if authority.is_file():
            args += ['--ro-bind', str(authority.resolve()), '/tmp/devos-xauthority',
                     '--setenv', 'XAUTHORITY', '/tmp/devos-xauthority']
    if notification is not None:
        endpoint, client = notification
        args += ['--dir', '/run/devos', '--ro-bind', str(endpoint), '/run/devos/notify.sock',
                 '--ro-bind', str(client), '/run/devos/dev-notify',
                 '--setenv', 'DEVOS_NOTIFICATION_SOCKET', '/run/devos/notify.sock']
    return args + mounts + ['--'] + command


@contextlib.contextmanager
def notification_bridge(root, m):
    if 'notifications' not in m['permissions']:
        yield None
        return
    source = Path(__file__).with_name('dev_notifications.py')
    path, _ = locations(root, m['name'])
    with tempfile.TemporaryDirectory(prefix='devos-notify-') as temp:
        endpoint = Path(temp) / 'notify.sock'
        client = Path(temp) / 'dev-notify'
        shutil.copyfile(source, client); client.chmod(0o755)
        broker = subprocess.Popen([sys.executable, str(source), '--broker', str(endpoint), m['name'],
                                   str(path.with_suffix('.notify-rate'))],
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            ready, _, _ = select.select([broker.stdout], [], [], 5)
            check(ready and broker.stdout.readline() == b'READY\n',
                  'Desktop notifications unavailable: a session bus, gdbus and notification daemon are required')
            yield endpoint, client
        finally:
            broker.terminate()
            try:
                broker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                broker.kill(); broker.wait()
            broker.stdout.close(); broker.stderr.close()


@contextlib.contextmanager
def application(root, m, kind, data, dev, output):
    with notification_bridge(root, m) as notification, tempfile.TemporaryDirectory(prefix='devos-app-') as temp:
        snapshot = Path(temp)
        for name, spec in m['files'].items():
            source = dev.target(root, name)
            dest = snapshot / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
            check(dev.digest(dest) == spec['sha256'], 'Installed app changed: ' + name)
            dest.chmod(spec['mode'])
        if m[kind].get('runtime', 'native') == 'native':
            validate_native(snapshot / m[kind]['entry_point'], m['arch'])
        process = subprocess.Popen(sandbox(snapshot, data, m, kind, notification), stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=output, close_fds=True,
                                   preexec_fn=functools.partial(limits, m[kind].get('runtime', 'native')))
        try:
            yield process
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()


def serve(path, data, root, m, dev):
    import fcntl
    # Never use a saved PID to signal a process. The worker owns its Popen and socket.
    with path.with_suffix('.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Background is already running')
        if path.exists():
            path.unlink()
        stopping = False

        def shutdown(*_):
            nonlocal stopping
            stopping = True

        old = {sig: signal.signal(sig, shutdown) for sig in (signal.SIGTERM, signal.SIGINT)}
        try:
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(path)); os.chmod(path, 0o600)
                server.listen(4); server.settimeout(0.2)
                with application(root, m, 'background', data, dev, None) as process:
                    time.sleep(0.2)
                    check(process.poll() is None, 'Background exited during startup; inspect its log')
                    while not stopping and process.poll() is None:
                        try:
                            client, _ = server.accept()
                        except socket.timeout:
                            continue
                        with client:
                            client.settimeout(1)
                            try:
                                command = client.recv(32).decode().strip()
                                if command == 'stop':
                                    stopping = True
                                answer = {'name': m['name'], 'version': m['version'],
                                          'running': process.poll() is None, 'stopping': stopping,
                                          'permissions': m['permissions']}
                                client.sendall(json.dumps(answer).encode() + b'\n')
                            except (OSError, UnicodeError):
                                pass
        finally:
            path.unlink(missing_ok=True)
            for sig, handler in old.items():
                signal.signal(sig, handler)


def launcher_grants(m, allowed):
    check('launcher' in m and 'window' in m, 'App has no desktop launcher')
    if allowed is not None:
        grants(m, allowed)
        return allowed
    check(sys.stdin.isatty(), 'Desktop launch needs an interactive terminal, or explicit --allow permissions')
    requested = ','.join(sorted(m['permissions']))
    print('Open ' + m['launcher'].get('name', m.get('display_name', m['name'])) + '?')
    print('Requested permissions: ' + requested)
    print('This opens the window only; background services are not started automatically.')
    try:
        answer = input('Allow these permissions for this launch? Type yes to continue: ')
    except (EOFError, KeyboardInterrupt):
        return None
    return requested if answer.strip().lower() == 'yes' else None


def dispatch(args, root, dev):
    check(sys.platform == 'linux' and os.getuid() != 0,
          'Run apps as a regular Linux user; sudo is for package installation only')
    check(re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._+-]{0,79}', args.name), 'Invalid app name')
    path, data = locations(root, args.name)
    if args.command in ('status', 'stop'):
        try:
            answer = rpc(path, args.command)
        except (FileNotFoundError, ConnectionRefusedError):
            answer = {'name': args.name, 'running': False}
        if args.command == 'stop' and answer.get('running'):
            for _ in range(50):
                if not path.exists():
                    break
                time.sleep(0.1)
            check(not path.exists(), 'Background is still stopping')
            answer['running'] = False
        print(json.dumps(answer))
        return 0
    m = metadata(root, args.name, dev)
    if args.command == 'launch':
        args.allow = launcher_grants(m, args.allow)
        if args.allow is None:
            print('Launch cancelled.')
            return 1
    grants(m, args.allow)
    kind = 'window' if args.command in ('open', 'launch') else 'background'
    check(kind in m, 'App has no ' + kind + ' entry point')
    runtime_command(m[kind])  # Report missing runtimes before detaching a background worker.
    if m[kind].get('runtime', 'native') == 'native':
        validate_native(dev.target(root, m[kind]['entry_point']), m['arch'])
    if args.command in ('open', 'launch'):
        with application(root, m, 'window', data, dev, None) as process:
            return process.wait()
    if args.command == '_background':
        serve(path, data, root, m, dev)
        return 0
    try:
        running = rpc(path, 'status')
    except (FileNotFoundError, ConnectionRefusedError):
        running = None
    check(not running, 'Background is already running; stop it before starting another version')
    log_path = path.with_suffix('.log')
    with log_path.open('w') as output:
        process = subprocess.Popen([sys.executable, str(Path(dev.__file__).resolve()),
                                    '--root', str(root), '_background', args.name, '--allow', args.allow],
                                   stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                                   start_new_session=True, close_fds=True)
    for _ in range(100):
        if process.poll() is not None:
            raise ValueError('Background failed to start. See ' + str(log_path))
        try:
            answer = rpc(path, 'status')
            print(json.dumps(answer)); print('Log: ' + str(log_path))
            return 0
        except (FileNotFoundError, ConnectionRefusedError, socket.timeout):
            time.sleep(0.1)
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill(); process.wait()
    raise ValueError('Background startup timed out. See ' + str(log_path))
