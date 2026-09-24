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


def run(cmd, wait=1.5, collect=3.5):
    s.sendall(cmd.encode() + b'\n')
    time.sleep(wait)
    return drain(collect)


for _ in range(3):
    s.sendall(b'\x03')
    time.sleep(0.3)
drain(0.8)
run('\n', 0.8, 1.2)
run('root', 1.0, 1.0)
run('mSJlOJ51W6nbaiC83JRqybPv', 1.5, 1.2)
run('stty -echo', 0.5, 0.6)
print(run('ps w | grep -vE "grep|\\[" | tail -6', 1.5, 3.5)[:400])
print(run('tail -8 /tmp/g.log 2>&1', 1.5, 3.0)[:400])
