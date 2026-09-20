#!/usr/bin/env python3
"""Render the two missing Buildroot packages from pinned PyPI source metadata.

Existing crypto/urllib3/packaging dependencies use Buildroot's own pinned sources.
This generator does not fetch or execute downloaded project code.
"""
import json
from pathlib import Path

project = Path(__file__).resolve().parents[1]
lock = json.loads((project / 'config/runtime-sources.json').read_text())
external = project / 'buildroot-external'
external.mkdir(exist_ok=True)
def write(path, value):
    path.write_text(value, encoding='utf-8', newline='\n')

write(external / 'external.desc', 'name: DEVOS\ndesc: Dev OS signed package runtime\n')
write(external / 'external.mk', 'include $(sort $(wildcard $(BR2_EXTERNAL_DEVOS_PATH)/package/*/*.mk))\n')
write(external / 'Config.in', '''menu "Dev OS"
source "$BR2_EXTERNAL_DEVOS_PATH/package/python-securesystemslib/Config.in"
source "$BR2_EXTERNAL_DEVOS_PATH/package/python-tuf/Config.in"
endmenu
''')
for name, license_name in (('securesystemslib', 'MIT'), ('tuf', 'Apache-2.0 or MIT')):
    info = lock[name]
    package = 'python-' + name
    prefix = package.upper().replace('-', '_')
    directory = external / 'package' / package
    directory.mkdir(parents=True, exist_ok=True)
    dependencies = 'python-cryptography' if name == 'securesystemslib' else 'python-securesystemslib python-urllib3'
    backend = '131' if name == 'securesystemslib' else '132'
    write(directory / (package + '.mk'), f'''# Generated from config/runtime-sources.json; do not edit by hand.
{prefix}_VERSION = {info['version']}
{prefix}_SOURCE = {info['filename']}
{prefix}_SITE = {info['url'].rsplit('/', 1)[0]}
{prefix}_SETUP_TYPE = pep517
{prefix}_LICENSE = {license_name}
{prefix}_LICENSE_FILES = {' '.join(info['license_hashes'])}
{prefix}_DEPENDENCIES = {dependencies} host-devos-hatchling{backend}
{prefix}_ENV = PYTHONPATH="$(HOST_DIR)/lib/devos/hatchling{backend}:$(PYTHON3_PATH)"

$(eval $(python-package))
''')
    hashes = [f"sha256  {info['sha256']}  {info['filename']}"]
    hashes.extend(f'sha256  {value}  {filename}' for filename, value in info['license_hashes'].items())
    write(directory / (package + '.hash'), '# Pinned upstream source and license hashes\n' + '\n'.join(hashes) + '\n')
    selections = ['BR2_PACKAGE_PYTHON_CRYPTOGRAPHY'] if name == 'securesystemslib' else [
        'BR2_PACKAGE_PYTHON_SECURESYSTEMSLIB', 'BR2_PACKAGE_PYTHON_URLLIB3', 'BR2_PACKAGE_PYTHON_PACKAGING',
        'BR2_PACKAGE_PYTHON3_SSL', 'BR2_PACKAGE_PYTHON3_HASHLIB', 'BR2_PACKAGE_CA_CERTIFICATES',
        'BR2_PACKAGE_PYTHON_PYELFTOOLS']
    write(directory / 'Config.in', f'''config BR2_PACKAGE_{prefix}
\tbool "{package}"
\tdepends on BR2_PACKAGE_PYTHON3
\tdepends on BR2_PACKAGE_HOST_RUSTC_TARGET_ARCH_SUPPORTS
''' + ''.join('\tselect ' + option + '\n' for option in selections) +
        '\thelp\n\t  Pinned verification runtime for Dev OS package repositories.\n')
backends = json.loads((project / 'config/build-backends.json').read_text())
for version, info in backends.items():
    short = version.replace('.', '')[:-1]
    package = 'devos-hatchling' + short
    prefix = 'HOST_DEVOS_HATCHLING' + short
    directory = external / 'package' / package
    directory.mkdir(parents=True, exist_ok=True)
    write(directory / (package + '.mk'), f'''# Pinned, isolated host-only wheel; never installed into the target image.
{prefix}_VERSION = {version}
{prefix}_SOURCE = {info['filename']}
{prefix}_SITE = {info['url'].rsplit('/', 1)[0]}
{prefix}_LICENSE = MIT
{prefix}_LICENSE_FILES = {info['license_file']}
{prefix}_DEPENDENCIES = host-python3 host-python-packaging host-python-pathspec host-python-pluggy host-python-trove-classifiers host-python-tomlkit

define {prefix}_EXTRACT_CMDS
\tpython3 -m zipfile -e $({prefix}_DL_DIR)/$({prefix}_SOURCE) $(@D)
endef

define {prefix}_INSTALL_CMDS
\tmkdir -p $(HOST_DIR)/lib/devos/hatchling{short}
\tcp -a $(@D)/hatchling $(@D)/hatchling-{version}.dist-info $(HOST_DIR)/lib/devos/hatchling{short}/
endef

$(eval $(host-generic-package))
''')
    write(directory / (package + '.hash'), f"sha256  {info['sha256']}  {info['filename']}\nsha256  {info['license_sha256']}  {info['license_file']}\n")
print('Generated Buildroot external package definitions')
