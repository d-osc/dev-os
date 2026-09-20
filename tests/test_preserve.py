import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('dev_preserve', Path(__file__).parents[1] / 'tools/dev_preserve.py')
preserve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preserve)


def record(name='app', version='1.0', files=None, sha='a' * 64):
    return {'name': name, 'version': version, 'arch': 'x86_64',
            'dependencies': {'lib': '*'}, 'runtime_versions': {'python': '~=3.14'},
            'files': files if files is not None else {'usr/bin/app': {'mode': 0o755, 'sha256': 'b' * 64}},
            'installed_trust': {'type': 'tuf', 'archive': 'var/lib/dev/archives/' + sha + '/' + name + '.dpk',
                                'sha256': sha}}


class Preserve(unittest.TestCase):
    def test_ready_plan_lists_packages_and_transferable_state(self):
        previous = {'name': 'lib', 'version': '1.0', 'archive': 'var/lib/dev/archives/' + 'c' * 64 + '/lib.dpk',
                    'sha256': 'c' * 64}
        database = {'app': record(), 'lib': dict(record(name='lib', sha='d' * 64,
                                                        files={'usr/lib/lib.so': {'mode': 0o644, 'sha256': 'e' * 64}}),
                                                 installed_previous=previous)}
        result = preserve.plan(database, {'usr/share/base': {'type': 'file'}, 'etc/passwd': {'type': 'file'}})
        self.assertTrue(result['ready'])
        self.assertEqual(sorted(result['packages']), ['app', 'lib'])
        self.assertEqual(result['packages']['app']['files']['usr/bin/app']['mode'], 0o755)
        self.assertEqual(result['packages']['lib']['previous']['sha256'], 'c' * 64)
        self.assertEqual(result['packages']['app']['dependencies'], {'lib': '*'})
        self.assertIsNone(result['state']['var/lib/dev/installed.json'])
        for sha in ('a' * 64, 'c' * 64, 'd' * 64):
            self.assertTrue(any(path.startswith('var/lib/dev/archives/' + sha + '/') for path in result['state']),
                            'Missing archive for ' + sha)
        self.assertTrue(all(sha is None or isinstance(sha, str) for sha in result['state'].values()))

    def test_release_overlap_is_a_conflict_even_with_identical_bytes(self):
        database = {'app': record()}
        owned = {'usr/bin/app': {'type': 'file', 'mode': 0o755, 'sha256': 'b' * 64}}
        result = preserve.plan(database, dict(owned))
        self.assertFalse(result['ready'])
        self.assertEqual(result['packages'], {})
        self.assertEqual(result['state'], {})
        self.assertEqual(result['conflicts'][0]['package'], 'app')
        self.assertIn('usr/bin/app', result['conflicts'][0]['reason'])

    def test_missing_or_mismatched_archive_is_a_conflict(self):
        missing = record(); del missing['installed_trust']
        mismatched = record(sha='a' * 64)
        mismatched['installed_trust']['archive'] = 'var/lib/dev/archives/' + 'f' * 64 + '/app.dpk'
        for database, expected in (({'app': missing}, 'No cached archive'),
                                   ({'app': mismatched}, 'Invalid cached archive reference')):
            result = preserve.plan(database, {})
            self.assertFalse(result['ready'])
            self.assertEqual(result['packages'], {})
            self.assertIn(expected, result['conflicts'][0]['reason'])

    def test_invalid_records_are_reported_per_package(self):
        bad_path = record(files={'etc/config': {'mode': 0o644, 'sha256': 'b' * 64}})
        bad_mode = record(files={'usr/bin/app': {'mode': 0o600, 'sha256': 'b' * 64}})
        bad_hash = record(files={'usr/bin/app': {'mode': 0o755, 'sha256': 'not-a-hash'}})
        protected = record(files={'usr/bin/dev': {'mode': 0o755, 'sha256': 'b' * 64}})
        empty = record(files={})
        for database in ({'app': bad_path}, {'app': bad_mode}, {'app': bad_hash},
                         {'app': protected}, {'app': empty}):
            result = preserve.plan(database, {})
            self.assertFalse(result['ready'])
            self.assertEqual(result['packages'], {})
            self.assertEqual(result['conflicts'][0]['package'], 'app')

    def test_package_count_limit_is_a_conflict(self):
        names = ['pkg%d' % index for index in range(513)]
        database = {name: record(name=name, sha='%064x' % index) for index, name in enumerate(names)}
        result = preserve.plan(database, {})
        self.assertFalse(result['ready'])
        self.assertIn('exceeds 512', result['conflicts'][0]['reason'])

    def test_record_name_must_match_the_database_key(self):
        result = preserve.plan({'other': record()}, {})
        self.assertFalse(result['ready'])
        self.assertEqual(result['conflicts'][0]['package'], 'other')
        self.assertIn('database key', result['conflicts'][0]['reason'])

    def test_non_dictionary_inputs_are_rejected(self):
        with self.assertRaises(ValueError): preserve.plan([], {})
        with self.assertRaises(ValueError): preserve.plan({}, [])
