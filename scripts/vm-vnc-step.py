"""One VNC step against the running VM: capture before, type, capture after."""
import sys
import time

sys.path.insert(0, '/home/ondev/.local/lib/python3.12/site-packages')
from vncdotool import api

client = api.connect('localhost::5900', timeout=30)
time.sleep(1.0)
client.captureScreen('/home/ondev/devos-vm/vnc-before.png')
time.sleep(0.3)

action = sys.argv[1]
if action == 'tab':
    client.keyPress('tab')
elif action == 'char':
    client.keyPress(sys.argv[2])
elif action == 'return':
    client.keyPress('return')
elif action == 'password':
    for character in 'yl7VxD1M-oW5O4W0lCw5q0jO':
        client.keyPress(character)
        time.sleep(0.22)
time.sleep(0.6)
client.captureScreen('/home/ondev/devos-vm/vnc-after.png')
print('STEP-DONE')
