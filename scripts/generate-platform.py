#!/usr/bin/env python3
"""Write target architecture/runtime metadata from the configured Buildroot tree."""
import argparse
import json
from pathlib import Path
import re
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('target', type=Path)
parser.add_argument('--build-output', type=Path, required=True)
args = parser.parse_args()
config = (args.build_output / '.config').read_text()
if 'BR2_x86_64=y' not in config:
    raise SystemExit('Only the x86_64 Dev OS target is currently supported')
variables = ('PYTHON3_VERSION', 'NODEJS_SRC_VERSION', 'BASH_VERSION', 'BUSYBOX_VERSION', 'GLIBC_VERSION')
result = subprocess.run(['make', '-s', '--no-print-directory', '-C', str(args.build_output),
                         'printvars', 'VARS=' + ' '.join(variables)],
                        check=True, capture_output=True, text=True)
values = {}
for line in result.stdout.splitlines():
    match = re.fullmatch(r'([A-Z0-9_]+)=(.+)', line)
    if match and match[1] in variables:
        values[match[1]] = match[2].strip("'\"")
runtimes = {}
for name, variable, binary in [('python', 'PYTHON3_VERSION', 'usr/bin/python3'),
                               ('node', 'NODEJS_SRC_VERSION', 'usr/bin/node'),
                               ('bash', 'BASH_VERSION', 'bin/bash'),
                               ('sh', 'BUSYBOX_VERSION', 'bin/busybox')]:
    if (args.target / binary).exists():
        if variable not in values:
            raise SystemExit('Missing configured runtime version: ' + variable)
        runtimes[name] = values[variable]
platform = {'version': 1, 'arch': 'x86_64', 'devos_version': '0.1', 'runtimes': runtimes,
            'libc': {'name': 'glibc', 'version': values.get('GLIBC_VERSION')},
            'library_dirs': ['lib', 'lib64', 'usr/lib', 'usr/lib64']}
destination = args.target / 'usr/lib/devos/platform.json'
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(json.dumps(platform, indent=2) + '\n')
destination.chmod(0o644)
print('Wrote target platform metadata')
