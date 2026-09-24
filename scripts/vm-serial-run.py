"""Run commands over the VM serial socket; print everything collected."""
import socket
import sys
import time

sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect('/home/ondev/devos-vm/serial.sock')
sock.settimeout(0.4)


def drain(seconds):
    end = time.monotonic() + seconds
    data = b''
    while time.monotonic() < end:
        try:
            chunk = sock.recv(4096)
            if chunk:
                data += chunk
        except socket.timeout:
            continue
    return data.decode('utf-8', 'replace')


def send(text, wait=1.2, collect=3.0):
    sock.sendall(text.encode() + b'\n')
    time.sleep(wait)
    return drain(collect)


print(send('\n', 0.8, 1.5))
print(send('root', 0.8, 1.0))
print(send('mSJlOJ51W6nbaiC83JRqybPv', 1.5, 1.5))
print(send('stty -echo; ps w | grep -vE "grep|\\[" | tail -5', 1.0, 3.0))
for command in sys.argv[1:]:
    print('$', command)
    print(send(command, 1.5, 4.0))
