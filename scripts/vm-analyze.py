"""Analyze a VM screendump: taskbar presence and stale login card."""
import sys
from pathlib import Path


def pixels(path):
    data = Path(path).read_bytes()
    width, height = (int(value) for value in data.split()[1:3])
    offset = data.index(b'\n', data.index(b'\n', 3) + 1) + 1
    stride = width * 3
    return width, height, data[offset:offset + stride * height], stride


width, height, raw, stride = pixels(sys.argv[1])
label = sys.argv[2]
green = white = stale = card = 0
for y in range(height):
    for x in range(0, width, 2):
        position = y * stride + x * 3
        red, grain, blue = raw[position], raw[position + 1], raw[position + 2]
        if y >= height - 40:
            if grain > 150 and grain > red + 60 and blue < 230:
                green += 1
            if min(red, grain, blue) > 165:
                white += 1
        if abs(height // 2 - 140) < y < abs(height // 2 + 80):
            if abs(x - width // 2) < 150 and abs(red - 17) < 6 \
                    and abs(grain - 24) < 6 and abs(blue - 39) < 6:
                stale += 1
center_y = height // 2 - 100
position = center_y * stride + (width // 2) * 3
card = tuple(raw[position:position + 3])
print('%s: taskbar-green=%d white=%d stale-card=%d center=%s'
      % (label, green, white, stale, card))
