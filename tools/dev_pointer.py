#!/usr/bin/python3
"""dev-pointer: move the real X core pointer to a screen position.

XWarpPointer against the root window — no extension, no VNC hop. Used by
GUI proofs to drive hover (the screen reader, hover feedback) exactly the
way a moving mouse would.
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dev_gui  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('x', type=int, help='target x on the root window')
    parser.add_argument('y', type=int, help='target y on the root window')
    args = parser.parse_args()
    toolkit = dev_gui.Toolkit()
    api, display = toolkit.api, toolkit.display
    api['warp'](display, 0, toolkit.root, 0, 0, 0, 0, args.x, args.y)
    api['flush'](display)
    print('pointer at %d,%d' % (args.x, args.y))


if __name__ == '__main__':
    main()
