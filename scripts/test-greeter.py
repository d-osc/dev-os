#!/usr/bin/env python3
"""Render the greeter login screen live and verify its pixels."""
import argparse
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import zlib

PROJECT = Path(__file__).resolve().parents[1]


def png_pixels(path):
    data = Path(path).read_bytes()
    pos, rows, width, height = 8, [], 0, 0
    while pos < len(data):
        length = struct.unpack('>I', data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        if tag == b'IHDR':
            width, height = struct.unpack('>II', data[pos + 8:pos + 16])
        elif tag == b'IDAT':
            rows.append(data[pos + 8:pos + 8 + length])
        pos += 12 + length
    return width, height, zlib.decompress(b''.join(rows))


def count(width, height, raw, predicate, x0=0, y0=0, x1=None, y1=None):
    x1, y1 = x1 or width, y1 or height
    stride = width * 3 + 1
    return sum(1 for y in range(y0, y1) for x in range(x0, x1)
               if predicate(tuple(raw[y * stride + 1 + x * 3:y * stride + 1 + x * 3 + 3])))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
                        default=PROJECT / 'out/greeter-tests/result.json')
    args = parser.parse_args()
    if os.name != 'posix' or not os.environ.get('DISPLAY'):
        raise SystemExit('Run inside an X11 session such as WSLg (DISPLAY must be set)')
    checks = []
    with tempfile.TemporaryDirectory(prefix='devos-greeter-test-') as temporary:
        shot = Path(temporary) / 'greeter.png'
        completed = subprocess.run(
            [sys.executable, str(PROJECT / 'tools/dev_greeter.py'),
             '--screenshot', str(shot)],
            capture_output=True, text=True, timeout=60)
        if completed.returncode != 0:
            raise SystemExit(completed.stdout + completed.stderr)
        result = json.loads(completed.stdout.strip().splitlines()[0])
        assert result['users'], 'no login-capable users were listed: %s' % result
        width, height, raw = png_pixels(shot)
        mint = lambda p: p[1] > 150 and p[1] > p[0] + 60 and 120 < p[2] < 230
        light = lambda p: min(p) > 165
        assert count(width, height, raw, mint) > 20, 'green >_ mark missing'
        assert count(width, height, raw, light) > 60, 'DEV OS title or fields missing'
        center = height // 2
        assert count(width, height, raw, mint, 0, 0, width, 40) < 5, \
            'accent should live on the card, not the top edge'
        checks.append('login card rendered live: >_ mark, DEV OS title, user and '
                      'password fields, Log in button (%dx%d, users: %s)'
                      % (width, height, ', '.join(result['users'][:3])))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.parent.joinpath('greeter.png').write_bytes(shot.read_bytes())

    report = {'passed': True, 'checks': checks,
              'screenshots': ['out/greeter-tests/greeter.png'],
              'scope': 'Live greeter rendering on the test X11 display; '
                       'no in-guest ISO session'}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
