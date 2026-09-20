import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('dev_cli_test', Path(__file__).parents[1] / 'tools/dev.py')
dev = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dev)


class CliManifest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source, self.root = self.base / 'source', self.base / 'root'
        self.path = 'opt/apps/cli-example/main.sh'
        script = self.source / 'payload' / self.path
        script.parent.mkdir(parents=True)
        script.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        self.manifest = {'manifest_version': 2, 'name': 'cli-example', 'version': '1',
                         'arch': 'all', 'permissions': [], 'executables': [self.path],
                         'cli': {'commands': {'my-tool': {'runtime': 'sh', 'entry_point': self.path,
                                                        'args': ['fixed value', '$(echo unsafe)']}}}}
        self.package = self.base / 'cli.dpk'

    def build(self):
        (self.source / 'manifest.json').write_text(json.dumps(self.manifest))
        dev.build(self.source, self.package)

    def test_cli_install_remove_and_inventory(self):
        self.build(); dev.install(self.root, self.package)
        wrapper = self.root / 'usr/bin/my-tool'
        text = wrapper.read_text()
        self.assertIn("'fixed value' '$(echo unsafe)'", text)
        db = json.loads((self.root / 'var/lib/dev/installed.json').read_text())
        dev.manifest_check(db['cli-example'])
        self.assertIn('usr/bin/my-tool', db['cli-example']['installed_commands'])
        self.assertNotIn('usr/bin/my-tool', db['cli-example']['files'])
        dev.remove(self.root, 'cli-example')
        self.assertFalse(wrapper.exists())
        self.assertFalse((self.root / self.path).exists())

    @unittest.skipIf(os.name == 'nt', 'POSIX shell required')
    def test_launcher_forwards_arguments_without_shell_evaluation(self):
        self.build(); dev.install(self.root, self.package)
        wrapper = self.root / 'usr/bin/my-tool'
        # Point the launcher to the disposable root so no host /opt files are written.
        wrapper.write_text(wrapper.read_text().replace('/' + self.path, str(self.root / self.path)))
        output = subprocess.check_output(['/bin/sh', str(wrapper), 'two words', '--help', ''], text=True)
        self.assertEqual(output, 'fixed value\n$(echo unsafe)\ntwo words\n--help\n\n')

    def test_all_runtimes_validate_and_pack(self):
        for runtime in ('native', 'node', 'bash', 'sh', 'python'):
            self.manifest['cli']['commands']['my-tool']['runtime'] = runtime
            self.build()

    def test_bad_cli_declarations(self):
        good = json.loads(json.dumps(self.manifest))
        for cli in ({'commands': {}}, {'commands': {'dev': {'entry_point': self.path}}},
                    {'commands': {'../bad': {'entry_point': self.path}}},
                    {'commands': {'tool': {'entry_point': 'opt/missing'}}},
                    {'commands': {'tool': {'entry_point': self.path, 'runtime': 'unknown'}}},
                    {'commands': {'tool': {'entry_point': self.path, 'args': ['a\0b']}}}):
            self.manifest = dict(good, cli=cli)
            with self.subTest(cli=cli), self.assertRaises(ValueError): self.build()
        self.manifest = good; self.manifest['executables'] = []
        self.manifest['cli']['commands']['my-tool']['runtime'] = 'native'
        with self.assertRaisesRegex(ValueError, 'executables'): self.build()

    def test_command_conflict_writes_no_payload(self):
        self.build()
        command = self.root / 'usr/bin/my-tool'
        command.parent.mkdir(parents=True); command.write_text('existing')
        with self.assertRaisesRegex(ValueError, 'conflict'): dev.install(self.root, self.package)
        self.assertEqual(command.read_text(), 'existing')
        self.assertFalse((self.root / self.path).exists())

    def test_modified_launcher_blocks_removal(self):
        self.build(); dev.install(self.root, self.package)
        (self.root / 'usr/bin/my-tool').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'modified'): dev.remove(self.root, 'cli-example')
        self.assertTrue((self.root / self.path).exists())

    def test_rollback_removes_generated_launcher(self):
        self.build()
        with mock.patch.object(dev, 'save', side_effect=OSError('failed')):
            with self.assertRaises(OSError): dev.install(self.root, self.package)
        self.assertFalse((self.root / self.path).exists())
        self.assertFalse((self.root / 'usr/bin/my-tool').exists())

    def test_installer_inventory_cannot_be_supplied_in_source(self):
        self.manifest['installed_commands'] = {}
        with self.assertRaisesRegex(ValueError, 'reserved'): self.build()
