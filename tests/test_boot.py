"""Validate the boot policy with real GRUB utilities before installer integration."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('dev_boot', Path(__file__).parents[1] / 'tools/dev_boot.py')
boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot)
BOOT = '12345678-1234-4234-8234-123456789abc'
ROOTS = {'A': '11111111-1111-4111-8111-111111111111', 'B': '22222222-2222-4222-8222-222222222222'}


class BootPolicy(unittest.TestCase):
    def test_reject_invalid_identity_and_duplicate_roots(self):
        for roots, confirmed in (({'A': ROOTS['A'], 'B': ROOTS['A']}, 'A'),
                                 ({'A': ROOTS['A']}, 'A'), (ROOTS, 'C')):
            with self.assertRaises(ValueError):
                boot.render(BOOT, roots, confirmed)
        with self.assertRaises(ValueError):
            boot.render('x; reboot', ROOTS, 'A')

    @unittest.skipUnless(shutil.which('grub-script-check'), 'Requires GRUB syntax checker')
    def test_real_grub_accepts_both_confirmed_slots(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            for confirmed in ('A', 'B'):
                boot.publish_config(path, BOOT, ROOTS, confirmed, serial=True)
                subprocess.run(['grub-script-check', str(path / 'grub/grub.cfg')], check=True, capture_output=True)
                self.assertFalse(list((path / 'grub').glob('devos-cfg-*')))

    @unittest.skipUnless(shutil.which('grub-editenv'), 'Requires GRUB environment utility')
    def test_real_grub_environment_schedule_and_cancel(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            (path / 'grub').mkdir()
            boot.environment(path, initialize=True)
            environment = path / 'grub/devos.env'
            size = environment.stat().st_size
            boot.environment(path, trial='B')
            result = subprocess.check_output(['grub-editenv', str(environment), 'list'], text=True)
            self.assertIn('next_entry=devos-B', result)
            boot.environment(path)
            result = subprocess.check_output(['grub-editenv', str(environment), 'list'], text=True)
            self.assertNotIn('next_entry=', result)
            self.assertEqual(environment.stat().st_size, size)
            with self.assertRaises(ValueError):
                boot.environment(path, initialize=True)
