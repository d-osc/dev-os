#!/usr/bin/python3
"""dev-ctl: drive windows in a running Dev OS session over the X protocol.

Handy when debugging by hand and used by GUI proofs:
  dev-ctl.py clients              list _NET_CLIENT_LIST window ids
  dev-ctl.py click WID X Y        synthetic button press+release
  dev-ctl.py drag WID X1 Y1 X2 Y2 synthetic title-bar drag
Coordinates are window-relative, exactly what XSendEvent delivers.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.append('/usr/lib/devos')
import dev_gui  # noqa: E402
from ctypes import (c_ulong, c_int, c_uint, c_void_p,  # noqa: E402
                    byref, pointer, cast, POINTER, c_char_p)


def named_clients(api, display, root):
    """[(id, title)] from _NET_CLIENT_LIST, for debugging and matching."""
    windows = clients(api, display, root)
    found = []
    for window in windows:
        name = c_char_p()
        if api['fetch_name'](display, window, byref(name)) and name.value:
            found.append((window, name.value.decode('utf-8', 'replace')))
            raw = cast(byref(name), POINTER(c_void_p)).contents.value
            api['x_free'](raw)
    return found


def clients(api, display, root):
    atom = api['atom'](display, b'_NET_CLIENT_LIST', 1)
    if not atom:
        return []
    actual, format_, count, remaining, data = (c_ulong(), c_int(), c_ulong(),
                                               c_ulong(), c_void_p())
    result = api['get_property'](display, root, atom, 0, 64, 0, 0,
                                 byref(actual), byref(format_), byref(count),
                                 byref(remaining), byref(data))
    if result != 0 or not count.value or format_.value != 32:
        return []
    try:
        return list((c_ulong * count.value).from_address(data.value))
    finally:
        if data.value:
            api['x_free'](data.value)


def send_button(api, display, xid, kind, x, y, state=0):
    import time
    event = dev_gui.XEvent()
    event.button.type = kind
    event.button.window = xid
    event.button.x = x
    event.button.y = y
    event.button.button = 1
    event.button.state = state
    event.button.same_screen = 1
    event.button.time = int(time.monotonic() * 1000)   # real-ish timestamps
    api['send_event'](display, xid, 0, 0, byref(event))


def geometry(api, display, xid):
    root, x, y = c_ulong(), c_int(), c_int()
    width, height, border, depth = c_uint(), c_uint(), c_uint(), c_uint()
    result = api['get_geometry'](display, xid, pointer(root), pointer(x),
                                 pointer(y), pointer(width), pointer(height),
                                 pointer(border), pointer(depth))
    if not result:          # XGetGeometry: True (1) on success, 0 on failure
        return None
    return (x.value, y.value, width.value, height.value)


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else ''
    toolkit = dev_gui.Toolkit()
    api, display = toolkit.api, toolkit.display
    root = toolkit.root
    if command == 'clients':
        windows = clients(api, display, root)
        print('clients:' + ','.join(str(item) for item in windows))
    elif command == 'windows':
        for window, title in named_clients(api, display, root):
            print('%x %s' % (window, title))
    elif command == 'geometry':
        box = geometry(api, display, int(sys.argv[2], 0))
        print('geometry:%s' % ('%d,%d,%d,%d' % box if box else 'unknown'))
    elif command == 'click':
        xid, x, y = int(sys.argv[2], 0), int(sys.argv[3]), int(sys.argv[4])
        send_button(api, display, xid, 4, x, y)
        send_button(api, display, xid, 5, x, y)
        api['flush'](display)
        print('clicked %s at %d,%d' % (hex(xid), x, y))
    elif command == 'activate':
        xid = int(sys.argv[2], 0)
        atom = api['atom'](display, b'_NET_ACTIVE_WINDOW', 1)
        message = dev_gui.XEvent()
        message.client.type = 33
        message.client.window = xid
        message.client.message_type = atom
        message.client.format = 32
        message.client.data[0] = 2
        api['send_event'](display, root, 0, (1 << 20) | (1 << 19), byref(message))
        api['flush'](display)
        print('activated %s' % hex(xid))
    elif command == 'map':
        xid = int(sys.argv[2], 0)
        api['map'](display, xid)
        api['raise_window'](display, xid)
        api['flush'](display)
        print('mapped %s' % hex(xid))
    elif command == 'drag':
        xid = int(sys.argv[2], 0)
        x1, y1, x2, y2 = (int(item) for item in sys.argv[3:7])
        send_button(api, display, xid, 4, x1, y1)
        steps = 6
        for step in range(1, steps + 1):
            x = x1 + (x2 - x1) * step // steps
            y = y1 + (y2 - y1) * step // steps
            send_button(api, display, xid, 6, x, y, state=0x100)
        send_button(api, display, xid, 5, x2, y2, state=0x100)
        api['flush'](display)
        print('dragged %s to +%d,+%d' % (hex(xid), x2 - x1, y2 - y1))
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main()
