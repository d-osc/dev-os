"""Dependency checks and real compiled ELF compatibility, without executing payloads."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from test_repository import load
dev = load('dev')
compat = load('dev_compat')


class Dependencies(unittest.TestCase):
    def test_package_operations_preserve_dependency_consistency(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / 'root'
            def package(name, version, dependencies=None):
                source = base / (name + version)
                (source / 'payload/usr/share' / name).mkdir(parents=True)
                (source / 'payload/usr/share' / name / 'version').write_text(version)
                manifest = {'name': name, 'version': version, 'arch': 'all'}
                if dependencies:
                    manifest['dependencies'] = dependencies
                (source / 'manifest.json').write_text(json.dumps(manifest))
                archive = base / (name + version + '.dpk')
                dev.build(source, archive)
                return archive
            lib1 = package('lib', '1')
            lib2 = package('lib', '2')
            lib3 = package('lib', '3')
            app = package('app', '1', {'lib': '>=2,<3'})
            with self.assertRaisesRegex(ValueError, 'Missing dependency'):
                dev.install(root, app)
            self.assertFalse((root / 'usr/share/app/version').exists())
            dev.install(root, lib1)
            with dev.database(root) as (db, path):
                dev.install_locked(root, lib2, db, path, replacement='upgrade')
            dev.install(root, app)
            with self.assertRaisesRegex(ValueError, 'Missing dependency'):
                dev.remove(root, 'lib')
            with self.assertRaisesRegex(ValueError, 'Dependency conflict'):
                with dev.database(root) as (db, path):
                    dev.install_locked(root, lib3, db, path, replacement='upgrade')
            with self.assertRaisesRegex(ValueError, 'Dependency conflict'):
                dev.rollback(root, 'lib')
            with dev.database(root) as (db, _):
                self.assertEqual(db['lib']['version'], '2')
                self.assertIn('app', db)
            self.assertEqual((root / 'usr/share/lib/version').read_text(), '2')
            self.assertFalse((root / 'var/lib/dev/transaction').exists())
            dev.remove(root, 'app')
            dev.rollback(root, 'lib')
            self.assertEqual((root / 'usr/share/lib/version').read_text(), '1')

    def test_missing_and_incompatible_dependencies(self):
        app = {'name': 'app', 'version': '1', 'dependencies': {'lib': '>=2,<3'}}
        with self.assertRaisesRegex(ValueError, 'Missing dependency'):
            compat.check_dependencies({'app': app}, dev)
        with self.assertRaisesRegex(ValueError, 'Dependency conflict'):
            compat.check_dependencies({'app': app, 'lib': {'name': 'lib', 'version': '1'}}, dev)
        compat.check_dependencies({'app': app, 'lib': {'name': 'lib', 'version': '2.1'}}, dev)

    def test_invalid_manifest_requirements(self):
        for update in ({'depends': {}}, {'dependencies': {'app': '*'}},
                       {'dependencies': {'../lib': '*'}}, {'dependencies': {'lib': 'latest'}},
                       {'runtime_versions': {'native': '>=1'}}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                dev.manifest_requirements(dict(name='app', **update))

    @unittest.skipIf(os.name == 'nt', 'POSIX symlink semantics')
    def test_absolute_symlink_resolves_inside_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'usr/lib').mkdir(parents=True)
            (root / 'lib').symlink_to('/usr/lib')
            self.assertEqual(compat.resolve_base(root, 'lib/test.so', dev), root / 'usr/lib/test.so')
            with self.assertRaisesRegex(ValueError, 'escapes'):
                compat.resolve_base(root, '../../etc/passwd', dev)

    def test_runtime_version_requirement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'usr/lib/devos').mkdir(parents=True)
            (root / 'usr/bin').mkdir()
            (root / 'usr/bin/node').write_bytes(b'base runtime fixture')
            (root / 'usr/bin/node').chmod(0o755)
            (root / 'usr/lib/devos/platform.json').write_text(json.dumps({
                'arch': 'x86_64', 'runtimes': {'node': '22.0.0'}}))
            m = {'name': 'app', 'version': '1', 'arch': 'all', 'files': {}, 'runtime_versions': {'node': '>=24'}}
            with self.assertRaisesRegex(ValueError, 'Incompatible runtime'):
                compat.check_install(root, m, root, {}, dev)
            m['runtime_versions']['node'] = '>=22'
            compat.check_install(root, m, root, {}, dev)


@unittest.skipUnless(os.name == 'posix' and shutil.which('gcc') and importlib.util.find_spec('elftools'),
                     'Requires Linux compiler and pyelftools')
class ELFCompatibility(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'root'
        self.source = self.base / 'source'
        self.payload = self.source / 'payload/opt/apps/app'
        (self.payload / 'lib').mkdir(parents=True)
        (self.root / 'usr/lib/devos').mkdir(parents=True)
        (self.root / 'lib64').mkdir()
        (self.root / 'lib/x86_64-linux-gnu').mkdir(parents=True)
        shutil.copyfile('/lib64/ld-linux-x86-64.so.2', self.root / 'lib64/ld-linux-x86-64.so.2')
        shutil.copyfile('/lib/x86_64-linux-gnu/libc.so.6', self.root / 'lib/x86_64-linux-gnu/libc.so.6')
        (self.root / 'usr/lib/devos/platform.json').write_text(json.dumps({
            'arch': 'x86_64', 'runtimes': {}, 'library_dirs': ['lib64', 'lib/x86_64-linux-gnu']}))
        (self.base / 'lib.c').write_text('int foo(void) { return 42; }\n')
        (self.base / 'app.c').write_text('extern int foo(void); int main(void) { return foo(); }\n')
        self.library('DEVOS_TEST_1')
        subprocess.run(['gcc', str(self.base / 'app.c'), '-L' + str(self.payload / 'lib'), '-ltest',
                        '-Wl,-rpath,$ORIGIN/lib', '-o', str(self.payload / 'app')], check=True, capture_output=True)
        self.manifest = {'name': 'app', 'version': '1', 'arch': 'x86_64',
                         'executables': ['opt/apps/app/app']}

    def library(self, version):
        (self.base / 'version.map').write_text(version + ' { global: foo; local: *; };\n')
        subprocess.run(['gcc', '-shared', '-fPIC', str(self.base / 'lib.c'),
                        '-Wl,--version-script=' + str(self.base / 'version.map'), '-Wl,-soname,libtest.so',
                        '-o', str(self.payload / 'lib/libtest.so')], check=True, capture_output=True)

    def check(self):
        (self.source / 'manifest.json').write_text(json.dumps(self.manifest))
        m = dev.prepare_manifest(self.source)
        compat.check_install(self.root, m, self.source / 'payload', {}, dev)

    def test_compiled_binary_and_origin_library_are_compatible(self):
        self.check()

    def test_batch_uses_planned_library_abi_instead_of_installed_library(self):
        name = 'opt/apps/app/lib/libtest.so'
        installed = self.root / name
        installed.parent.mkdir(parents=True)
        shutil.copyfile(self.payload / 'lib/libtest.so', installed)
        self.library('DEVOS_TEST_0')
        proposed = self.base / 'new-library.so'
        (self.payload / 'lib/libtest.so').rename(proposed)
        (self.source / 'manifest.json').write_text(json.dumps(self.manifest))
        m = dev.prepare_manifest(self.source)
        compat.check_install(self.root, m, self.source / 'payload', {}, dev)
        with self.assertRaisesRegex(ValueError, 'Missing ABI symbol versions'):
            compat.check_install(self.root, m, self.source / 'payload', {}, dev,
                                 planned_files={name: proposed})
        with self.assertRaisesRegex(ValueError, 'Missing shared library'):
            compat.check_install(self.root, m, self.source / 'payload', {}, dev,
                                 removed_files={name})

    def test_missing_shared_library_is_rejected(self):
        (self.payload / 'lib/libtest.so').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing shared library'):
            self.check()

    def test_missing_symbol_version_is_rejected(self):
        self.library('DEVOS_TEST_0')
        with self.assertRaisesRegex(ValueError, 'Missing ABI symbol versions'):
            self.check()

    def test_wrong_elf_architecture_is_rejected(self):
        path = self.payload / 'app'
        data = bytearray(path.read_bytes())
        struct.pack_into('<H', data, 18, 183)
        path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'Only x86_64'):
            self.check()

    def test_native_payload_cannot_claim_arch_all(self):
        self.manifest['arch'] = 'all'
        with self.assertRaisesRegex(ValueError, 'arch: x86_64'):
            self.check()

    def test_missing_elf_interpreter_is_rejected(self):
        (self.root / 'lib64/ld-linux-x86-64.so.2').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing ELF interpreter'):
            self.check()
