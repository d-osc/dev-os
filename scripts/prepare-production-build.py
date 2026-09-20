#!/usr/bin/env python3
"""Copy source inputs into an isolated native Linux Buildroot workspace."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('destination', type=Path)
args = parser.parse_args()
if sys.platform != 'linux':
    raise SystemExit('Run this script through Linux/WSL')
source = Path(__file__).resolve().parents[1]
destination = args.destination.resolve()
if destination == source or destination.is_relative_to(source) or source.is_relative_to(destination):
    raise SystemExit('Build checkout must be separate from the source checkout')
marker = destination / '.devos-build-checkout.json'
if destination.exists():
    if not marker.is_file() or json.loads(marker.read_text()).get('source') != str(source):
        raise SystemExit('Refusing to overwrite an unrecognized build checkout')
destination.mkdir(parents=True, exist_ok=True)
inputs = {}
for directory in ('buildroot-external', 'config', 'scripts', 'tools', 'installer',
                  'rootfs-overlay', 'examples', 'tests', 'sdk'):
    for path in (source / directory).rglob('*'):
        relative = path.relative_to(source)
        if any(part in ('node_modules', '__pycache__', 'dist', 'out') for part in relative.parts):
            continue
        if path.is_symlink():
            raise SystemExit('Source checkout contains an unsupported symlink: ' + str(relative))
        if path.is_file():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            inputs[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
for path in source.glob('*.md'):
    shutil.copy2(path, destination / path.name)
marker.write_text(json.dumps({'source': str(source), 'files': inputs}, indent=2) + '\n')
print('Prepared isolated build checkout: ' + str(destination))
