import socket
import time

s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect('/home/ondev/devos-vm/serial.sock')
s.settimeout(0.3)


def drain(t):
    end = time.monotonic() + t
    d = b''
    while time.monotonic() < end:
        try:
            c = s.recv(4096)
            if c:
                d += c
        except socket.timeout:
            pass
    return d.decode('utf-8', 'replace')


def run(cmd, wait=2.0, collect=4.0):
    s.sendall(cmd.encode() + b'\n')
    time.sleep(wait)
    return drain(collect)


for _ in range(3):
    s.sendall(b'\x03')
    time.sleep(0.3)
drain(0.8)
hash_line = run('grep ^dev: /etc/shadow', 1.5, 3.0)
hash_value = [line for line in hash_line.splitlines() if line.startswith('dev:')][0].split(':')[1]
print('HASH-LEN:', len(hash_value))

# Ask the guest's own libcrypt whether our password matches that exact hash.
command = ("python3 -c \"import ctypes; l=ctypes.CDLL('libcrypt.so.1'); "
           "l.crypt.restype=ctypes.c_char_p; "
           "l.crypt.argtypes=[ctypes.c_char_p, ctypes.c_char_p]; "
           "r=l.crypt(b'yl7VxD1M-oW5O4W0lCw5q0jO', %r); "
           "print('MATCH' if r == %r else 'MISMATCH')\""
           % (hash_value.encode(), hash_value.encode()))
print(run(command, 3.0, 4.0)[:200])
