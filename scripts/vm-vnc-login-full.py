"""Full GUI login: Tab into the password field, type it, press Return."""
import sys
import time

sys.path.insert(0, '/home/ondev/.local/lib/python3.12/site-packages')
from vncdotool import api

client = api.connect('localhost::5900', timeout=30)
time.sleep(1.2)
client.captureScreen('/home/ondev/devos-vm/f-before.png')

client.keyPress('tab')                    # user field (prefilled) -> password
time.sleep(0.6)
client.captureScreen('/home/ondev/devos-vm/f-tabbed.png')

for character in 'yl7VxD1M-oW5O4W0lCw5q0jO':
    client.keyPress(character)
    time.sleep(0.22)
time.sleep(0.6)
client.captureScreen('/home/ondev/devos-vm/f-typed.png')

client.keyPress('return')
time.sleep(1.5)
print('LOGIN-SENT')
