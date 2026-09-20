#!/usr/bin/env python3
"""Verify safe extraction of the sanitized payload from a candidate ISO on Linux."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('dev_rootfs', PROJECT / 'tools/dev_rootfs.py')
rootfs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rootfs)
config_spec = importlib.util.spec_from_file_location('dev_config', PROJECT / 'tools/dev_config.py')
config = importlib.util.module_from_spec(config_spec)
config_spec.loader.exec_module(config)
preserve_spec = importlib.util.spec_from_file_location('dev_preserve', PROJECT / 'tools/dev_preserve.py')
preserve = importlib.util.module_from_spec(preserve_spec)
preserve_spec.loader.exec_module(preserve)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iso', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Run as Linux root in a disposable test environment')
    iso_hash = digest(args.iso)
    with tempfile.TemporaryDirectory(prefix='devos-rootfs-test-') as temporary:
        temporary = Path(temporary)
        initrd = temporary / 'live.cpio.gz'
        subprocess.run(['xorriso', '-osirrox', 'on', '-indev', str(args.iso),
                        '-extract', '/boot/live.cpio.gz', str(initrd)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # cpio writes only the selected trusted ISO member to stdout. It never
        # creates archive paths on the host, even for malformed input names.
        def member(name, destination):
            with destination.open('wb') as output:
                gzip = subprocess.Popen(['gzip', '-dc', str(initrd)], stdout=subprocess.PIPE)
                try:
                    result = subprocess.run(['cpio', '-i', '--to-stdout', 'opt/devos-installer/' + name],
                                            stdin=gzip.stdout, stdout=output, stderr=subprocess.DEVNULL)
                    gzip.stdout.close()
                    status = gzip.wait()
                    if result.returncode or status:
                        raise RuntimeError('Could not read ISO payload member')
                finally:
                    if gzip.poll() is None:
                        gzip.kill(); gzip.wait()
            if not destination.stat().st_size:
                raise RuntimeError('ISO payload member is missing or empty: ' + name)
        payload = temporary / 'rootfs.tar.gz'
        manifest = temporary / 'manifest.json'
        member('rootfs.tar.gz', payload)
        member('manifest.json', manifest)
        expected = json.loads(manifest.read_text())['files']['rootfs.tar.gz']
        destination = temporary / 'stage'; destination.mkdir()
        inventory = rootfs.extract(payload, destination, length=payload.stat().st_size, sha256=expected)
        counts = {}
        for relative, item in inventory['files'].items():
            path = destination / relative
            status = path.lstat()
            kind = item['type']
            counts[kind] = counts.get(kind, 0) + 1
            assert status.st_uid == item['uid'] and status.st_gid == item['gid'], relative
            if kind != 'symlink': assert stat.S_IMODE(status.st_mode) == item['mode'], relative
            if kind == 'file':
                assert stat.S_ISREG(status.st_mode) and digest(path) == item['sha256'], relative
                assert status.st_size == item['length'], relative
            elif kind == 'directory':
                assert stat.S_ISDIR(status.st_mode), relative
            elif kind == 'symlink':
                assert stat.S_ISLNK(status.st_mode) and os.readlink(path) == item['link'], relative
            else:
                target = (destination / item['target']).stat()
                assert stat.S_ISREG(status.st_mode) and status.st_ino == target.st_ino, relative
        actual = set()
        for parent, directories, files in os.walk(destination, followlinks=False):
            actual.update((Path(parent) / entry).relative_to(destination).as_posix()
                          for entry in directories + files)
        assert actual == inventory['files'].keys(), 'Unexpected or missing extracted paths'
        baseline = config.config_inventory(inventory['files'])
        current = config.snapshot(destination)
        assert current == baseline, 'Extracted /etc snapshot differs from archive inventory'
        assert config.plan(baseline, current, baseline)['ready']
        reference = temporary / 'reference'
        shutil.copytree(destination, reference, symlinks=True)
        local_config = destination / 'etc/devos-qa-local'
        assert not local_config.exists()
        local_config.write_text('local configuration preservation test\n')
        current = config.snapshot(destination)
        plan = config.plan(baseline, current, baseline)
        assert plan['ready'] and plan['entries']['etc/devos-qa-local']['source'] == 'current'
        # The edited tree plays the live root; the pristine copy is the staged
        # root the plan is applied to. It must end up equal to the merged plan,
        # keeping the local addition and every upstream entry unchanged.
        merged = config.apply(destination, reference, baseline, current, baseline)
        assert config.snapshot(reference) == merged
        assert (reference / 'etc/devos-qa-local').read_text() == 'local configuration preservation test\n'
        for relative, item in merged.items():
            if relative == 'etc/devos-qa-local' or item['type'] != 'file': continue
            assert (reference / relative).read_bytes() == (destination / relative).read_bytes(), relative
        # Package preservation against a genuine database: install the example
        # package into a separate disposable live root (the extracted image's
        # strict signed policy correctly refuses unsigned installs), then plan
        # its transfer to the authenticated release inventory of this ISO.
        hello = temporary / 'hello.dpk'
        subprocess.run([sys.executable, str(PROJECT / 'tools/dev.py'), 'build',
                        str(PROJECT / 'examples/hello'), str(hello)], check=True)
        live = temporary / 'live'
        live.mkdir()
        subprocess.run([sys.executable, str(PROJECT / 'tools/dev.py'), '--root', str(live),
                        'install', str(hello)], check=True)
        installed = json.loads((live / 'var/lib/dev/installed.json').read_text())
        package_plan = preserve.plan(installed, inventory['files'])
        assert package_plan['ready'], package_plan['conflicts']
        assert 'hello' in package_plan['packages']
        assert package_plan['state']['var/lib/dev/installed.json'] is None
        archive = package_plan['packages']['hello']['archive']
        assert (live / archive['path']).is_file(), archive['path']
        assert digest(live / archive['path']) == archive['sha256']
        report = {'passed': True, 'iso_sha256': iso_hash, 'rootfs_sha256': expected,
                  'extractor_sha256': digest(PROJECT / 'tools/dev_rootfs.py'),
                  'files': len(actual), 'types': counts, 'expanded_bytes': inventory['bytes'],
                  'config_planner_sha256': digest(PROJECT / 'tools/dev_config.py'),
                  'config_entries': len(baseline), 'config_snapshot_and_local_preservation_plan': True,
                  'config_apply_merged_and_verified': True,
                  'preserve_planner_sha256': digest(PROJECT / 'tools/dev_preserve.py'),
                  'package_preservation_ready_with_verified_archive': True,
                  'scope': 'Linux host extraction, all-entry verification, /etc apply and package preservation planning; not slot deployment or boot'}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
