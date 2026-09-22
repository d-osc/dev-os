import importlib.util
import os
from pathlib import Path
import unittest

TOOLS = Path(__file__).parents[1] / 'tools'


def load_module(name, file_name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / file_name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


greeter = load_module('dev_greeter_local', 'dev_greeter.py')
gui = load_module('dev_gui_greeter', 'dev_gui.py')

PASSWD = '''root:x:0:0:root:/root:/bin/sh
ondev:x:1000:1000:On Dev,,,:/home/ondev:/bin/sh
builder:x:1001:1001:Builder:/home/builder:/sbin/nologin
robot:x:998:998:Robot:/tmp:/bin/false
legacy:x:1200:1200:Legacy User:/home/legacy:/bin/sh
nobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin
'''
SHADOW = ('ondev:$6$devosdemo$WA2Ht8Zj7dChjCnHgZEWb0hZq6I5t47MwrIMytDcyuRJwG44jM9Vf'
          '7IEN5REag5mp.vJKxr1IRm5.gAsZtzxg.:19000:0:99999:7:::\n'
          'locked:$6$x$y!:19000:0:99999:7:::\n'
          'empty::19000:0:99999:7:::\n')
PASSWORD = 'devos-demo-pass'


class Users(unittest.TestCase):
    def test_login_users_lists_human_accounts_only(self):
        self.assertEqual(greeter.login_users(PASSWD),
                         [('legacy', 'Legacy User'), ('ondev', 'On Dev')])

    def test_shadow_parsing(self):
        hashes = greeter.shadow_hashes(SHADOW)
        self.assertTrue(hashes['ondev'].startswith('$6$'))
        self.assertEqual(hashes['empty'], '')


class Authentication(unittest.TestCase):
    def test_fixture_hash_verifies_on_crypt_systems(self):
        if os.name != 'posix':
            self.skipTest('libcrypt verification needs POSIX')
        self.assertTrue(greeter.authenticate('ondev', PASSWORD, SHADOW))
        self.assertFalse(greeter.authenticate('ondev', 'wrong', SHADOW))
        self.assertFalse(greeter.authenticate('missing', PASSWORD, SHADOW))
        self.assertFalse(greeter.authenticate('empty', '', SHADOW))


class EntryWidget(unittest.TestCase):
    def entry(self):
        return gui.Entry(10, 20, 200, 36, label='User', placeholder='name')

    def test_typing_backspace_and_submit(self):
        entry = self.entry()
        self.assertIsNone(entry.feed(0, 'o'))
        self.assertIsNone(entry.feed(0, 'n'))
        entry.feed(gui.KEYSYM_BACKSPACE, '')
        entry.feed(0, 'd')
        self.assertEqual(entry.text, 'od')
        self.assertEqual(entry.feed(gui.KEYSYM_RETURN, ''), 'submit')
        self.assertEqual(entry.display_text(), 'od')

    def test_masking_escape_and_limits(self):
        entry = gui.Entry(0, 0, 100, 30, masked=True, placeholder='password')
        for character in 'secret':
            entry.feed(0, character)
        self.assertEqual(entry.display_text(), '******')
        self.assertEqual(entry.feed(gui.KEYSYM_ESCAPE, ''), 'clear')
        self.assertEqual(entry.text, '')
        for _ in range(100):
            entry.feed(0, 'x')
        self.assertEqual(len(entry.text), entry.LIMIT)
        entry.feed(0, '\t')
        entry.feed(0x100, 'q')          # non-ASCII keysym chars are ignored
        self.assertEqual(entry.text, 'x' * entry.LIMIT)


if __name__ == '__main__':
    unittest.main()
