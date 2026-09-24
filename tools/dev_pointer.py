#!/usr/bin/python3
"""dev-pointer: move and click through the real X core pointer.

XWarpPointer against the root window moves the pointer (no extension, no
VNC hop). --click-bar sends a synthetic ButtonPress/Release with XSendEvent
to the shell's taskbar window (its XID is published in /tmp/devos-bar-<uid>)
so GUI proofs can press tray buttons exactly like a mouse would.
"""
import argparse
import ctypes as c
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.append('/usr/lib/devos')
import dev_gui  # noqa: E402


def bar_window_id(path=None):
    """(xid, kb_right) published by the shell, or (None, None)."""
    path = Path(path) if path else Path('/tmp/devos-bar-%d' % os.getuid())
    try:
        parts = path.read_text().split()
        return int(parts[0]), int(parts[1]) if len(parts) > 1 else None
    except (OSError, ValueError):
        return None, None


def click_bar(toolkit, xid, x, y):
    """Deliver a synthetic button click on the bar window."""
    event = dev_gui.XEvent()
    for kind in (4, 5):                                  # press, release
        event.button.type = kind
        event.button.window = xid
        event.button.x = x
        event.button.y = y
        event.button.button = 1
        event.button.state = 0
        event.button.same_screen = 1
        toolkit.api['send_event'](toolkit.display, xid, 0, 0, c.byref(event))
    toolkit.api['flush'](toolkit.display)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('x', nargs='?', type=int, help='target x on the root window')
    parser.add_argument('y', nargs='?', type=int, help='target y on the root window')
    parser.add_argument('--click-bar', metavar=('X', 'Y'), nargs=2, type=int,
                        help='click the shell taskbar at these bar coordinates')
    parser.add_argument('--click-kb', action='store_true',
                        help='click the keyboard-layout badge in the tray')
    args = parser.parse_args()
    toolkit = dev_gui.Toolkit()
    api, display = toolkit.api, toolkit.display
    if args.click_kb or args.click_bar:
        xid, kb_right = bar_window_id()
        if not xid:
            raise SystemExit('no published bar window id (is dev-shell running?)')
        if args.click_kb:
            if not kb_right:
                raise SystemExit('the shell has not published the badge position yet')
            x, y = kb_right - 22, 20
        else:
            x, y = args.click_bar
        click_bar(toolkit, xid, x, y)
        print('clicked bar at %d,%d' % (x, y))
        return
    if args.x is None or args.y is None:
        parser.error('give x y, or --click-bar X Y, or --click-kb')
    api['warp'](display, 0, toolkit.root, 0, 0, 0, 0, args.x, args.y)
    api['flush'](display)
    print('pointer at %d,%d' % (args.x, args.y))


if __name__ == '__main__':
    main()
