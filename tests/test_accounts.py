"""Regression coverage for Buildroot's make escaping of root password hashes."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(shutil.which('openssl'), 'openssl is required for test-VM accounts')
class TestAccounts(unittest.TestCase):
    def test_generated_accounts_authenticate_and_survive_reconfigure(self):
        script = Path(__file__).parents[1] / 'scripts/test-accounts.py'
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            config = out / '.config'

            def generate():
                subprocess.run([sys.executable, str(script), str(config), str(out)],
                               check=True, capture_output=True, text=True)

            generate()
            credentials = json.loads((out / 'vm-credentials.json').read_text())
            root_line = next(x for x in config.read_text().splitlines()
                             if x.startswith('BR2_TARGET_GENERIC_ROOT_PASSWD='))
            escaped = json.loads(root_line.split('=', 1)[1])
            self.assertTrue(escaped.startswith('$$6$$'))
            hashes = {'root': escaped.replace('$$', '$'),
                      'dev': (out / 'vm-users.txt').read_text().split()[4]}
            for user, stored in hashes.items():
                salt = stored.split('$')[2]
                computed = subprocess.run(['openssl', 'passwd', '-6', '-salt', salt, '-stdin'],
                                          input=credentials[user] + '\n', text=True,
                                          capture_output=True, check=True).stdout.strip()
                # Avoid putting credential/hash contents into test output.
                self.assertTrue(computed == stored, user + ' password hash mismatch')
            generate()
            self.assertTrue(json.loads((out / 'vm-credentials.json').read_text()) == credentials)


if __name__ == '__main__':
    unittest.main()
