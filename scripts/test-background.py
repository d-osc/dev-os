#!/usr/bin/env python3
"""Set every background format through settings.json and verify pixels."""
import argparse
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'tools'))
import dev_gui  # noqa: E402  (PNG writer for the fixture)

PNG_FIXTURE = 'out/greeter-tests/bg-png.png'
JPG_FIXTURE = 'out/greeter-tests/bg-jpg.jpg'
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200">'
       '<rect x="0" y="0" width="400" height="200" fill="#008000"/>'
       '<circle cx="330" cy="40" r="18" fill="#ffff00"/></svg>')
HTML = ('<html><body style="background:linear-gradient(#5a0000,#00005a)">'
        '<h1 style="left:60px; top:120px; font-size:44px; color:#ffffff">'
        'Dev OS</h1></body></html>')


def png_pixels(path):
    import zlib
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


def near(actual, expected, slack=70):
    return all(abs(a - b) <= slack for a, b in zip(actual, expected))


def shoot(settings_dir, shot):
    environment = dict(os.environ, DEVOS_SETTINGS=str(settings_dir))
    completed = subprocess.run(
        [sys.executable, str(PROJECT / 'tools/dev_greeter.py'),
         '--screenshot', str(shot)],
        capture_output=True, text=True, timeout=60, env=environment)
    if completed.returncode != 0:
        raise SystemExit(completed.stdout + completed.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
                        default=PROJECT / 'out/greeter-tests/background-result.json')
    args = parser.parse_args()
    if os.name != 'posix' or not os.environ.get('DISPLAY'):
        raise SystemExit('Run inside an X11 session such as WSLg (DISPLAY must be set)')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    red = bytearray()
    for _ in range(64):
        red += bytes((255, 30, 30)) * 64
    dev_gui.write_png(args.output.parent / 'bg-png.png', 64, 64, [red[i * 192:(i + 1) * 192] for i in range(64)])
    checks = []
    with tempfile.TemporaryDirectory(prefix='devos-bg-') as temporary:
        home = Path(temporary)
        (home / 'bg.svg').write_text(SVG)
        (home / 'bg.html').write_text(HTML)
        cases = [('png', str(args.output.parent / 'bg-png.png'), (255, 30, 30)),
                 ('svg', str(home / 'bg.svg'), (0, 128, 0)),
                 ('html', str(home / 'bg.html'), None)]
        jpg_path = None
        try:
            from PIL import Image
            jpg_path = home / 'bg.jpg'
            image = Image.new('RGB', (96, 96), (30, 30, 255))
            image.save(jpg_path, 'JPEG', quality=95)
        except ImportError:
            checks.append('jpg case skipped: Pillow not available for the fixture')
        if jpg_path:
            cases.insert(1, ('jpg', str(jpg_path), (30, 30, 255)))
        for name, value, expected in cases:
            settings = home / ('settings-%s.json' % name)
            settings.write_text(json.dumps({'desktop.background': value}))
            shot = home / ('shot-%s.png' % name)
            shoot(settings, shot)
            width, height, raw = png_pixels(shot)
            corners = [pixel(raw, width, 40, 40), pixel(raw, width, width - 40, 40),
                       pixel(raw, width, 40, height - 40)]
            if name == 'html':                      # gradient: top vs bottom differ
                bottom = pixel(raw, width, width // 2, height - 40)
                assert abs(corners[0][0] - bottom[2]) > 60, \
                    'html gradient not painted: %s vs %s' % (corners[0], bottom)
            else:
                assert all(near(corner, expected) for corner in corners), \
                    '%s background not painted: %s' % (name, corners)
            checks.append('%s background rendered through settings.json '
                          '(corners %s)' % (name, corners[0]))
        settings = home / 'settings-color.json'
        settings.write_text(json.dumps({'desktop.background': '#1e3a5f'}))
        shoot(settings, home / 'shot-color.png')
        width, height, raw = png_pixels(home / 'shot-color.png')
        assert near(pixel(raw, width, 40, 40), (0x1e, 0x3a, 0x5f)), 'color background'
        checks.append('#RRGGBB color background rendered')
    report = {'passed': True, 'checks': checks,
              'screenshots': [PNG_FIXTURE],
              'scope': 'Live background rendering through settings.json on the '
                       'test X11 display; no in-guest ISO session'}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
