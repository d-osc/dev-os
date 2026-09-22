#!/usr/bin/env python3
"""Prove a greeter extension repaints the login screen live."""
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
MANIFEST = {'id': 'devos.greeter-proof', 'name': 'Proof', 'version': '1.0.0',
            'engine': 1, 'main': 'extension.py'}
CODE = '''
def activate(api):
    api.set_subtitle("Welcome aboard")

    def background(painter):
        painter.rect(0, 0, 260, 220, "blue")
        painter.rect(painter.width - 260, painter.height - 220, 260, 220, "red")

    def card(painter):
        painter.rect(0, 0, painter.width, painter.height, "chrome", radius=2)
        painter.rect(0, painter.height - 6, painter.width, 6, "accent")

    api.paint_background(background)
    api.paint_card(card)
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


def pixel(raw, width, x, y):
    stride = width * 3 + 1
    return tuple(raw[y * stride + 1 + x * 3:y * stride + 1 + x * 3 + 3])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
                        default=PROJECT / 'out/greeter-tests/extensions-result.json')
    args = parser.parse_args()
    if os.name != 'posix' or not os.environ.get('DISPLAY'):
        raise SystemExit('Run inside an X11 session such as WSLg (DISPLAY must be set)')
    blue = lambda p: p[2] > 200 and p[1] < 190 and p[0] < 120
    red = lambda p: p[0] > 190 and p[1] < 120 and p[2] < 120
    mint = lambda p: p[1] > 150 and p[1] > p[0] + 60 and 120 < p[2] < 230
    checks = []
    with tempfile.TemporaryDirectory(prefix='devos-greeterext-') as temporary:
        home = Path(temporary)
        extension = home / 'extensions' / 'proof'
        extension.mkdir(parents=True)
        (extension / 'manifest.json').write_text(json.dumps(MANIFEST))
        (extension / 'extension.py').write_text(CODE)
        shot = home / 'greeter.png'
        completed = subprocess.run(
            [sys.executable, str(PROJECT / 'tools/dev_greeter.py'),
             '--greeter-extensions', str(home / 'extensions'),
             '--screenshot', str(shot)],
            capture_output=True, text=True, timeout=60)
        if completed.returncode != 0:
            raise SystemExit(completed.stdout + completed.stderr)
        result = json.loads(completed.stdout.strip().splitlines()[0])
        assert result['greeter_extensions'] == ['devos.greeter-proof'], result
        width, height, raw = png_pixels(shot)
        assert blue(pixel(raw, width, 80, 80)), 'background hook missing (top-left)'
        assert red(pixel(raw, width, width - 80, height - 80)), \
            'background hook missing (bottom-right)'
        card_x, card_y = (width - 380) // 2, (height - 344) // 2
        accent = sum(1 for x in range(card_x + 100, card_x + 280)
                     if mint(pixel(raw, width, x, card_y + 343)))
        assert accent > 60, 'card hook missing (accent strip under the card)'
        center = pixel(raw, width, width // 2, card_y + 230)
        assert center[0] < 60 and min(center) < 90, \
            'card surface should be the extension chrome, not stock'
        checks.append('greeter extension repainted the login screen: corners show the '
                      'custom background, the card carries the extension surface and '
                      'accent strip, stock fields stay on top (%dx%d)' % (width, height))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.parent.joinpath('extensions-greeter.png').write_bytes(
            shot.read_bytes())
    report = {'passed': True, 'checks': checks,
              'screenshots': ['out/greeter-tests/extensions-greeter.png'],
              'scope': 'Live greeter extension rendering on the test X11 display; '
                       'no in-guest ISO session'}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
