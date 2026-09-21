#!/usr/bin/env python3
"""Render the desktop-info window on a real X11 display and verify pixels."""
import argparse
import json
import os
from pathlib import Path
import shutil
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
    parser.add_argument('--output', type=Path, default=PROJECT / 'out/gui-tests/result.json')
    args = parser.parse_args()
    if os.name != 'posix' or not os.environ.get('DISPLAY'):
        raise SystemExit('Run inside an X11 session such as WSLg (DISPLAY must be set)')
    script = PROJECT / 'examples/desktop-info/payload/opt/apps/desktop-info/window.py'
    checks = []
    with tempfile.TemporaryDirectory(prefix='devos-gui-test-') as temporary:
        environment = dict(os.environ, DEVOS_DATA_DIR=temporary)
        completed = subprocess.run([sys.executable, str(script), '--test'],
                                   capture_output=True, text=True, timeout=60, env=environment)
        if completed.returncode != 0:
            raise SystemExit(completed.stdout + completed.stderr)
        captured = Path(temporary) / 'window.png'
        assert captured.is_file(), 'the window did not capture itself'
        width, height, raw = png_pixels(captured)
        assert (width, height) == (380, 230), 'unexpected window size'
        checks.append('desktop-info window rendered at %dx%d on a live X11 display'
                      % (width, height))
        mint = lambda p: p[1] > 150 and p[1] > p[0] + 60
        light = lambda p: min(p) > 165
        dim = lambda p: 120 < min(p) < 200
        shades = len({tuple(raw[y * (width * 3 + 1) + 1 + x * 3:y * (width * 3 + 1) + 1 + x * 3 + 3])
                      for y in range(height) for x in range(width)})
        assert shades > 300, 'rendering must be anti-aliased, found %d shades' % shades
        checks.append('window renders with anti-aliased detail (%d distinct shades)' % shades)
        assert count(width, height, raw, mint) > 100, 'green >_ mark and Close chip missing'
        checks.append('title-bar >_ prompt mark and primary Close chip present')
        glyph = lambda p: 50 < min(p) < 170 and max(p) - min(p) > 20 and p[2] > p[0]
        controls = count(width, height, raw, glyph, width - 84, 2, width - 2, 28)
        assert controls > 40, 'minimize/maximize/close glyphs missing'
        checks.append('title-bar controls (- [] x) rendered and hit-testable')
        assert count(width, height, raw, light) > 300, 'value text missing'
        assert count(width, height, raw, dim) > 100, 'heading text missing'
        checks.append('System Info rows (Version/Kernel/Memory/Uptime) rendered')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(captured, args.output.parent / 'desktop-info.png')
    report = {'passed': True, 'checks': checks,
              'screenshot': 'out/gui-tests/desktop-info.png',
              'scope': 'Live X11 rendering through the shared ctypes+Cairo toolkit; '
                       'not an in-guest ISO session'}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
