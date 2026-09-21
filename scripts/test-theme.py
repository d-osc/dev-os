#!/usr/bin/env python3
"""Switch the desktop to a JSON theme and verify the pixels really change."""
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
AMBER = {'name': 'Theme Test Amber', 'colors': {'accent': '#FFB000',
                                                'accentText': '#201600'}}


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
    parser.add_argument('--output', type=Path, default=PROJECT / 'out/theme-tests/result.json')
    args = parser.parse_args()
    if os.name != 'posix' or not os.environ.get('DISPLAY'):
        raise SystemExit('Run inside an X11 session such as WSLg (DISPLAY must be set)')
    amber = lambda p: p[0] > 200 and p[1] > 120 and p[2] < 90
    green = lambda p: p[1] > 200 and p[0] < 100 and p[2] < 180
    checks = []
    with tempfile.TemporaryDirectory(prefix='devos-theme-test-') as temporary:
        home = Path(temporary)
        theme_file = home / 'amber.json'
        theme_file.write_text(json.dumps(AMBER))
        prefix = home / 'shell'
        completed = subprocess.run([sys.executable, str(PROJECT / 'tools/dev_shell.py'),
                                    '--theme', str(theme_file),
                                    '--screenshot-prefix', str(prefix)],
                                   capture_output=True, text=True, timeout=60)
        if completed.returncode != 0:
            raise SystemExit(completed.stdout + completed.stderr)
        bar_w, bar_h, bar_raw = png_pixels(str(prefix) + '-bar.png')
        start = count(bar_w, bar_h, bar_raw, amber, 0, 0, 140)
        assert start > 30, 'amber start button missing (%d px)' % start
        assert count(bar_w, bar_h, bar_raw, green, 0, 0, 140) == 0, 'old accent still visible'
        assert count(bar_w, bar_h, bar_raw, amber, bar_w - 180) > 8, 'amber wifi glyph missing'
        checks.append('taskbar restyled: start button and tray accent are amber, '
                      'no green remains (%dx%d)' % (bar_w, bar_h))

        environment = dict(os.environ, DEVOS_DATA_DIR=str(home), DEVOS_THEME=str(theme_file))
        script = PROJECT / 'examples/desktop-info/payload/opt/apps/desktop-info/window.py'
        completed = subprocess.run([sys.executable, str(script), '--test'],
                                   capture_output=True, text=True, timeout=60, env=environment)
        if completed.returncode != 0:
            raise SystemExit(completed.stdout + completed.stderr)
        win_w, win_h, win_raw = png_pixels(home / 'window.png')
        assert count(win_w, win_h, win_raw, amber) > 100, 'amber Close chip / >_ mark missing'
        assert count(win_w, win_h, win_raw, green) == 0, 'old accent still visible in the window'
        checks.append('window app inherits the theme via DEVOS_THEME: primary button and '
                      'title mark are amber')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.parent.joinpath('amber-bar.png').write_bytes(
            Path(str(prefix) + '-bar.png').read_bytes())
        args.output.parent.joinpath('amber-window.png').write_bytes(
            (home / 'window.png').read_bytes())
    report = {'passed': True, 'checks': checks, 'theme': AMBER,
              'screenshots': ['out/theme-tests/amber-bar.png', 'out/theme-tests/amber-window.png'],
              'scope': 'Live theme switching on the test X11 display; no in-guest ISO session'}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
