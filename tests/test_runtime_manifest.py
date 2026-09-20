import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('dev_runtime_manifest_test', Path(__file__).parents[1] / 'tools/dev.py')
dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev)


class RuntimeManifest(unittest.TestCase):
    def setUp(self):
        self.path = 'opt/apps/example/main'
        self.manifest = {'format': 2, 'manifest_version': 2, 'name': 'example', 'version': '1',
                         'arch': 'all', 'permissions': ['background', 'window'],
                         'background': {'entry_point': self.path},
                         'window': {'type': 'desktop', 'entry_point': self.path},
                         'executables': [self.path],
                         'files': {self.path: {'mode': 0o755, 'sha256': 'a' * 64}}}

    def test_native_ui_and_background_are_valid(self):
        dev.manifest_check(self.manifest)

    def test_runtime_cannot_be_smuggled_as_format_one(self):
        self.manifest.update(format=1, manifest_version=1)
        with self.assertRaisesRegex(ValueError, 'require manifest_version 2'):
            dev.manifest_check(self.manifest)

    def test_missing_unknown_and_duplicate_permissions_fail(self):
        for permissions in ([], ['background'], ['window'], ['background', 'window', 'root'],
                            ['background', 'window', 'window'], 'background'):
            with self.subTest(permissions=permissions):
                m = copy.deepcopy(self.manifest)
                m['permissions'] = permissions
                with self.assertRaises(ValueError):
                    dev.manifest_check(m)

    def test_no_autostart_shell_commands_or_web_ui(self):
        for update in ({'background': {'entry_point': self.path, 'autostart': True}},
                       {'background': {'command': 'sh -c anything'}},
                       {'background': {'entry_point': self.path, 'args': ['bad\x00arg']}},
                       {'window': {'type': 'web', 'entry_point': self.path}}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                dev.manifest_check(dict(self.manifest, **update))

    def test_entry_must_be_executable_in_the_package(self):
        self.manifest['background']['entry_point'] = '/bin/sh'
        with self.assertRaisesRegex(ValueError, 'Entry point'):
            dev.manifest_check(self.manifest)

    def test_runtime_package_cannot_install_global_commands(self):
        self.manifest['files']['usr/bin/example'] = {'mode': 0o644, 'sha256': 'b' * 64}
        with self.assertRaisesRegex(ValueError, 'beneath'):
            dev.manifest_check(self.manifest)

    def test_runtime_is_selected_independently(self):
        self.manifest['background']['runtime'] = 'node'
        self.manifest['window']['runtime'] = 'bash'
        self.manifest['executables'] = []
        self.manifest['files'][self.path]['mode'] = 0o644
        dev.manifest_check(self.manifest)

    def test_native_still_requires_executable(self):
        self.manifest['executables'] = []
        with self.assertRaisesRegex(ValueError, 'Native entry point'):
            dev.manifest_check(self.manifest)

    def test_unknown_runtime_paths_and_shell_fragments_rejected(self):
        for runtime in ('ruby', '/usr/bin/node', 'bash -c', ['node'], None):
            with self.subTest(runtime=runtime):
                self.manifest['background']['runtime'] = runtime
                with self.assertRaisesRegex(ValueError, 'Unsupported runtime'):
                    dev.manifest_check(self.manifest)

    def test_all_named_runtimes_accept_packaged_scripts(self):
        for runtime in ('node', 'bash', 'sh', 'python'):
            with self.subTest(runtime=runtime):
                m = copy.deepcopy(self.manifest)
                for kind in ('background', 'window'):
                    m[kind]['runtime'] = runtime
                m['executables'] = []
                m['files'][self.path]['mode'] = 0o644
                dev.manifest_check(m)


if __name__ == '__main__':
    unittest.main()
