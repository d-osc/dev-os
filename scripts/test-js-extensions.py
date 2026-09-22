#!/usr/bin/env python3
"""Run a JavaScript extension in the live shell through the Node runtime."""
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
MANIFEST = {'id': 'devos.js-proof', 'name': 'JS Proof', 'version': '1.0.0',
            'description': 'JavaScript live test', 'engine': 1,
            'main': 'extension.js'}
CODE = '''
module.exports.activate = function activate(api) {
  api.registerWidget("jsw", "left", 90, [
    { op: "rect", x: 0, y: 3, w: 86, h: 34, color: "blue", r: 4 },
    { op: "text", value: "JS", x: 8, y: 25, color: "text", size: 13, bold: true }
  ]);
  api.registerTray("jst", "wifi", "devos.jstest.run", "blue");
  api.registerCommand("devos.jstest.run", "Run JS",
                      () => api.notify("JS", "ran"), "From Node");
};
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
                        default=PROJECT / 'out/js-extension-tests/result.json')
    args = parser.parse_args()
    if os.name != 'posix' or not os.environ.get('DISPLAY'):
        raise SystemExit('Run inside an X11 session such as WSLg (DISPLAY must be set)')
    if shutil.which('node') is None:
        raise SystemExit('node is required on PATH (DEVOS_WITH_NODE=1 in the image)')
    blue = lambda p: p[2] > 200 and p[1] < 190 and p[0] < 120
    checks = []
    with tempfile.TemporaryDirectory(prefix='devos-jsext-test-') as temporary:
        home = Path(temporary)
        extension = home / 'extensions' / 'proof'
        extension.mkdir(parents=True)
        (extension / 'manifest.json').write_text(json.dumps(MANIFEST))
        (extension / 'extension.js').write_text(CODE)
        prefix = home / 'shell'
        completed = subprocess.run([sys.executable, str(PROJECT / 'tools/dev_shell.py'),
                                    '--extensions', str(home / 'extensions'),
                                    '--screenshot-prefix', str(prefix)],
                                   capture_output=True, text=True, timeout=60)
        if completed.returncode != 0:
            raise SystemExit(completed.stdout + completed.stderr)
        result = json.loads(completed.stdout.strip().splitlines()[0])
        assert result['extensions'] == ['devos.js-proof'], result
        assert result['widgets'] == 1 and result['commands'] == 1, result
        bar_w, bar_h, bar_raw = png_pixels(str(prefix) + '-bar.png')
        assert count(bar_w, bar_h, bar_raw, blue, 100, 320) > 40, 'JS widget missing'
        assert count(bar_w, bar_h, bar_raw, blue, bar_w - 210, bar_w - 110) > 8, \
            'JS tray icon missing'
        checks.append('JavaScript extension ran on Node: widget and tray icon painted '
                      'from declarative draw ops, command registered (%dx%d)'
                      % (bar_w, bar_h))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.parent.joinpath('js-bar.png').write_bytes(
            Path(str(prefix) + '-bar.png').read_bytes())
    report = {'passed': True, 'checks': checks,
              'screenshots': ['out/js-extension-tests/js-bar.png'],
              'scope': 'Live Node.js extension hosting on the test X11 display; '
                       'no in-guest ISO session'}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
