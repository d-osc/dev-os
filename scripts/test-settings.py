#!/usr/bin/env python3
"""Drive the desktop from a settings.json and verify it on real pixels."""
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
NIGHTFALL = {'name': 'Settings Nightfall',
             'colors': {'accent': '#7C4DFF', 'accentText': '#120B24'}}


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


def count(width, height, raw, predicate, x0=0, x1=None):
    x1 = x1 or width
    stride = width * 3 + 1
    return sum(1 for y in range(height) for x in range(x0, x1)
               if predicate(tuple(raw[y * stride + 1 + x * 3:y * stride + 1 + x * 3 + 3])))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=PROJECT / 'out/settings-tests/result.json')
    args = parser.parse_args()
    if os.name != 'posix' or not os.environ.get('DISPLAY'):
        raise SystemExit('Run inside an X11 session such as WSLg (DISPLAY must be set)')
    violet = lambda p: 100 < p[0] < 170 and p[1] < 130 and p[2] > 200
    green = lambda p: p[1] > 200 and p[0] < 100 and p[2] < 180
    checks = []
    with tempfile.TemporaryDirectory(prefix='devos-settings-test-') as temporary:
        home = Path(temporary)
        (home / 'themes').mkdir()
        (home / 'themes' / 'nightfall.json').write_text(json.dumps(NIGHTFALL))
        settings = home / 'settings.json'
        settings.write_text(json.dumps({'theme': 'nightfall',
                                        'clock.showSeconds': False,
                                        'clock.dateFormat': '%Y-%m-%d'}))
        prefix = home / 'shell'
        completed = subprocess.run([sys.executable, str(PROJECT / 'tools/dev_shell.py'),
                                    '--settings', str(settings),
                                    '--screenshot-prefix', str(prefix)],
                                   capture_output=True, text=True, timeout=60)
        if completed.returncode != 0:
            raise SystemExit(completed.stdout + completed.stderr)
        result = json.loads(completed.stdout.strip().splitlines()[0])
        assert result['theme'] == 'Settings Nightfall', \
            'settings theme not applied: %s' % result['theme']
        bar_w, bar_h, bar_raw = png_pixels(str(prefix) + '-bar.png')
        assert count(bar_w, bar_h, bar_raw, violet, 0, 140) > 30, \
            'nightfall start button missing'
        assert count(bar_w, bar_h, bar_raw, green, 0, 140) == 0, 'old accent still visible'
        checks.append("settings.json picks the theme by name: 'nightfall' resolves beside "
                      'the settings file and restyles the taskbar (%dx%d)' % (bar_w, bar_h))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.parent.joinpath('nightfall-bar.png').write_bytes(
            Path(str(prefix) + '-bar.png').read_bytes())
    report = {'passed': True, 'checks': checks,
              'screenshots': ['out/settings-tests/nightfall-bar.png'],
              'scope': 'Live settings.json handling on the test X11 display; '
                       'no in-guest ISO session'}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
