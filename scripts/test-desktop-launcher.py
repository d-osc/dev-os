#!/usr/bin/env python3
"""Real Linux launcher consent and X11 window test; no host installation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import pexpect
from gi.repository import Gio, GLib

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project / 'tools'))
import dev_runtime

output = project / 'out/launcher-tests'
output.mkdir(parents=True, exist_ok=True)
report = {'passed': False, 'checks': []}

with tempfile.TemporaryDirectory(prefix='devos-launcher-') as temporary:
    base = Path(temporary); source = base / 'source'; root = base / 'root'
    shutil.copytree(project / 'examples/desktop-counter', source)
    manifest_path = source / 'manifest.json'
    m = json.loads(manifest_path.read_text())
    del m['background']; m['permissions'] = ['window', 'storage']
    m['window']['args'] = ['--test']
    manifest_path.write_text(json.dumps(m))
    def command(*args):
        return [sys.executable, str(project / 'tools/dev.py'), '--root', str(root), *args]
    subprocess.run(command('build', str(source), str(base / 'app.dpk')), check=True)
    subprocess.run(command('install', str(base / 'app.dpk')), check=True)
    try:
        desktop = root / 'usr/share/applications/devos-desktop-counter.desktop'
        text = desktop.read_text()
        shutil.copyfile(desktop, output / desktop.name)
        keyfile = GLib.KeyFile()
        # GIO checks host executable availability. Substitute its path for parsing
        # only; actual launch below calls our dev.py against the disposable root.
        assert 'Exec=/usr/bin/dev launch desktop-counter\n' in text
        parsed_text = text.replace('/usr/bin/dev', '/usr/bin/python3')
        keyfile.load_from_data(parsed_text, len(parsed_text.encode('utf-8')), GLib.KeyFileFlags.NONE)
        app = Gio.DesktopAppInfo.new_from_keyfile(keyfile)
        assert app is not None and app.get_name() == 'Dev Counter'
        assert app.get_commandline() == '/usr/bin/python3 launch desktop-counter'
        assert app.get_boolean('Terminal')
        report['checks'].append('GIO parses generated desktop entry, icon and terminal command')
        denied = subprocess.run(command('launch', m['name']), capture_output=True, text=True)
        assert denied.returncode != 0 and 'interactive terminal' in denied.stderr
        report['checks'].append('non-interactive launch refuses implicit grants')
        _, data = dev_runtime.locations(root, m['name'])
        for answer in ('no', 'yes'):
            child = pexpect.spawn(sys.executable, command('launch', m['name'])[1:], encoding='utf-8', timeout=30)
            try:
                child.expect_exact('Type yes to continue: ')
                child.sendline(answer); child.expect(pexpect.EOF); child.close()
                assert child.exitstatus == (0 if answer == 'yes' else 1)
                assert (data / 'window.ppm').exists() == (answer == 'yes')
            finally:
                if child.isalive(): child.close(force=True)
        shutil.copyfile(data / 'window.ppm', output / 'native-window.ppm')
        report['checks'].append('declining opens nothing; consenting renders an X11 window inside sandbox')
        report['checks'].append('launcher executes the declared window runtime, entry_point and args')
        status = subprocess.check_output(command('status', m['name']), text=True)
        assert not json.loads(status)['running']
        report['checks'].append('launcher does not auto-start background')
        subprocess.run(command('remove', m['name']), check=True)
        assert not desktop.exists()
        report['checks'].append('uninstall removes desktop entry')
        report['passed'] = True
    finally:
        (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2))
