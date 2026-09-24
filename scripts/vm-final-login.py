"""Guest-side auth check (script file, no quoting), then the GUI login."""
import base64
import socket
import sys
import time

sys.path.insert(0, '/home/ondev/.local/lib/python3.12/site-packages')
from vncdotool import api

PASSWORD = 'yl7VxD1M-oW5O4W0lCw5q0jO'

AUTH_CHECK = '''
import ctypes
shadow = {}
for line in open('/etc/shadow'):
    fields = line.split(':')
    if fields[0] == 'dev':
        shadow['hash'] = fields[1]
lib = ctypes.CDLL('libcrypt.so.1')
lib.crypt.restype = ctypes.c_char_p
lib.crypt.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
password = %r
hash_value = shadow['hash'].encode()
result = lib.crypt(password, hash_value)
print('AUTH-MATCH' if result == hash_value else 'AUTH-MISMATCH')
print('HASH-PREFIX', shadow['hash'][:12])
''' % PASSWORD.encode()

serial = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
serial.connect('/home/ondev/devos-vm/serial.sock')
serial.settimeout(0.3)


def drain(t):
    end = time.monotonic() + t
    data = b''
    while time.monotonic() < end:
        try:
            chunk = serial.recv(4096)
            if chunk:
                data += chunk
        except socket.timeout:
            pass
    return data.decode('utf-8', 'replace')


def run(cmd, wait=1.5, collect=3.5):
    serial.sendall(cmd.encode() + b'\n')
    time.sleep(wait)
    return drain(collect)


for _ in range(3):
    serial.sendall(b'\x03')
    time.sleep(0.3)
drain(0.8)
run('root', 1.0, 1.2)
run('mSJlOJ51W6nbaiC83JRqybPv', 1.5, 1.2)
run('stty -echo', 0.5, 0.6)

encoded = base64.b64encode(AUTH_CHECK.encode()).decode()
run("echo %s | base64 -d > /tmp/authcheck.py" % encoded, 1.0, 2.0)
print(run('python3 /tmp/authcheck.py', 3.0, 4.0)[:200])

# Also watch the greeter: run a copy with stderr kept, then kill the
# inittab one so the visible greeter is ours.
run('pkill -f dev-greeter; sleep 1', 1.5, 2.0)
run('DISPLAY=:0 XAUTHORITY=/root/.Xauthority nohup /usr/bin/python3 /usr/bin/dev-greeter > /tmp/g.log 2>&1 & echo BG-STARTED', 2.0, 3.0)
print(run('sleep 3; pidof python3', 1.5, 3.0)[:120])
serial.close()
time.sleep(1.0)

client = api.connect('localhost::5900', timeout=30)
time.sleep(1.5)
client.captureScreen('/home/ondev/devos-vm/g-before.png')
client.keyPress('tab')
time.sleep(0.7)
client.captureScreen('/home/ondev/devos-vm/g-tabbed.png')
for character in PASSWORD:
    client.keyPress(character)
    time.sleep(0.22)
time.sleep(0.7)
client.captureScreen('/home/ondev/devos-vm/g-typed.png')
client.keyPress('return')
time.sleep(3.0)
client.captureScreen('/home/ondev/devos-vm/g-after.png')
print('VNC-LOGIN-SENT')

serial2 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
serial2.connect('/home/ondev/devos-vm/serial.sock')
serial2.settimeout(0.3)
serial2.sendall(b'\n')
time.sleep(1.2)
serial2.settimeout(0.3)


def drain2(t):
    end = time.monotonic() + t
    data = b''
    while time.monotonic() < end:
        try:
            chunk = serial2.recv(4096)
            if chunk:
                data += chunk
        except socket.timeout:
            pass
    return data.decode('utf-8', 'replace')


drain2(1.0)


def run2(cmd, wait=1.5, collect=3.5):
    serial2.sendall(cmd.encode() + b'\n')
    time.sleep(wait)
    return drain2(collect)


print('G-LOG:', run2('tail -6 /tmp/g.log', 1.5, 3.5)[:400])
print('PS:', run2('ps w | grep -vE "grep|\\[" | tail -6', 1.5, 3.5)[:400])
