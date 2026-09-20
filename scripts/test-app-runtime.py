#!/usr/bin/env python3
"""Exercise real Linux sandboxing, background lifecycle, storage and native X11 UI."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project / 'tools'))
import dev_runtime

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--variant', choices=['python', 'node-bash', 'native'], default='python')
variant = parser.parse_args().variant
report = {'passed': False, 'variant': variant, 'checks': []}
output = project / ('out/runtime-tests' if variant == 'python' else 'out/runtime-tests-' + variant)
output.mkdir(parents=True, exist_ok=True)


def run(root, *args, success=True, env=None):
    result = subprocess.run([sys.executable, str(project / 'tools/dev.py'), '--root', str(root), *args],
                            text=True, capture_output=True, timeout=20, env=env)
    if (result.returncode == 0) != success:
        raise AssertionError(str(args) + '\n' + result.stdout + result.stderr)
    return result


try:
    with tempfile.TemporaryDirectory(prefix='devos-runtime-test-') as temporary:
        temp = Path(temporary)
        root = temp / 'root'
        source = temp / 'source'
        if variant == 'native':
            subprocess.run([sys.executable, str(project / 'scripts/build-native-example.py'),
                            '--output-dir', str(source), '--package', str(temp / 'native.dpk')], check=True)
        else:
            shutil.copytree(project / 'examples/desktop-counter', source)
        if variant == 'node-bash':
            shutil.copyfile(source / 'manifest.node-bash.json', source / 'manifest.json')
        manifest = json.loads((source / 'manifest.json').read_text())
        app_name = manifest['name']
        report['app'] = app_name
        manifest['window']['args'] = ['--test']
        (source / 'manifest.json').write_text(json.dumps(manifest))
        archive = temp / (app_name + '.dpk')
        run(root, 'build', str(source), str(archive))
        shutil.copyfile(archive, output / (app_name + '.dpk'))
        run(root, 'install', str(archive))
        grant = 'background,window,storage'
        try:
            run(root, 'start', app_name, success=False)
            report['checks'].append('no launch without explicit grants')
            runtime_name = manifest['background']['runtime']
            if runtime_name != 'native':
                missing_runtime = dict(os.environ, **{'DEVOS_RUNTIME_' + runtime_name.upper(): '/no-such-devos-runtime'})
                denied = run(root, 'start', app_name, '--allow', grant, success=False, env=missing_runtime)
                assert 'Runtime ' + runtime_name + ' is not installed' in denied.stderr
                report['checks'].append('missing selected runtime fails before background detaches')
            missing = dict(os.environ, DEVOS_BWRAP='/no-such-devos-bwrap')
            run(root, 'start', app_name, '--allow', grant, success=False, env=missing)
            report['checks'].append('missing sandbox fails closed')
            run(root, 'start', app_name, '--allow', grant)
            run(root, 'start', app_name, '--allow', grant, success=False)
            report['checks'].append('background start and duplicate start rejection')
            _, data = dev_runtime.locations(root, app_name)
            time.sleep(1.2)
            initial = json.loads((data / 'counter.json').read_text())['ticks']
            run(root, 'open', app_name, '--allow', grant)
            check_image = data / 'window.ppm'
            if not check_image.is_file():
                raise AssertionError('Native desktop screenshot was not produced')
            shutil.copyfile(check_image, output / 'native-window.ppm')
            status = json.loads(run(root, 'status', app_name).stdout)
            assert status['running']
            assert json.loads((data / 'counter.json').read_text())['ticks'] > initial
            report['checks'].append('native X11 window rendered; closing UI leaves background running')
            run(root, 'stop', app_name)
            stopped = (data / 'counter.json').read_text()
            time.sleep(1.2)
            assert (data / 'counter.json').read_text() == stopped
            assert not json.loads(run(root, 'status', app_name).stdout)['running']
            run(root, 'start', app_name, '--allow', grant)
            time.sleep(1.2)
            assert json.loads((data / 'counter.json').read_text())['ticks'] > json.loads(stopped)['ticks']
            report['checks'].append('stop halts background; storage persists on restart')
        finally:
            run(root, 'stop', app_name)

        sentinel = temp / 'private-host-file'
        sentinel.write_text('private')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); listener.listen(4)
            port = listener.getsockname()[1]
            for allowed in (False, True):
                source = temp / ('probe-' + str(allowed))
                payload = source / 'payload/opt/apps/permission-probe'
                payload.mkdir(parents=True)
                code = f'''#!/usr/bin/python3
import json, os, socket, subprocess, time
from pathlib import Path
result = {{'private_host_file_hidden': not Path({str(sentinel)!r}).exists()}}
result['host_process_hidden'] = not Path('/proc/{os.getpid()}').exists()
result['host_environment_hidden'] = 'DEVOS_TEST_SECRET' not in os.environ
status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines())
result['no_new_privileges'] = status['NoNewPrivs'].strip() == '1'
result['no_effective_capabilities'] = int(status['CapEff'].strip(), 16) == 0
try:
    Path('/app/opt/apps/permission-probe/unauthorized-write').write_text('bad')
    result['app_read_only'] = False
except OSError:
    result['app_read_only'] = True
try:
    connection = socket.create_connection(('127.0.0.1', {port}), timeout=1)
    connection.close()
    result['network'] = True
except OSError:
    result['network'] = False
Path('/data/probe.txt').write_text('persistent?')
subprocess.Popen(['/usr/bin/python3', '-c', "import time; from pathlib import Path;\\nwhile True: Path('/data/child-tick').write_text(str(time.time_ns())); time.sleep(0.1)"])
print(json.dumps(result), flush=True)
while True: time.sleep(1)
'''
                (payload / 'probe.py').write_text(code)
                permissions = ['background'] + (['network', 'storage'] if allowed else [])
                manifest = {'manifest_version': 2, 'name': 'permission-probe', 'version': '1', 'arch': 'all',
                            'permissions': permissions, 'background': {'entry_point': 'opt/apps/permission-probe/probe.py'},
                            'executables': ['opt/apps/permission-probe/probe.py']}
                (source / 'manifest.json').write_text(json.dumps(manifest))
                probe_root = temp / ('probe-root-' + str(allowed))
                archive = temp / ('probe-' + str(allowed) + '.dpk')
                run(probe_root, 'build', str(source), str(archive))
                run(probe_root, 'install', str(archive))
                try:
                    run(probe_root, 'start', 'permission-probe', '--allow', ','.join(permissions),
                        env=dict(os.environ, DEVOS_TEST_SECRET='must-not-reach-the-app'))
                    path, data = dev_runtime.locations(probe_root, 'permission-probe')
                    for _ in range(30):
                        log = path.with_suffix('.log').read_text()
                        if 'private_host_file_hidden' in log:
                            break
                        time.sleep(0.1)
                    actual = json.loads(log.splitlines()[0])
                    assert actual == {'private_host_file_hidden': True, 'network': allowed,
                                      'host_process_hidden': True, 'host_environment_hidden': True,
                                      'no_new_privileges': True, 'no_effective_capabilities': True,
                                      'app_read_only': True}, actual
                    assert (data / 'probe.txt').exists() == allowed
                    report['checks'].append('network/storage ' + ('granted' if allowed else 'denied') + '; private host file inaccessible')
                    report['checks'].append('host PID/environment hidden, capabilities dropped, no-new-privileges, app read-only')
                    if allowed:
                        child_tick = data / 'child-tick'
                        for _ in range(30):
                            if child_tick.exists():
                                break
                            time.sleep(0.1)
                        assert child_tick.exists(), 'Child process did not start'
                        run(probe_root, 'stop', 'permission-probe')
                        stopped_tick = child_tick.read_text()
                        time.sleep(0.5)
                        assert child_tick.read_text() == stopped_tick, 'Descendant escaped app stop'
                        report['checks'].append('stopping app also stops its child process')
                finally:
                    run(probe_root, 'stop', 'permission-probe')
        report['passed'] = True
except Exception as exc:
    report['error'] = str(exc)
    raise
finally:
    (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
