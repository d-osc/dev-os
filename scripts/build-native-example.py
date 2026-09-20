#!/usr/bin/env python3
"""Compile static/background and dynamic/window Linux ELF examples and pack a DPK."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

project = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir', type=Path, default=project / 'out/native-counter-source')
parser.add_argument('--package', type=Path, default=project / 'out/native-counter-0.1.0-x86_64.dpk')
args = parser.parse_args()
source = project / 'examples/native-counter'
payload = args.output_dir / 'payload/opt/apps/native-counter'
(payload / 'bin').mkdir(parents=True, exist_ok=True)
(payload / 'lib').mkdir(exist_ok=True)
shutil.copyfile(source / 'manifest.json', args.output_dir / 'manifest.json')
compiler = os.environ.get('CC', 'cc')
flags = ['-O2', '-Wall', '-Wextra', '-Werror']
include = ['-I', os.environ['DEVOS_X11_INCLUDE']] if os.environ.get('DEVOS_X11_INCLUDE') else []

def compile(*arguments):
    subprocess.run([compiler, *flags, *arguments], check=True)

compile('-static', str(source / 'background.c'), '-o', str(payload / 'bin/counterd'))
compile('-shared', '-fPIC', str(source / 'label.c'), '-o', str(payload / 'lib/libcounter-label.so'))
compile(*include, str(source / 'window.c'), '-L' + str(payload / 'lib'), '-lcounter-label',
        '-Wl,-rpath,$ORIGIN/../lib', '-l:libX11.so.6', '-o', str(payload / 'bin/counter-window.bin'))
subprocess.run([sys.executable, str(project / 'tools/dev.py'), 'build', str(args.output_dir), str(args.package)], check=True)
