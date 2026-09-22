#!/usr/bin/env python3
"""Two extensions, one taskbar zone: prove they never paint over each other."""
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


def manifest(identifier, name):
    return {'id': identifier, 'name': name, 'version': '1.0.0',
            'description': 'overlap test', 'engine': 1, 'main': 'extension.py'}


# Widget A declares 80px but draws red across 160px on purpose; widget B
# (registered after A) fills its whole box with blue. If painting were not
# clipped, A's red would swallow B's box.
CODE_A = '''
def activate(api):
    def draw(painter):
        painter.rect(0, 3, 160, 34, "red", radius=4)
        painter.text("A", 6, 25, "text", 13, True)
    api.register_widget("left", 80, draw, widget_id="over-a")
'''

CODE_B = '''
def activate(api):
    def draw(painter):
        painter.rect(0, 3, painter.width - 4, 34, "blue", radius=4)
        painter.text("B", 6, 25, "text", 13, True)
    api.register_widget("left", 140, draw, widget_id="over-b")
'''


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
    parser.add_argument('--output', type=Path,
                        default=PROJECT / 'out/widget-overlap-tests/result.json')
    args = parser.parse_args()
    if os.name != 'posix' or not os.environ.get('DISPLAY'):
        raise SystemExit('Run inside an X11 session such as WSLg (DISPLAY must be set)')
    red = lambda p: p[0] > 190 and p[1] < 120 and p[2] < 120
    blue = lambda p: p[2] > 200 and p[1] < 190 and p[0] < 120
    checks = []
    with tempfile.TemporaryDirectory(prefix='devos-overlap-') as temporary:
        home = Path(temporary)
        extensions = home / 'extensions'
        for identifier, name, code in (('devos.over-a', 'A', CODE_A),
                                       ('devos.over-b', 'B', CODE_B)):
            directory = extensions / identifier
            directory.mkdir(parents=True)
            (directory / 'manifest.json').write_text(json.dumps(manifest(identifier, name)))
            (directory / 'extension.py').write_text(code)
        prefix = home / 'shell'
        completed = subprocess.run([sys.executable, str(PROJECT / 'tools/dev_shell.py'),
                                    '--extensions', str(extensions),
                                    '--screenshot-prefix', str(prefix)],
                                   capture_output=True, text=True, timeout=60)
        if completed.returncode != 0:
            raise SystemExit(completed.stdout + completed.stderr)
        result = json.loads(completed.stdout.strip().splitlines()[0])
        assert result['widgets'] == 2, result
        bar_w, bar_h, bar_raw = png_pixels(str(prefix) + '-bar.png')
        # A occupies [127, 207); B starts after the gap: [219, 359).
        assert count(bar_w, bar_h, bar_raw, red, 120, 215) > 30, 'widget A missing'
        assert count(bar_w, bar_h, bar_raw, red, 219, 365) == 0, \
            'widget A painted past its declared box into widget B'
        assert count(bar_w, bar_h, bar_raw, blue, 219, 365) > 40, 'widget B missing'
        assert count(bar_w, bar_h, bar_raw, blue, 120, 215) == 0, \
            'widget B painted over widget A'
        checks.append('two widgets share the left zone without overlap: A stays inside '
                      'its 80px box even though it tries to draw 160px, B renders intact '
                      '(%dx%d)' % (bar_w, bar_h))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.parent.joinpath('overlap-bar.png').write_bytes(
            Path(str(prefix) + '-bar.png').read_bytes())
    report = {'passed': True, 'checks': checks,
              'screenshots': ['out/widget-overlap-tests/overlap-bar.png'],
              'scope': 'Live widget clipping on the test X11 display; '
                       'no in-guest ISO session'}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
