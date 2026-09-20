#!/usr/bin/env python3
"""Stage a prompt-only update to existing images and rebuild the installer ISO."""
import argparse
import hashlib
import io
from pathlib import Path
import shutil
import subprocess
import tarfile

project = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--base-images', required=True, type=Path)
parser.add_argument('--stage', required=True, type=Path, help='new staging directory; must not exist')
args = parser.parse_args()
args.stage.mkdir(parents=True, exist_ok=False)
images = args.stage / 'out/buildroot/images'
images.mkdir(parents=True)
profile_data = (project / 'rootfs-overlay/etc/profile.d/devos-prompt.sh').read_text().encode()
profile = args.stage / 'devos-prompt.sh'
profile.write_bytes(profile_data)
for name in ('bzImage', 'rootfs.ext4'):
    shutil.copyfile(args.base_images / name, images / name)
for command in ('mkdir /etc/profile.d', 'rm /etc/profile.d/devos-prompt.sh',
                f'write {profile} /etc/profile.d/devos-prompt.sh'):
    subprocess.run(['debugfs', '-w', '-R', command, str(images / 'rootfs.ext4')], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
stored = subprocess.check_output(['debugfs', '-R', 'cat /etc/profile.d/devos-prompt.sh', str(images / 'rootfs.ext4')], stderr=subprocess.DEVNULL)
assert stored == profile_data
with tarfile.open(args.base_images / 'rootfs.tar.gz', 'r:gz') as source, tarfile.open(images / 'rootfs.tar.gz', 'w:gz') as dest:
    has_directory = False
    for member in source:
        name = member.name.removeprefix('./').rstrip('/')
        if name == 'etc/profile.d/devos-prompt.sh':
            continue
        if name == 'etc/profile.d':
            has_directory = True
        dest.addfile(member, source.extractfile(member) if member.isfile() else None)
    if not has_directory:
        directory = tarfile.TarInfo('etc/profile.d')
        directory.type = tarfile.DIRTYPE; directory.mode = 0o755
        dest.addfile(directory)
    member = tarfile.TarInfo('etc/profile.d/devos-prompt.sh')
    member.mode = 0o644; member.size = len(profile_data)
    dest.addfile(member, io.BytesIO(profile_data))
(args.stage / 'scripts').mkdir()
for name in ('build-installer.py', 'test-installer.py'):
    shutil.copyfile(project / 'scripts' / name, args.stage / 'scripts' / name)
subprocess.run(['fakeroot', '--', 'python3', str(args.stage / 'scripts/build-installer.py')], check=True)
checksums = []
for name in ('bzImage', 'rootfs.ext4', 'rootfs.tar.gz'):
    with (images / name).open('rb') as stream:
        checksums.append(hashlib.file_digest(stream, 'sha256').hexdigest() + '  ' + name)
(images / 'SHA256SUMS').write_text('\n'.join(checksums) + '\n')
print('Staged release: ' + str(args.stage), flush=True)
