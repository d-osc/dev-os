import copy
import importlib.util
from pathlib import Path
import unittest
import uuid

spec = importlib.util.spec_from_file_location('dev_slots', Path(__file__).parents[1] / 'tools/dev_slots.py')
slots = importlib.util.module_from_spec(spec)
spec.loader.exec_module(slots)


class Slots(unittest.TestCase):
    def setUp(self):
        self.metadata = {'version': 1, 'layout': 'ab', 'slot': 'A', 'shared_mounts': ['/home'], 'partitions': {}}
        self.devices = []
        for number, name in enumerate(('efi', 'boot', 'A', 'B', 'home'), 1):
            part = {'number': number, 'partuuid': str(uuid.uuid4()), 'uuid': str(uuid.uuid4())}
            self.metadata['partitions'][name] = part
            self.devices.append(dict(part, path='/dev/vda' + str(number), device='252:' + str(number),
                                     parent='/sys/devices/disk', fstype='vfat' if name == 'efi' else 'ext4',
                                     read_only=False, holders=False))
        self.commandline = 'root=PARTUUID=' + self.metadata['partitions']['A']['partuuid'] + ' devos.slot=A'
        self.mounts = [{'target': path, 'device': '252:' + str(number), 'root': '/',
                        'options': ['rw'], 'super_options': ['rw'], 'fstype': 'vfat' if number == 1 else 'ext4'}
                       for path, number in (('/', 3), ('/boot', 2), ('/boot/efi', 1), ('/home', 5))]

    def check(self):
        return slots.validate(self.metadata, self.commandline, self.mounts, self.devices, set())

    def test_resolves_inactive_slot_from_partition_identity(self):
        self.assertEqual(self.check()['target'], '/dev/vda4')
        self.metadata['slot'] = 'B'
        self.commandline = 'root=PARTUUID=' + self.metadata['partitions']['B']['partuuid'] + ' devos.slot=B'
        self.mounts[0]['device'] = '252:4'
        self.assertEqual(self.check()['inactive'], 'A')

    def test_kernel_slot_and_root_must_match_exactly_once(self):
        original = self.commandline
        for value in ('devos.slot=B', original + ' devos.slot=A', original + ' root=/dev/vda3',
                      original.replace('devos.slot=A', 'devos.slot=B')):
            with self.subTest(value=value):
                self.commandline = value
                with self.assertRaises(ValueError): self.check()

    def test_clone_and_wrong_disk_are_rejected(self):
        self.devices.append(copy.deepcopy(self.devices[3]))
        with self.assertRaisesRegex(ValueError, 'ambiguous'): self.check()
        self.devices.pop()
        self.devices[3]['parent'] = '/sys/devices/other-disk'
        with self.assertRaisesRegex(ValueError, 'one disk'): self.check()

    def test_inactive_mount_swap_and_holders_are_rejected(self):
        self.mounts.append(dict(self.mounts[0], target='/mnt/other', device='252:4'))
        with self.assertRaisesRegex(ValueError, 'already mounted'): self.check()
        self.mounts.pop()
        with self.assertRaisesRegex(ValueError, 'swap'):
            slots.validate(self.metadata, self.commandline, self.mounts, self.devices, {'252:4'})
        self.devices[3]['holders'] = True
        with self.assertRaisesRegex(ValueError, 'unsuitable'): self.check()

    def test_bind_mount_readonly_wrong_uuid_and_overmount_are_rejected(self):
        for key, value in (('root', '/subdir'), ('device', '252:4'), ('options', ['ro']),
                           ('super_options', ['ro'])):
            original = copy.deepcopy(self.mounts)
            with self.subTest(key=key):
                self.mounts[0][key] = value
                with self.assertRaises(ValueError): self.check()
            self.mounts = original
        self.mounts.append(copy.deepcopy(self.mounts[0]))
        with self.assertRaisesRegex(ValueError, 'overmounted'): self.check()
        self.mounts.pop()
        self.devices[3]['uuid'] = str(uuid.uuid4())
        with self.assertRaisesRegex(ValueError, 'identity mismatch'): self.check()

    def test_mountinfo_decodes_escaped_paths_and_optional_fields(self):
        result = slots.mountinfo('40 22 252:4 / /mnt/a\\040b rw,relatime shared:4 - ext4 /dev/vda4 rw\n')
        self.assertEqual(result[0]['target'], '/mnt/a b')
        self.assertEqual(result[0]['device'], '252:4')
        with self.assertRaisesRegex(ValueError, 'Malformed'): slots.mountinfo('invalid')
