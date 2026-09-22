import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOLS = Path(__file__).parents[1] / 'tools'


def load_module(name, file_name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / file_name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


settings = load_module('dev_settings_mode', 'dev_settings.py')
shell = load_module('dev_shell_mode', 'dev_shell.py')
DEV = [sys.executable, str(TOOLS / 'dev.py')]


class ModeFile(unittest.TestCase):
    def test_desktop_is_the_default_when_no_file_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(settings.read_mode(directory), 'desktop')

    def test_write_and_read_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            settings.write_mode(directory, 'server')
            self.assertEqual(settings.read_mode(directory), 'server')
            self.assertEqual((Path(directory) / 'etc/devos/mode').read_text(),
                             'server\n')
            settings.write_mode(directory, 'desktop')
            self.assertEqual(settings.read_mode(directory), 'desktop')

    def test_invalid_mode_and_corrupt_file_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                settings.write_mode(directory, 'kiosk')
            path = Path(directory) / 'etc/devos/mode'
            path.parent.mkdir(parents=True)
            path.write_text('toaster\n')
            with self.assertRaises(ValueError):
                settings.read_mode(directory)


class ModeCommand(unittest.TestCase):
    def test_cli_shows_and_sets_the_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            show = subprocess.run(DEV + ['--root', directory, 'mode'],
                                  capture_output=True, text=True)
            self.assertEqual(show.stdout.strip(), 'desktop')
            for mode in ('server', 'desktop'):
                result = subprocess.run(DEV + ['--root', directory, 'mode', 'set', mode],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('Mode set to ' + mode, result.stdout)
                self.assertEqual(settings.read_mode(directory), mode)
            bad = subprocess.run(DEV + ['--root', directory, 'mode', 'set', 'kiosk'],
                                 capture_output=True, text=True)
            self.assertNotEqual(bad.returncode, 0)
            usage = subprocess.run(DEV + ['--root', directory, 'mode', 'toggle'],
                                   capture_output=True, text=True)
            self.assertNotEqual(usage.returncode, 0)


class ShellGate(unittest.TestCase):
    def test_shell_only_runs_in_desktop_mode(self):
        self.assertIsNone(shell.mode_error('desktop'))
        message = shell.mode_error('server')
        self.assertIn('desktop mode only', message)
        self.assertIn('dev mode set desktop', message)


if __name__ == '__main__':
    unittest.main()
