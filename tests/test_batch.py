"""One durable database decision for several prepared package transitions."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

CORE = Path(__file__).parents[1] / 'tools/dev.py'
spec = importlib.util.spec_from_file_location('dev_batch_test', CORE)
dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev)

CHILD = '''import importlib.util, json, os, pathlib, sys
spec = importlib.util.spec_from_file_location('dev', sys.argv[1])
dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev)
def crash(label):
    if label == sys.argv[4]:
        os._exit(77)
dev.transaction_checkpoint = crash
root = pathlib.Path(sys.argv[2])
data = json.loads(pathlib.Path(sys.argv[3]).read_text())
with dev.database(root) as (db, dbpath):
    if sys.argv[5] != 'recover':
        dev.run_batch(root, dbpath, db, data['updates'],
                      {name: pathlib.Path(path) for name, path in data['sources'].items()})
'''


class Batch(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'root'
        for name in ('lib', 'app'):
            archive, _, _ = self.package(name, '1')
            dev.install(self.root, archive)
        self.updates = {}
        self.sources = {}
        for name in ('lib', 'app', 'extra'):
            _, manifest, source = self.package(name, '2')
            self.updates[name] = manifest
            self.sources.update({file: source / file for file in dev.installed_files(manifest)})
        self.plan = self.base / 'plan.json'
        self.plan.write_text(json.dumps({'updates': self.updates,
                                        'sources': {name: str(path) for name, path in self.sources.items()}}))

    def package(self, name, version):
        source = self.base / (name + version)
        payload = source / 'payload/usr/share' / name
        payload.mkdir(parents=True)
        (payload / 'version').write_text(version)
        manifest = {'name': name, 'version': version, 'arch': 'all'}
        if name == 'app':
            manifest['dependencies'] = {'lib': '==' + version}
        (source / 'manifest.json').write_text(json.dumps(manifest))
        archive = self.base / (name + version + '.dpk')
        dev.build(source, archive)
        stage = self.base / (name + version + '-stage')
        stage.mkdir()
        manifest = dev.unpack(archive, stage)
        return archive, manifest, stage

    def apply(self):
        with dev.database(self.root) as (db, path):
            dev.run_batch(self.root, path, db, self.updates, self.sources)

    def state(self, version):
        with dev.database(self.root) as (db, _):
            self.assertEqual({name: item['version'] for name, item in db.items()},
                             {name: version for name in (('lib', 'app') if version == '1' else ('lib', 'app', 'extra'))})
            dev.compatibility_module().check_dependencies(db, dev.core_api())
        for name in ('lib', 'app'):
            self.assertEqual((self.root / 'usr/share' / name / 'version').read_text(), version)
        self.assertEqual((self.root / 'usr/share/extra/version').exists(), version == '2')
        self.assertFalse((self.root / 'var/lib/dev/transaction').exists())
        self.assertFalse(list(self.root.rglob('.dev-*')))

    def crash(self, point, operation='batch'):
        result = subprocess.run([sys.executable, '-c', CHILD, str(CORE), str(self.root),
                                 str(self.plan), point, operation], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 77, result.stdout + result.stderr)

    def test_dependencies_transition_together(self):
        self.apply()
        self.state('2')

    def test_process_crashes_restore_whole_batch(self):
        # Each precommit crash recovers to the same root, ready for the next case.
        for point in ('prepared', 'journal', 'replace-copy:version', 'replace-publish:version',
                      'file:0', 'copy:version', 'publish:version', 'file:1', 'file:2'):
            with self.subTest(point=point):
                self.crash(point)
                self.state('1')
        self.crash('commit')
        self.state('2')

    def test_recovery_can_itself_be_interrupted(self):
        self.crash('file:2')
        self.crash('replace-publish:version', 'recover')
        self.state('1')

    def test_commit_failure_restores_every_package(self):
        with mock.patch.object(dev, 'save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.apply()
        self.state('1')

    def test_modified_existing_package_prevents_partial_install(self):
        modified = self.root / 'usr/share/lib/version'
        modified.write_text('user edit')
        with self.assertRaisesRegex(ValueError, 'modified file'):
            self.apply()
        self.assertEqual(modified.read_text(), 'user edit')
        self.assertEqual((self.root / 'usr/share/app/version').read_text(), '1')
        self.assertFalse((self.root / 'usr/share/extra/version').exists())

    def test_batch_ownership_conflict_is_rejected(self):
        self.updates['extra']['files'] = dict(self.updates['app']['files'])
        with self.assertRaisesRegex(ValueError, 'ownership conflict'):
            self.apply()
        self.state('1')


if __name__ == '__main__':
    unittest.main()
