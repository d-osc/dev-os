#!/usr/bin/env python3
"""Run inside dbus-run-session; uses a real, test-owned Dunst notification daemon."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project / 'tools'))
import dev_runtime

output = project / 'out/notification-tests'
output.mkdir(parents=True, exist_ok=True)
report = {'passed': False, 'checks': []}
daemon = None


def command(root, *args, success=True):
    result = subprocess.run([sys.executable, str(project / 'tools/dev.py'), '--root', str(root), *args],
                            capture_output=True, text=True, timeout=20)
    if (result.returncode == 0) != success:
        raise AssertionError(str(args) + '\n' + result.stdout + result.stderr)
    return result


def dbus(method):
    return subprocess.run(['gdbus', 'call', '--session', '--dest', 'org.freedesktop.Notifications',
                           '--object-path', '/org/freedesktop/Notifications', '--method', method],
                          capture_output=True, text=True, timeout=3)


try:
    if not os.environ.get('DEVOS_TEST_DUNST'):
        raise RuntimeError('Set DEVOS_TEST_DUNST to a Dunst executable; run this script inside dbus-run-session')
    if dbus('org.freedesktop.Notifications.GetCapabilities').returncode == 0:
        raise RuntimeError('Use a private dbus-run-session; refusing to replace an existing notification daemon')
    with tempfile.TemporaryDirectory(prefix='devos-notification-test-') as temp:
        temp = Path(temp)
        source = temp / 'source'
        shutil.copytree(project / 'examples/notification-demo', source)
        manifest = json.loads((source / 'manifest.json').read_text())
        manifest['permissions'].append('storage')
        (source / 'manifest.json').write_text(json.dumps(manifest))
        script = source / 'payload/opt/apps/notification-demo/background.py'
        script.write_text('''import json, os, shutil, subprocess, time
from pathlib import Path
answer = {'has_client': shutil.which('dev-notify') is not None,
          'has_display': 'DISPLAY' in os.environ,
          'has_dbus_address': 'DBUS_SESSION_BUS_ADDRESS' in os.environ}
if answer['has_client']:
    first = subprocess.run(['dev-notify', 'Dev OS ทดสอบแจ้งเตือน', 'Native notification from sandbox'], capture_output=True, text=True)
    answer['first'] = json.loads(first.stdout)
    second = subprocess.run(['dev-notify', 'Too soon', 'Rate limit test'], capture_output=True, text=True)
    answer['limited'] = second.returncode != 0 and 'rate limit' in second.stderr
Path('/data/result.json').write_text(json.dumps(answer))
while True: time.sleep(1)
''')
        archive = temp / 'demo.dpk'
        root = temp / 'root'
        command(root, 'build', str(source), str(archive))
        command(root, 'install', str(archive))
        grant = 'background,notifications,storage'
        command(root, 'start', 'notification-demo', '--allow', grant, success=False)
        assert not json.loads(command(root, 'status', 'notification-demo').stdout)['running']
        report['checks'].append('missing desktop notification service fails closed')
        config = temp / 'dunstrc'
        config.write_text('[global]\nforce_xwayland = true\nfont = Sans 12\n')
        with (output / 'daemon.log').open('w') as log:
            daemon = subprocess.Popen([os.environ['DEVOS_TEST_DUNST'], '-conf', str(config), '-verbosity', 'debug'],
                                      stdout=log, stderr=log)
            for _ in range(30):
                if dbus('org.freedesktop.Notifications.GetCapabilities').returncode == 0:
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError('Test notification daemon did not start')
            try:
                command(root, 'start', 'notification-demo', '--allow', 'background,storage', success=False)
                report['checks'].append('notifications grant is mandatory')
                command(root, 'start', 'notification-demo', '--allow', grant)
                _, data = dev_runtime.locations(root, 'notification-demo')
                for _ in range(50):
                    if (data / 'result.json').exists():
                        break
                    time.sleep(0.1)
                result = json.loads((data / 'result.json').read_text())
                assert result['first']['ok'] and result['first']['id'] > 0, result
                assert result['limited'] and not result['has_display'] and not result['has_dbus_address'], result
                report['checks'].append('real notification daemon accepts Unicode notification and returns an ID')
                report['checks'].append('sandbox has notification broker only, without display or session bus access')
                report['checks'].append('second notification is rate-limited')
                # Verify the real daemon rendered a window after accepting the request.
                time.sleep(0.3)
                assert 'Window dimensions' in (output / 'daemon.log').read_text()
                report['checks'].append('test-owned desktop daemon renders a notification window')
            finally:
                command(root, 'stop', 'notification-demo')
            manifest['permissions'].remove('notifications')
            (source / 'manifest.json').write_text(json.dumps(manifest))
            denied_root = temp / 'denied-root'
            command(denied_root, 'build', str(source), str(archive))
            command(denied_root, 'install', str(archive))
            try:
                command(denied_root, 'start', 'notification-demo', '--allow', 'background,storage')
                _, data = dev_runtime.locations(denied_root, 'notification-demo')
                for _ in range(30):
                    if (data / 'result.json').exists():
                        break
                    time.sleep(0.1)
                assert not json.loads((data / 'result.json').read_text())['has_client']
                report['checks'].append('no notification endpoint or client without permission')
            finally:
                command(denied_root, 'stop', 'notification-demo')
            window_root = temp / 'window-root'
            manifest['window'] = dict(manifest.pop('background'), type='desktop')
            manifest['permissions'] = ['window', 'notifications', 'storage']
            (source / 'manifest.json').write_text(json.dumps(manifest))
            script.write_text(script.read_text().replace('while True: time.sleep(1)', ''))
            command(window_root, 'build', str(source), str(archive))
            command(window_root, 'install', str(archive))
            command(window_root, 'open', 'notification-demo', '--allow', 'window,notifications,storage')
            _, data = dev_runtime.locations(window_root, 'notification-demo')
            result = json.loads((data / 'result.json').read_text())
            assert result['first']['ok'] and result['has_display'] and not result['has_dbus_address']
            report['checks'].append('window entry point can notify through the same permission-scoped broker')
            daemon.terminate(); daemon.wait(timeout=5); daemon = None
        report['passed'] = True
except Exception as exc:
    report['error'] = str(exc)
    raise
finally:
    if daemon is not None:
        daemon.terminate(); daemon.wait(timeout=5)
    (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
