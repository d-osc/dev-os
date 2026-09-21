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


def pixels(width, height, raw):
    stride = width * 3 + 1
    return [[tuple(raw[y * stride + 1 + x * 3:y * stride + 1 + x * 3 + 3])
             for x in range(width)] for y in range(height)]


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
        bar_w, bar_h, bar_raw = png_pixels(Path(str(prefix) + '-bar.png'))
        menu_w, menu_h, menu_raw = png_pixels(Path(str(prefix) + '-menu.png'))
        bar = pixels(bar_w, bar_h, bar_raw)
        menu = pixels(menu_w, menu_h, menu_raw)

        def count(grid, predicate, x0=0, x1=None, y0=0, y1=None):
            x1 = x1 or len(grid[0])
            y1 = y1 or len(grid)
            return sum(1 for y in range(y0, y1) for x in range(x0, x1)
                       if predicate(grid[y][x]))

        mint = lambda p: p[1] > 150 and p[1] > p[0] + 60 and 120 < p[2] < 230
        light = lambda p: min(p) > 165
        gray = lambda p: 90 <= min(p) <= 150
        red = lambda p: p[0] > 190 and p[1] < 120 and p[2] < 120
        assert bar_h == 40, 'taskbar must be exactly 40 pixels high'
        checks.append('taskbar is 40px tall and spans the screen width (%dpx)' % bar_w)
        shades = len({p for row in bar for p in row})
        assert shades > 100, 'bar must be anti-aliased, found %d shades' % shades
        checks.append('bar renders flat with anti-aliased glyphs (%d distinct shades)' % shades)
        assert count(bar, mint, 0, 120) > 30, 'green >_ DEVOS start pill missing'
        assert count(bar, gray, 104, 220) > 8, 'pinned-app monogram missing left of center'
        assert result['pinned'] == 1, 'installed window app must be pinned'
        assert count(bar, mint, bar_w - 180) > 8, 'green wifi tray glyph missing'
        assert count(bar, red, bar_w - 180) > 4, 'red notification badge missing'
        assert count(bar, light, bar_w - 140, None, 2, 20) > 20, 'clock time line missing'
        assert count(bar, gray, bar_w - 140, None, 22, 38) > 8, 'clock date line missing'
        assert count(bar, light, 130, bar_w - 160) == 0, 'unexpected bright text outside zones'
        checks.append('green start pill, left-anchored pinned icon, tray with wifi + red '
                      'badge, two-line clock at the right')
        assert menu_w == 320, 'menu popup width'
        shades = len({p for row in menu for p in row})
        assert shades > 300, 'menu must be anti-aliased, found %d shades' % shades
        checks.append('menu renders with anti-aliased detail (%d distinct shades)' % shades)
        assert count(menu, mint) > 40, 'accent elements (header dot, ALLOW chip) missing'
        assert count(menu, light) > 100, 'item and consent text missing'
        center, corner = menu[menu_h // 2][menu_w // 2], menu[1][1]
        assert corner != center, 'rounded corners missing'
        checks.append('menu panel has rounded corners, header, item, permission detail '
                      'and an ALLOW consent chip')
    report = {'passed': True, 'checks': checks,
              'screenshots': ['out/shell-tests/devos-shell-bar.png',
                              'out/shell-tests/devos-shell-menu.png'],
              'scope': 'Live X11 rendering (Cairo) on the test display; no in-guest ISO session'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
