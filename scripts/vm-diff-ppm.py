"""Diff three PPMs: report changed pixel counts between the pairs."""
import sys
from pathlib import Path


def pixels(path):
    data = Path(path).read_bytes()
    width, height = (int(value) for value in data.split()[1:3])
    offset = data.index(b'\n', data.index(b'\n', 3) + 1) + 1
    return width, height, data[offset:]


before, after, after2 = (pixels(path) for path in sys.argv[1:3 + 1][:3])
pairs = (('before->after1', before, after), ('after1->after2', after, after2))
for name, one, two in pairs:
    changed = sum(1 for a, b in zip(one, two) if a != b)
    print(name, 'changed bytes:', changed)
print('sizes equal:', len(one) == len(two) == len(before))
