#!/usr/bin/env python3
"""Prove full GUI customization by extensions on the live shell."""
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
MANIFEST = {'id': 'devos.gui-proof', 'name': 'Gui Proof', 'version': '1.0.0',
            'description': 'Full-customization live test', 'engine': 1,
            'main': 'extension.py'}
CODE = '''
import os
from pathlib import Path

def draw_widget(painter):
    painter.rect(0, 3, painter.width - 4, 34, "blue", radius=4)
    painter.text("WIDGET", 6, 24, "text", 11, True)

def draw_override(painter):
    painter.text("OVERRIDE", 4, 25, "red", 13, True)

def draw_panel(painter):
    painter.rect(0, 0, painter.width, painter.height, "chrome")
    painter.rect(10, 10, painter.width - 20, painter.height - 20, "accent", radius=6)

def activate(api):
    Path(os.environ["DEVOS_EXT_PROOF"]).write_text("activated")
    api.register_widget("left", 78, draw_widget)
    api.override_clock(120, draw_override)
    api.hide("tray")
    panel = api.create_panel("devos.gui-proof.panel", 240, 120, draw_panel, x=8)
    panel.show()
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
                        default=PROJECT / 'out/gui-extension-tests/result.json')
    args = parser.parse_args()
    if os.name != 'posix' or not os.environ.get('DISPLAY'):
        raise SystemExit('Run inside an X11 session such as WSLg (DISPLAY must be set)')
    blue = lambda p: p[2] > 200 and p[1] < 190 and p[0] < 120
    red = lambda p: p[0] > 190 and p[1] < 120 and p[2] < 120
    green = lambda p: p[1] > 200 and p[0] < 100 and p[2] < 180
    mint = lambda p: p[1] > 150 and p[1] > p[0] + 60
    checks = []
    with tempfile.TemporaryDirectory(prefix='devos-guiext-test-') as temporary:
        home = Path(temporary)
        proof = home / 'proof.txt'
        extension = home / 'extensions' / 'proof'
        extension.mkdir(parents=True)
        (extension / 'manifest.json').write_text(json.dumps(MANIFEST))
        (extension / 'extension.py').write_text(CODE)
        prefix = home / 'shell'
        environment = dict(os.environ, DEVOS_EXT_PROOF=str(proof))
        completed = subprocess.run([sys.executable, str(PROJECT / 'tools/dev_shell.py'),
                                    '--extensions', str(home / 'extensions'),
                                    '--screenshot-prefix', str(prefix)],
                                   capture_output=True, text=True, timeout=60, env=environment)
        if completed.returncode != 0:
            raise SystemExit(completed.stdout + completed.stderr)
        result = json.loads(completed.stdout.strip().splitlines()[0])
        assert result['widgets'] == 1 and result['panels'] == 1, result
        assert proof.read_text() == 'activated', 'activate() never ran'
        bar_w, bar_h, bar_raw = png_pixels(str(prefix) + '-bar.png')
        assert count(bar_w, bar_h, bar_raw, blue, 100, 260) > 40, 'custom widget missing'
        assert count(bar_w, bar_h, bar_raw, red, bar_w - 150) > 10, 'clock override missing'
        assert count(bar_w, bar_h, bar_raw, green, bar_w - 180) == 0, \
            'hide("tray") left the stock glyphs behind'
        panel_path = Path(str(prefix) + '-panel.png')
        assert panel_path.is_file(), 'panel was not captured'
        panel_w, panel_h, panel_raw = png_pixels(panel_path)
        assert count(panel_w, panel_h, panel_raw, mint) > 200, 'panel painting missing'
        checks.append('extension rebuilt the GUI: custom taskbar widget (blue), clock '
                      'override (red), stock tray hidden, and a floating panel painted '
                      'by the extension (%dx%d bar, %dx%d panel)'
                      % (bar_w, bar_h, panel_w, panel_h))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.parent.joinpath('gui-extension-bar.png').write_bytes(
            Path(str(prefix) + '-bar.png').read_bytes())
        args.output.parent.joinpath('gui-extension-panel.png').write_bytes(
            panel_path.read_bytes())
    report = {'passed': True, 'checks': checks,
              'screenshots': ['out/gui-extension-tests/gui-extension-bar.png',
                              'out/gui-extension-tests/gui-extension-panel.png'],
              'scope': 'Live extension GUI customization on the test X11 display; '
                       'no in-guest ISO session'}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
