#!/usr/bin/env python3
"""Narrator live probe: with the VM desktop up, move the pointer over the
taskbar via VNC while draining the serial console. A working narrator pops
a toast AND prints '[narrator] ...' to stdout, which reaches /dev/console
(the same ttyS0 the serial socket carries). Reports what actually arrived.
"""
import socket
import sys
import threading
import time

sys.path.insert(0, '/home/ondev/.local/lib/python3.12/site-packages')

SERIAL = '/home/ondev/devos-vm/serial.sock'
captured = []


def drain():
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(SERIAL)
    sock.settimeout(0.3)
    end = time.monotonic() + 30
    while time.monotonic() < end:
        try:
            chunk = sock.recv(4096)
            if chunk:
                captured.append(chunk.decode('utf-8', 'replace'))
        except socket.timeout:
            continue
    sock.close()


thread = threading.Thread(target=drain)
thread.start()
time.sleep(1.0)

from vncdotool import api
client = api.connect('localhost::5900', timeout=30)
time.sleep(0.8)
client.captureScreen('/home/ondev/devos-vm/probe-before.png')
client.mouseMove(30, 780)              # menu pill, bottom bar
time.sleep(1.5)
client.captureScreen('/home/ondev/devos-vm/probe-hover.png')
client.mouseMove(640, 780)             # sweep along the bar
time.sleep(0.6)
client.mouseMove(30, 780)
time.sleep(1.0)
client.disconnect()
thread.join()

text = ''.join(captured)
open('/home/ondev/devos-vm/probe-serial.txt', 'w').write(text)
print('narrator-prints:', text.count('[narrator]'))
for line in text.splitlines():
    if '[narrator]' in line:
        print('  ' + line.strip()[:120])
