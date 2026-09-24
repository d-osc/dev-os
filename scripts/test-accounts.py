#!/usr/bin/env python3
"""Create unique local test-VM credentials; never use shared default passwords."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

config, out = Path(sys.argv[1]), Path(sys.argv[2]).resolve()
out.mkdir(parents=True, exist_ok=True)
os.umask(0o077)
credentials = out / 'vm-credentials.json'
if credentials.exists():
    accounts = json.loads(credentials.read_text())
else:
    accounts = {user: secrets.token_urlsafe(18) for user in ('root', 'dev')}
    credentials.write_text(json.dumps(accounts, indent=2) + '\n')
    credentials.chmod(0o600)

def hashed(user):
    return subprocess.run(['openssl', 'passwd', '-6', '-stdin'],
                          input=accounts[user] + '\n', text=True,
                          capture_output=True, check=True).stdout.strip()

users = out / 'vm-users.txt'
users.write_text(f'dev 1000 dev 1000 {hashed("dev")} /home/dev /bin/sh wheel,audio Dev OS tester\n')
with config.open('a') as f:
    f.write('\nBR2_TARGET_ENABLE_ROOT_LOGIN=y\n')
    # Buildroot includes .config from make: literal dollars must be doubled.
    f.write('BR2_TARGET_GENERIC_ROOT_PASSWD=' + json.dumps(hashed('root').replace('$', '$$')) + '\n')
    f.write('BR2_ROOTFS_USERS_TABLES=' + json.dumps(str(users)) + '\n')
print('Local VM accounts configured; passwords saved in ' + str(credentials))
