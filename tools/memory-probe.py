#!/usr/bin/env python3
"""Bounded VM probe: touch 50% of available memory, hold briefly, then release."""
import sys
import time

available = None
with open('/proc/meminfo') as f:
    for line in f:
        if line.startswith('MemAvailable:'):
            available = int(line.split()[1]) * 1024
if available is None:
    raise SystemExit('MemAvailable is unavailable')
size = available // 2
payload = bytearray(size)
for offset in range(0, size, 4096):
    payload[offset] = 1
print(f'READY allocated_bytes={size}', flush=True)
time.sleep(min(30, max(1, int(sys.argv[1]) if len(sys.argv) > 1 else 12)))
print('DONE', flush=True)
