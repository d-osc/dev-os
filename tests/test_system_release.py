import copy
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('dev_system_release', Path(__file__).parents[1] / 'tools/dev_system_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class SystemRelease(unittest.TestCase):
    def test_manifest_rejects_wrong_arch_paths_sizes_and_sequence(self):
        item = {'length': 1, 'sha256': hashlib.sha256(b'x').hexdigest()}
        good = {'format': 1, 'kind': 'system', 'arch': 'x86_64', 'sequence': 1,
                'version': '1', 'files': {name: dict(item) for name in release.LIMITS}}
        release.validate(good)
        for changes in ({'sequence': True}, {'sequence': 0}, {'version': '../escape'},
                        {'arch': 'all'}, {'kind': 'package'}, {'format': True},
                        {'files': {'../../escape': item}}, {'extra': 'ignored?'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                release.validate(dict(good, **changes))
        bad = copy.deepcopy(good)
        bad['files']['bzImage']['length'] = release.LIMITS['bzImage'] + 1
        with self.assertRaises(ValueError):
            release.validate(bad)

    def test_copy_is_bounded_and_verifies_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'; source.write_bytes(b'longer than declared')
            with self.assertRaisesRegex(ValueError, 'length changed'):
                release.copy_verified(source, root / 'copy', {'length': 1, 'sha256': '0' * 64})
            self.assertEqual((root / 'copy').stat().st_size, 0)
