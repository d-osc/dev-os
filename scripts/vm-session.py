#!/usr/bin/env python3
"""One serial session: log in as root and run every argument as a command."""
import socket
import sys
import time

PASSWORD = 'mSJlOJ51W6nbaiC83JRqybPv'


def main():
    commands = sys.argv[1:]
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect('/home/ondev/devos-vm/serial.sock')
    sock.settimeout(0.5)

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

    def expect(needle, seconds=20):
        collected = ''
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            collected += drain(0.4)
            if needle in collected:
                return collected
        raise SystemExit('missing %r; tail: %r' % (needle, collected[-200:]))

    sock.sendall(b'\n')
    time.sleep(1.2)
    opening = drain(1.5)
    if '~#' not in opening:                      # otherwise a shell survived
        sock.sendall(b'root\n')
        expect('Password:')
        time.sleep(0.3)
        sock.sendall(PASSWORD.encode() + b'\n')
        time.sleep(1.5)
        expect('~# ')
    for command in commands:
        sock.sendall(command.encode() + b'\n')
        time.sleep(0.5)
        print('$ ' + command)
        print(drain(8.0))
    sock.sendall(b'poweroff\n')
    time.sleep(3)


if __name__ == '__main__':
    main()
