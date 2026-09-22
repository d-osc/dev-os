#!/usr/bin/env python3
"""Drive the Dev OS VM over its serial socket: log in, run commands, print."""
import socket
import sys
import time

SOCKET = '/home/ondev/devos-vm/serial.sock'
USER, PASSWORD = 'root', 'mSJlOJ51W6nbaiC83JRqybPv'
PROMPT = '# '
MARK = '__XDONE__'


class Serial:
    def __init__(self, path):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.sock.settimeout(0.3)
        self.buffer = b''

    def read(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                chunk = self.sock.recv(4096)
                if chunk:
                    self.buffer += chunk
            except socket.timeout:
                continue
        out, self.buffer = self.buffer, b''
        return out.decode('utf-8', 'replace')

    def send(self, text):
        self.sock.sendall(text.encode())

    def expect(self, needle, seconds=25):
        end = time.monotonic() + seconds
        collected = ''
        while time.monotonic() < end:
            collected += self.read(0.3)
            if needle in collected:
                return collected
        raise SystemExit('did not see %r; tail: %s' % (needle, collected[-300:]))


def main():
    keep = '--keep' in sys.argv
    commands = [argument for argument in sys.argv[1:] if argument != '--keep']
    serial = Serial(SOCKET)
    serial.send('\n')
    time.sleep(1.0)
    opening = serial.read(2.0)
    if '~#' not in opening:               # otherwise a shell session survived
        serial.send(USER + '\n')
        serial.expect('Password:')
        serial.send(PASSWORD + '\n')
        time.sleep(1.5)
        serial.expect('~# ')
    serial.read(0.5)
    serial.send('stty -echo\n')
    time.sleep(0.5)
    serial.read(1.0)
    for command in commands:
        serial.send(command + '; echo ' + MARK + '$?\n')
        serial.expect(MARK)               # echo is off: first hit is the marker
        collected = serial.expect(MARK)   # second: command output + marker
        print('$ %s' % command)
        print(collected.replace(MARK, '').strip())
        print()
    if not keep:
        serial.send('poweroff\n')
        time.sleep(4)


if __name__ == '__main__':
    main()
