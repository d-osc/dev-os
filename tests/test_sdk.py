import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'sdk'))
from dpk_sdk import init_project, inspect_package, pack, validate, verify
from dpk_sdk._core import core


class SDK(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / 'app'
        init_project(self.source, name='sample', background_runtime='node', window_runtime='bash')

    def test_roundtrip_installs_with_existing_dev_reader(self):
        archive = pack(self.source)
        m = inspect_package(archive)
        self.assertEqual(m['background']['runtime'], 'node')
        self.assertEqual(m['window']['runtime'], 'bash')
        self.assertEqual(m['format'], 2)
        root = self.base / 'root'
        core.install(root, archive)
        self.assertTrue((root / 'opt/apps/sample/background.cjs').is_file())
        core.remove(root, 'sample')

    def test_pack_is_reproducible_across_output_names(self):
        first = pack(self.source, self.base / 'first.dpk')
        second = pack(self.source, self.base / 'second.dpk')
        self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_refuses_overwrite_unless_forced(self):
        archive = pack(self.source)
        original = archive.read_bytes()
        with self.assertRaises(FileExistsError):
            pack(self.source)
        self.assertEqual(archive.read_bytes(), original)
        self.assertEqual(pack(self.source, force=True).read_bytes(), original)

    def test_invalid_force_build_preserves_existing_archive(self):
        archive = pack(self.source)
        original = archive.read_bytes()
        path = self.source / 'manifest.json'
        m = json.loads(path.read_text())
        m['permissions'].append('root')
        path.write_text(json.dumps(m))
        with self.assertRaises(ValueError):
            pack(self.source, archive, force=True)
        self.assertEqual(archive.read_bytes(), original)

    def test_payload_output_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'outside payload'):
            pack(self.source, self.source / 'payload/opt/apps/sample/self.dpk')

    def test_source_manifest_is_unchanged(self):
        before = (self.source / 'manifest.json').read_bytes()
        validate(self.source)
        pack(self.source)
        self.assertEqual((self.source / 'manifest.json').read_bytes(), before)

    def test_corrupt_payload_is_detected(self):
        archive = pack(self.source)
        with tarfile.open(archive, 'r:gz') as reader:
            entries = [(member, reader.extractfile(member).read()) for member in reader]
        with tarfile.open(archive, 'w:gz') as writer:
            for index, (member, data) in enumerate(entries):
                if index == 1:
                    data = b'corrupted'
                member.size = len(data)
                writer.addfile(member, io.BytesIO(data))
        with self.assertRaisesRegex(ValueError, 'Checksum'):
            verify(archive)

    def test_template_variants_validate(self):
        for runtime in ('python', 'node', 'bash', 'sh'):
            with self.subTest(runtime=runtime):
                folder = self.base / runtime
                init_project(folder, name='sample', runtime=runtime, permissions=['notifications'])
                self.assertIn('notifications', validate(folder)['permissions'])
                for script in folder.rglob('*.sh'):
                    self.assertNotIn(b'\x01', script.read_bytes())

    def test_native_template_needs_compilation(self):
        source = self.base / 'native'
        init_project(source, name='native-app', runtime='native')
        self.assertTrue((source / 'build.py').is_file())
        self.assertTrue((source / 'src/window.c').is_file())
        self.assertEqual(json.loads((source / 'manifest.json').read_text())['arch'], 'x86_64')
        with self.assertRaises(ValueError):
            validate(source)

    def test_init_does_not_overwrite_existing_work(self):
        with self.assertRaises(FileExistsError):
            init_project(self.source, name='sample')

    def test_manifest_size_limit_matches_reader(self):
        path = self.source / 'manifest.json'
        m = json.loads(path.read_text())
        m['extra'] = 'x' * (2 * 1024**2)
        path.write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError, 'Manifest exceeds'):
            validate(self.source)


if __name__ == '__main__':
    unittest.main()
