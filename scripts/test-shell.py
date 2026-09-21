#!/usr/bin/env python3
"""Render the Dev OS shell on a real X11 display and verify its pixels."""
import argparse
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
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
    raw = zlib.decompress(b''.join(rows))
    return width, height, raw


def count(width, height, raw, color):
    stride = width * 3 + 1
    return sum(1 for y in range(height) for x in range(width)
               if tuple(raw[y * stride + 1 + x * 3:y * stride + 1 + x * 3 + 3]) == color)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=PROJECT / 'out/shell-tests/result.json')
    args = parser.parse_args()
    if os.name != 'posix' or not os.environ.get('DISPLAY'):
        raise SystemExit('Run inside an X11 session such as WSLg (DISPLAY must be set)')
    checks = []
    with tempfile.TemporaryDirectory(prefix='devos-shell-test-') as temporary:
        root = Path(temporary) / 'root'
        subprocess.run([sys.executable, str(PROJECT / 'tools/dev.py'), '--root', str(root),
                        'install', str(PROJECT / 'out/desktop-counter-0.1.0-all.dpk')],
                       check=True, capture_output=True, text=True)
        prefix = PROJECT / 'out/shell-tests/devos-shell'
        completed = subprocess.run([sys.executable, str(PROJECT / 'tools/dev_shell.py'),
                                    '--root', str(root), '--dev', str(PROJECT / 'tools/dev.py'),
                                    '--screenshot-prefix', str(prefix)],
                                   capture_output=True, text=True, timeout=60)
        if completed.returncode != 0:
            raise SystemExit(completed.stdout + completed.stderr)
        result = json.loads(completed.stdout.strip().splitlines()[0])
        checks.append('shell rendered on a live X11 display: %dx%d' %
                      (result['screen'][0], result['screen'][1]))
        checks.append('menu lists the installed window app (%d application(s))' %
                      result['applications'])
        bar = png_pixels(Path(str(prefix) + '-bar.png'))
        menu = png_pixels(Path(str(prefix) + '-menu.png'))
        bar_bg, accent, text, panel, dim = ((20, 32, 52), (101, 224, 191), (229, 237, 248),
                                            (16, 27, 44), (143, 163, 191))
        assert bar[1] == 24, 'taskbar must be exactly 24 pixels high'
        checks.append('taskbar is 24px tall and spans the screen width (%dpx)' % bar[0])
        assert count(bar[0], bar[1], bar[2], bar_bg) > 1000, 'taskbar background missing'
        assert count(bar[0], bar[1], bar[2], accent) > 50, 'MENU button missing'
        assert count(bar[0], bar[1], bar[2], text) > 50, 'clock text missing'
        stride = bar[0] * 3 + 1
        right = sum(1 for y in range(bar[1]) for x in range(bar[0] - 220, bar[0])
                    if tuple(bar[2][y * stride + 1 + x * 3:y * stride + 1 + x * 3 + 3]) == text)
        assert right > 50, 'clock must be right-aligned'
        checks.append('MENU accent at the left, date-time text at the right')
        assert menu[0] == 320, 'menu popup width'
        assert count(menu[0], menu[1], menu[2], panel) > 1000, 'menu panel missing'
        for label, color in (('DEV OS header', accent), ('item and consent text', text),
                             ('category and permission detail', dim)):
            assert count(menu[0], menu[1], menu[2], color) > 50, label + ' missing'
            checks.append('menu renders the ' + label)
    report = {'passed': True, 'checks': checks,
              'screenshots': ['out/shell-tests/devos-shell-bar.png',
                              'out/shell-tests/devos-shell-menu.png'],
              'scope': 'Live X11 rendering on the test display; no in-guest ISO session'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
