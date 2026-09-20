import importlib.util
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('native_binary_test', Path(__file__).parents[1] / 'tools/dev_runtime.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class NativeBinary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'app.bin'
        self.header = bytearray(64)
        self.header[:7] = b'\x7fELF\x02\x01\x01'
        struct.pack_into('<HH', self.header, 16, 2, 62)
        struct.pack_into('<Q', self.header, 32, 64)
        struct.pack_into('<HH', self.header, 54, 56, 1)

    def write(self, program=None, trailer=b''):
        self.path.write_bytes(self.header + (program or bytes(56)) + trailer)

    def test_static_elf_header_and_native_script(self):
        self.write()
        with mock.patch.object(runtime.platform, 'machine', return_value='x86_64'):
            runtime.validate_native(self.path, 'x86_64')
        self.path.write_bytes(b'#!/bin/sh\nexit 0\n')
        runtime.validate_native(self.path, 'all')

    def test_windows_executable_rejected(self):
        self.path.write_bytes(b'MZ' + bytes(100))
        with self.assertRaisesRegex(ValueError, 'Linux ELF'):
            runtime.validate_native(self.path, 'x86_64')

    def test_wrong_arch_and_arch_all_rejected(self):
        self.write()
        with self.assertRaisesRegex(ValueError, 'arch: x86_64'):
            runtime.validate_native(self.path, 'all')
        struct.pack_into('<H', self.header, 18, 183)
        self.write()
        with self.assertRaisesRegex(ValueError, 'Only x86_64'):
            runtime.validate_native(self.path, 'x86_64')

    def test_truncated_program_headers_rejected(self):
        self.path.write_bytes(self.header)
        with mock.patch.object(runtime.platform, 'machine', return_value='x86_64'):
            with self.assertRaisesRegex(ValueError, 'program headers'):
                runtime.validate_native(self.path, 'x86_64')

    @unittest.skipIf(os.name == 'nt', 'Linux loader paths require POSIX')
    def test_missing_loader_is_reported(self):
        loader = b'/lib64/devos-test-missing-loader.so\0'
        program = bytearray(56)
        struct.pack_into('<I', program, 0, 3)
        struct.pack_into('<Q', program, 8, 120)
        struct.pack_into('<Q', program, 32, len(loader))
        self.write(program, loader)
        with mock.patch.object(runtime.platform, 'machine', return_value='x86_64'):
            with self.assertRaisesRegex(ValueError, 'Missing ELF loader'):
                runtime.validate_native(self.path, 'x86_64')


if __name__ == '__main__':
    unittest.main()
