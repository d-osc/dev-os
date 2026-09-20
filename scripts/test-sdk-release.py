#!/usr/bin/env python3
"""Verify the portable SDK and installed wheel away from the repository source."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv

project = Path(__file__).resolve().parents[1]
artifacts = project / 'out/sdk'
report = {'platform': sys.platform, 'passed': False, 'checks': []}


def run(command, cwd, success=True):
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=120)
    if (result.returncode == 0) != success:
        raise AssertionError(str(command) + '\n' + result.stdout + result.stderr)
    return result


try:
    with tempfile.TemporaryDirectory(prefix='sdk release test ') as temp:
        temp = Path(temp)
        portable = [sys.executable, str(artifacts / 'dpk-sdk.pyz')]
        run(portable + ['init', 'app', '--name', 'sample', '--background-runtime', 'node', '--window-runtime', 'bash'], temp)
        run(portable + ['validate', 'app'], temp)
        run(portable + ['pack', 'app', '-o', 'first.dpk'], temp)
        run(portable + ['pack', 'app', '-o', 'second.dpk'], temp)
        assert (temp / 'first.dpk').read_bytes() == (temp / 'second.dpk').read_bytes()
        run(portable + ['pack', 'app', '-o', 'first.dpk'], temp, success=False)
        run(portable + ['verify', 'first.dpk'], temp)
        manifest = json.loads(run(portable + ['inspect', 'first.dpk'], temp).stdout)
        assert manifest['window']['runtime'] == 'bash'
        run([sys.executable, str(project / 'tools/dev.py'), '--root', str(temp / 'target'), 'install', str(temp / 'first.dpk')], temp)
        run([sys.executable, str(project / 'tools/dev.py'), '--root', str(temp / 'target'), 'remove', 'sample'], temp)
        report['checks'].append('standalone zipapp init/validate/pack/verify/inspect, deterministic bytes, no overwrite, dev install/remove')
        environment = temp / 'venv'
        venv.EnvBuilder(with_pip=True).create(environment)
        binary = environment / ('Scripts' if os.name == 'nt' else 'bin')
        python = binary / ('python.exe' if os.name == 'nt' else 'python')
        run([str(python), '-m', 'pip', 'install', '--no-index', '--no-deps', '--disable-pip-version-check',
             str(artifacts / 'devos_dpk_sdk-0.4.0-py3-none-any.whl')], temp)
        cli = binary / ('dpk.exe' if os.name == 'nt' else 'dpk')
        run([str(cli), 'init', 'wheel-app', '--runtime', 'python', '--kind', 'background'], temp)
        run([str(cli), 'pack', 'wheel-app'], temp)
        result = run([str(python), '-c', "from dpk_sdk import verify; print(verify('wheel-app/dist/wheel-app-0.1.0-all.dpk')['name'])"], temp)
        assert result.stdout.strip() == 'wheel-app'
        report['checks'].append('offline wheel install, dpk console entry point, embedded templates/core, public Python API')
        report['passed'] = True
except Exception as exc:
    report['error'] = str(exc)
    raise
finally:
    (artifacts / ('test-' + sys.platform + '.json')).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
