"""Bound kernel and rootfs bytes to a versioned manifest; never deploy here."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile

LIMITS = {'bzImage': 128 * 1024**2, 'rootfs.tar.gz': 1024**3}


def validate(manifest):
    if not isinstance(manifest, dict) or set(manifest) != {'format', 'kind', 'version', 'sequence', 'arch', 'files'}:
        raise ValueError('Invalid system release manifest')
    if type(manifest['format']) is not int or manifest['format'] != 1 or manifest['kind'] != 'system':
        raise ValueError('Unsupported system release format')
    if manifest['arch'] != 'x86_64':
        raise ValueError('Unsupported system release architecture')
    if not isinstance(manifest['version'], str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._+-]{0,79}', manifest['version']):
        raise ValueError('Invalid system release version')
    if type(manifest['sequence']) is not int or not 1 <= manifest['sequence'] <= 2**53 - 1:
        raise ValueError('Invalid system release sequence')
    files = manifest['files']
    if not isinstance(files, dict) or set(files) != set(LIMITS):
        raise ValueError('System release requires exactly bzImage and rootfs.tar.gz')
    for name, limit in LIMITS.items():
        item = files[name]
        if not isinstance(item, dict) or set(item) != {'length', 'sha256'}:
            raise ValueError('Invalid system artifact metadata')
        if type(item['length']) is not int or not 0 < item['length'] <= limit:
            raise ValueError('System artifact exceeds size limit')
        if not isinstance(item['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', item['sha256']):
            raise ValueError('Invalid system artifact digest')
    return manifest


def load(directory):
    path = Path(directory) / 'manifest.json'
    with path.open('rb') as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError('Oversized system release manifest')
    return validate(json.loads(raw))


def copy_verified(source, destination, item):
    """Bound the copy itself, not only a prior stat vulnerable to source changes."""
    digest = hashlib.sha256()
    length = 0
    with Path(source).open('rb') as inp, Path(destination).open('xb') as out:
        while chunk := inp.read(min(1024**2, item['length'] - length + 1)):
            length += len(chunk)
            if length > item['length']:
                raise ValueError('System artifact length changed')
            digest.update(chunk)
            out.write(chunk)
    if length != item['length'] or digest.hexdigest() != item['sha256']:
        raise ValueError('System artifact checksum mismatch')


def inspect_rootfs(path):
    import dev_rootfs
    return dev_rootfs.inspect(path)


def snapshot(source, destination):
    manifest = load(source)
    for name, item in manifest['files'].items():
        copy_verified(Path(source) / name, destination / name, item)
    inspect_rootfs(destination / 'rootfs.tar.gz')
    (destination / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True) + '\n')
    return manifest


def build(kernel, rootfs, output, version, sequence):
    sources = {'bzImage': Path(kernel), 'rootfs.tar.gz': Path(rootfs)}
    files = {}
    for name, source in sources.items():
        length = source.stat().st_size
        if not 0 < length <= LIMITS[name]:
            raise ValueError('System artifact exceeds size limit')
        with source.open('rb') as stream:
            checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        files[name] = {'length': length, 'sha256': checksum}
    manifest = validate({'format': 1, 'kind': 'system', 'arch': 'x86_64',
                         'version': version, 'sequence': sequence, 'files': files})
    output = Path(output)
    if output.exists():
        raise ValueError('System release output already exists')
    with tempfile.TemporaryDirectory(prefix='.system-release-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'release'; stage.mkdir()
        for name, source in sources.items():
            copy_verified(source, stage / name, files[name])
        inspect_rootfs(stage / 'rootfs.tar.gz')
        (stage / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True) + '\n')
        stage.rename(output)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--rootfs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--sequence', type=int, required=True)
    args = parser.parse_args()
    build(args.kernel, args.rootfs, args.output, args.version, args.sequence)
    print('Prepared system release: ' + str(args.output))


if __name__ == '__main__':
    main()
