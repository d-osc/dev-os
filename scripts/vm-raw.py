import socket
import sys
import time

s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect('/home/ondev/devos-vm/serial.sock')
s.settimeout(1.0)


def drain(seconds):
    end = time.monotonic() + seconds
    data = b''
    while time.monotonic() < end:
        try:
            chunk = s.recv(4096)
            if not chunk:
                return data + b'<EOF>'
            data += chunk
        except socket.timeout:
            pass
    return data


command = ' '.join(sys.argv[1:])
s.sendall(('\n' + command + '\n').encode())
time.sleep(1.5)
print(drain(3.0).decode('utf-8', 'replace'))
