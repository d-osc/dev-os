import socket
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


print('start:', drain(2.0)[-80:])
s.sendall(b'\n')
print('enter:', drain(2.0)[-120:])
s.sendall(b'root\n')
print('user:', drain(2.0)[-120:])
s.sendall(b'mSJlOJ51W6nbaiC83JRqybPv\n')
print('pass:', drain(3.0)[-200:])
s.sendall(b'echo MARK; id\n')
time.sleep(1.0)
print('cmd:', drain(3.0)[-300:])
