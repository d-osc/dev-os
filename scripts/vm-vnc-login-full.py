"""Full GUI login: Tab into the password field, type it, press Return.

The dev password comes from out/vm-credentials.json so a credential
rotation never silently breaks this helper.
"""
import json
import os
import sys
import time

sys.path.insert(0, '/home/ondev/.local/lib/python3.12/site-packages')
from vncdotool import api

CREDENTIALS = [
    '/home/ondev/src/dev-os-build/project/out/vm-credentials.json',
    '/mnt/c/Users/ondev/Projects/dev-os/out/vm-credentials.json',
]
PASSWORD = None
for path in CREDENTIALS:
    if os.path.isfile(path):
        PASSWORD = json.load(open(path))['dev']
        break
if not PASSWORD:
    raise SystemExit('no vm-credentials.json found')

client = api.connect('localhost::5900', timeout=30)
time.sleep(1.2)
client.captureScreen('/home/ondev/devos-vm/f-before.png')

client.keyPress('tab')                    # user field (prefilled) -> password
time.sleep(0.6)
client.captureScreen('/home/ondev/devos-vm/f-tabbed.png')

for character in PASSWORD:
    client.keyPress(character)
    time.sleep(0.22)
time.sleep(0.6)
client.captureScreen('/home/ondev/devos-vm/f-typed.png')

client.keyPress('return')
time.sleep(1.5)
print('LOGIN-SENT')
sys.stdout.flush()
os._exit(0)                               # vncdotool's disconnect can hang
