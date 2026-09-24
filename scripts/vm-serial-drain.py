#!/usr/bin/env python3
"""Hold the VM serial socket open and log everything to a file."""
import socket
import sys
import time

sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect('/home/ondev/devos-vm/serial.sock')
sock.settimeout(0.5)
end = time.monotonic() + float(sys.argv[2] if len(sys.argv) > 2 else 120)
out = open(sys.argv[1], 'wb')
while time.monotonic() < end:
    try:
        chunk = sock.recv(4096)
        if chunk:
            out.write(chunk)
            out.flush()
    except socket.timeout:
        continue
out.close()
