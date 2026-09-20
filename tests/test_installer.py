import copy
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('installer', Path(__file__).parents[1] / 'installer/devos-install.py')
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class InstallerSafety(unittest.TestCase):
    def setUp(self):
        self.disk = {'name': '/dev/devos-test-only', 'type': 'disk', 'size': 16 * 1024**3,
                     'ro': False, 'serial': 'test', 'maj:min': '240:0', 'model': 'Test disk',
                     'mountpoints': [None], 'children': []}

    def test_unused_disk_allowed(self):
        self.assertIsNone(installer.rejection(self.disk))

    @unittest.skipUnless(shutil.which('sfdisk'), 'Requires GPT utility')
    def test_ab_layout_on_disposable_regular_file(self):
        system, layout = installer.system_layout()
        with tempfile.TemporaryDirectory() as temporary:
            disk = Path(temporary) / 'layout.raw'
            with disk.open('wb') as stream:
                stream.truncate(installer.MIN_DISK)
            subprocess.run(['sfdisk', str(disk)], input=layout, text=True, check=True, capture_output=True)
            table = json.loads(subprocess.check_output(['sfdisk', '--json', str(disk)], text=True))['partitiontable']
            parts = table['partitions']
            self.assertEqual(len(parts), 5)
            for index, name in enumerate(('efi', 'boot', 'A', 'B', 'home')):
                self.assertEqual(parts[index]['uuid'].lower(), system[name]['partuuid'])
            self.assertEqual(parts[2]['size'] * table['sectorsize'], 4 * 1024**3)
            self.assertEqual(parts[3]['size'] * table['sectorsize'], 4 * 1024**3)
            self.assertGreater(parts[4]['size'] * table['sectorsize'], 6 * 1024**3)

    @unittest.skipUnless(os.name == 'posix' and shutil.which('grub-editenv'), 'Requires Linux GRUB tools')
    def test_ab_target_has_shared_mounts_and_boot_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            etc = target / 'etc'; etc.mkdir()
            (target / 'home').mkdir()
            for name, content in {'passwd': 'root:x:0:0:root:/root:/bin/sh\n',
                'shadow': 'root:!:19000:0:99999:7:::\n', 'group': 'root:x:0:\nwheel:x:10:\n',
                'fstab': '/dev/root / ext4 defaults 0 1\n', 'inittab': 'ttyS0::respawn:/sbin/getty ttyS0\n'}.items():
                (etc / name).write_text(content)
            system, _ = installer.system_layout()
            with mock.patch.object(installer.os, 'chown'):
                installer.configure_target(target, 'tester', 'devos-test', '!', '!',
                    system['A']['uuid'], system['A']['partuuid'], system['efi']['partuuid'], system)
            mounts = [line.split()[1] for line in (etc / 'fstab').read_text().splitlines()]
            self.assertEqual(mounts, ['/', '/boot', '/boot/efi', '/home'])
            metadata = json.loads((etc / 'devos-system.json').read_text())
            self.assertEqual(metadata['slot'], 'A')
            self.assertFalse(metadata['slots']['B']['initialized'])
            subprocess.run(['grub-script-check', str(target / 'boot/grub/grub.cfg')], check=True, capture_output=True)
            self.assertTrue((target / 'boot/grub/devos.env').is_file())

    def test_mounted_descendant_is_blocked(self):
        self.disk['children'] = [{'name': '/dev/devos-test-only1', 'type': 'part', 'mountpoints': ['/']}]
        self.assertIn('mounted', installer.rejection(self.disk))

    def test_installer_media_is_blocked(self):
        self.disk['fstype'] = 'iso9660'
        self.assertIn('media', installer.rejection(self.disk))

    def test_installer_label_is_blocked(self):
        self.disk['label'] = 'DEVOS_LIVE'
        self.assertIn('media', installer.rejection(self.disk))

    def test_swap_is_blocked(self):
        self.assertIn('swap', installer.rejection(self.disk, [self.disk['name']]))

    def test_readonly_small_and_non_disk_are_blocked(self):
        for change in ({'ro': True}, {'size': 1024}, {'type': 'loop'}, {'type': 'part'}):
            disk = dict(self.disk, **change)
            with self.subTest(change=change):
                self.assertIsNotNone(installer.rejection(disk))

    def test_mapped_descendant_is_blocked(self):
        self.disk['children'] = [{'name': '/dev/mapper/test-only', 'type': 'crypt', 'mountpoints': [None]}]
        self.assertIn('mapped', installer.rejection(self.disk))

    def test_partition_names_for_nvme_sata_and_virtio(self):
        self.assertEqual(installer.partition_name('/dev/nvme0n1', 2), '/dev/nvme0n1p2')
        self.assertEqual(installer.partition_name('/dev/sda', 1), '/dev/sda1')
        self.assertEqual(installer.partition_name('/dev/vda', 2), '/dev/vda2')

    def test_disk_change_refuses_before_any_commands(self):
        changed = copy.deepcopy(self.disk)
        changed['serial'], changed['blocked'] = 'replacement', None
        with mock.patch.object(installer, 'disks', return_value=[changed]), mock.patch.object(installer, 'run') as commands:
            with self.assertRaisesRegex(RuntimeError, 'changed'):
                installer.install(self.disk, 'dev', 'dev-os', 'unused', 'unused')
            commands.assert_not_called()

    def test_payload_corruption_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'rootfs.tar.gz').write_bytes(b'corrupt')
            (root / 'manifest.json').write_text(json.dumps({'files': dict.fromkeys(
                ['rootfs.tar.gz', 'bzImage'], '0' * 64)}))
            with mock.patch.object(installer, 'PAYLOAD', root):
                with self.assertRaisesRegex(RuntimeError, 'checksum'):
                    installer.verify_payload()

    @unittest.skipUnless(os.name == 'posix', 'Linux libcrypt required')
    def test_runtime_password_hash_uses_sha512_and_random_salts(self):
        first = installer.password_hash('installer-unit-test-password')
        second = installer.password_hash('installer-unit-test-password')
        self.assertTrue(first.startswith('$6$') and second.startswith('$6$'))
        self.assertNotEqual(first, second)


if __name__ == '__main__':
    unittest.main()
