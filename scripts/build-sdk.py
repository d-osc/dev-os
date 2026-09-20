#!/usr/bin/env python3
"""Build a standalone wheel and portable zipapp from the current shared DPK core."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipapp

project = Path(__file__).resolve().parents[1]
output = project / 'out/sdk'
output.mkdir(parents=True, exist_ok=True)
assets = {
    'background.py': 'examples/desktop-counter/payload/opt/apps/desktop-counter/background.py',
    'background.cjs': 'examples/desktop-counter/payload/opt/apps/desktop-counter/background.cjs',
    'window.py': 'examples/desktop-counter/payload/opt/apps/desktop-counter/window.py',
    'background.c': 'examples/native-counter/background.c',
    'window.c': 'examples/native-counter/window.c',
    'label.c': 'examples/native-counter/label.c',
}
with tempfile.TemporaryDirectory(prefix='dpk-sdk-release-') as temporary:
    stage = Path(temporary)
    shutil.copytree(project / 'sdk/dpk_sdk', stage / 'dpk_sdk', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copyfile(project / 'tools/dev.py', stage / 'dpk_sdk/_dev.py')
    (stage / 'dpk_sdk/assets').mkdir()
    (stage / 'dpk_sdk/assets/__init__.py').write_text('"""SDK starter source assets."""\n')
    for name, path in assets.items():
        shutil.copyfile(project / path, stage / 'dpk_sdk/assets' / name)
    shutil.copyfile(project / 'sdk/README.md', stage / 'README.md')
    (stage / '__main__.py').write_text('from dpk_sdk.cli import main\nraise SystemExit(main())\n')
    zipapp.create_archive(stage, output / 'dpk-sdk.pyz', interpreter='/usr/bin/env python3', compressed=True)
    (stage / 'pyproject.toml').write_text('''[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "devos-dpk-sdk"
version = "0.4.0"
description = "Developer Package Kit SDK for Dev OS"
readme = "README.md"
requires-python = ">=3.11"

[project.scripts]
dpk = "dpk_sdk.cli:main"
dpk-sdk = "dpk_sdk.cli:main"

[tool.setuptools]
packages = ["dpk_sdk", "dpk_sdk.assets"]

[tool.setuptools.package-data]
dpk_sdk = ["assets/*"]
''', encoding='utf-8')
    subprocess.run([sys.executable, '-c', 'from setuptools.build_meta import build_wheel; build_wheel("dist")'],
                   cwd=stage, check=True)
    for wheel in (stage / 'dist').glob('*.whl'):
        shutil.copyfile(wheel, output / wheel.name)
shutil.copyfile(project / 'sdk/README.md', output / 'README.md')
names = ['dpk-sdk.pyz', 'devos_dpk_sdk-0.4.0-py3-none-any.whl', 'README.md']
checksums = []
for name in names:
    with (output / name).open('rb') as stream:
        checksums.append(hashlib.file_digest(stream, 'sha256').hexdigest() + '  ' + name)
(output / 'SHA256SUMS').write_text('\n'.join(checksums) + '\n')
print('SDK release: ' + str(output))
