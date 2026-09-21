#!/usr/bin/env python3
"""Load an extension into the live shell and verify it contributed."""
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
MANIFEST = {'id': 'devos.proof', 'name': 'Proof', 'version': '1.0.0',
            'description': 'Live test extension', 'engine': 1, 'main': 'extension.py'}
CODE = '''
import os
from pathlib import Path

SQUARE = {"view": [16, 16], "elements": [
    {"kind": "rect", "x": 3, "y": 3, "w": 10, "h": 10, "r": 2, "fill": True}
]}

def activate(api):
    Path(os.environ["DEVOS_EXT_PROOF"]).write_text("activated")
    api.register_tray("proof", SQUARE, command_id="devos.proof.run", color="blue")
    api.register_command("devos.proof.run", "Run proof",
                         lambda: Path(os.environ["DEVOS_EXT_PROOF"]).write_text("ran"),
                         "Live test command")
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
                        default=PROJECT / 'out/extensions-tests/result.json')
    args = parser.parse_args()
    if os.name != 'posix' or not os.environ.get('DISPLAY'):
        raise SystemExit('Run inside an X11 session such as WSLg (DISPLAY must be set)')
    blue = lambda p: p[2] > 200 and p[1] < 190 and p[0] < 120
    checks = []
    with tempfile.TemporaryDirectory(prefix='devos-ext-test-') as temporary:
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
        assert result['extensions'] == ['devos.proof'], \
            'extension did not load: %s' % result
        assert result['commands'] == 1, 'command not registered: %s' % result
        assert proof.read_text() == 'activated', 'activate() never ran'
        bar_w, bar_h, bar_raw = png_pixels(str(prefix) + '-bar.png')
        assert count(bar_w, bar_h, bar_raw, blue, bar_w - 210, bar_w - 110) > 8, \
            'extension tray icon missing'
        checks.append('extension loaded beside the live shell: activate() ran, its command '
                      'is in the menu and its blue tray icon renders (%dx%d)' % (bar_w, bar_h))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.parent.joinpath('extension-bar.png').write_bytes(
            Path(str(prefix) + '-bar.png').read_bytes())
        args.output.parent.joinpath('extension-menu.png').write_bytes(
            Path(str(prefix) + '-menu.png').read_bytes())
    report = {'passed': True, 'checks': checks,
              'screenshots': ['out/extensions-tests/extension-bar.png',
                              'out/extensions-tests/extension-menu.png'],
              'scope': 'Live extension hosting on the test X11 display; '
                       'no in-guest ISO session'}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
