"""Controlled VNC input test: two baseline captures, type, capture, compare."""
import sys
import time

sys.path.insert(0, '/home/ondev/.local/lib/python3.12/site-packages')
from vncdotool import api

client = api.connect('localhost::5900', timeout=30)
time.sleep(1.2)
client.captureScreen('/home/ondev/devos-vm/c1.png')
time.sleep(0.8)
client.captureScreen('/home/ondev/devos-vm/c2.png')     # control: no input
time.sleep(0.5)
client.keyPress('k')
time.sleep(0.8)
client.captureScreen('/home/ondev/devos-vm/c3.png')
print('DONE')
