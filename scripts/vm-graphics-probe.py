"""Exit 0 when a VM screendump shows real graphics (not a text console).

Text consoles are black with gray/magenta glyphs; our GUI has large flat
dark-blue areas and theme colors, so a low-variance-black-but-not-pure-black
heuristic plus a green/red sample count separates them.
"""
import struct
import sys
from pathlib import Path


def pixels(path):
    data = Path(path).read_bytes()
    if not data.startswith(b'P6'):
        raise SystemExit('not a PPM')
    width, height = (int(value) for value in data.split()[1:3])
    offset = data.index(b'\n', data.index(b'\n', 3) + 1) + 1
    stride = width * 3
    return width, height, data[offset:offset + stride * height], stride


def main():
    width, height, raw, stride = pixels(sys.argv[1])
    green = blue_theme = 0
    for y in range(0, height, 4):
        base = y * stride
        for x in range(0, width, 4):
            position = base + x * 3
            red, green, blue = raw[position], raw[position + 1], raw[position + 2]
            if green > 150 and green > red + 60:
                green += 1
            elif red < 40 and green < 45 and 18 < blue < 60:
                blue_theme += 1
    graphics = green > 4 or blue_theme > 150
    raise SystemExit(0 if graphics else 1)


if __name__ == '__main__':
    main()
