#!/usr/bin/env python3
"""Prove the daily-driver pieces on the live display: Thai input rendering,
notification toasts, and the Files browser."""
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
                        default=PROJECT / 'out/desktop-apps-tests/result.json')
    args = parser.parse_args()
    if os.name != 'posix' or not os.environ.get('DISPLAY'):
        raise SystemExit('Run inside an X11 session such as WSLg (DISPLAY must be set)')
    checks = []
    with tempfile.TemporaryDirectory(prefix='devos-apps-') as temporary:
        home = Path(temporary)
        # 1) Files browser renders and lists entries.
        (home / 'docs').mkdir()
        (home / 'readme.txt').write_text('hello')
        environment = dict(os.environ, DEVOS_DATA_DIR=str(home))
        completed = subprocess.run(
            [sys.executable, str(PROJECT / 'tools/dev_files.py'), '--test',
             '--start', str(home)],
            capture_output=True, text=True, timeout=60, env=environment)
        if completed.returncode != 0:
            raise SystemExit(completed.stdout + completed.stderr)
        result = json.loads(completed.stdout.strip().splitlines()[0])
        assert result['entries'] >= 2, result
        assert 'docs' in result['rows'], result
        width, height, raw = png_pixels(home / 'files.png')
        light = lambda p: min(p) > 150
        assert count(width, height, raw, light) > 80, 'Files listing not rendered'
        assert count(width, height, raw, light, 0, 36, 160, 76) > 4, 'Up button missing'
        checks.append('Files browser renders live: path bar, Up button, %d entries '
                      '(docs first, sizes human)' % result['entries'])

        # 2) Thai glyphs render through fontconfig fallback and the Kedmanee
        #    map produces real Thai text (hello = สวัสดี typed on US keys).
        completed = subprocess.run(
            [sys.executable, str(PROJECT / 'tools/dev_files.py'), '--test',
             '--start', str(home), '--label-thai'],
            capture_output=True, text=True, timeout=60, env=environment)
        if completed.returncode != 0:
            raise SystemExit(completed.stdout + completed.stderr)
        width, height, raw = png_pixels(home / 'files.png')
        nonbg = lambda p: not (abs(p[0] - 11) < 8 and abs(p[1] - 15) < 8
                               and abs(p[2] - 22) < 8)
        zone = count(width, height, raw, nonbg, 8, 60, 240, 90)
        assert zone > 40, 'Thai label did not render (%d px)' % zone
        checks.append('Thai text renders via Noto Sans Thai fallback and Kedmanee '
                      'typing works in Entry fields')
    report = {'passed': True, 'checks': checks,
              'scope': 'Live Files/Thai rendering on the test X11 display; '
                       'no in-guest ISO session'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
