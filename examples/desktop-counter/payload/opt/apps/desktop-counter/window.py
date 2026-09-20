#!/usr/bin/python3
"""Small native X11 window using Python's ctypes and the system libX11."""
import ctypes as c
import json
import os
from pathlib import Path
import sys
import time

x = c.CDLL('libX11.so.6')


def bind(name, result, *arguments):
    function = getattr(x, name)
    function.restype, function.argtypes = result, list(arguments)
    return function


ptr, ulong, integer = c.c_void_p, c.c_ulong, c.c_int
open_display = bind('XOpenDisplay', ptr, c.c_char_p)
display = open_display(None)
if not display:
    raise SystemExit('Unable to open desktop display')
screen = bind('XDefaultScreen', integer, ptr)(display)
root = bind('XRootWindow', ulong, ptr, integer)(display, screen)
window = bind('XCreateSimpleWindow', ulong, ptr, ulong, integer, integer, c.c_uint,
              c.c_uint, c.c_uint, ulong, ulong)(display, root, 80, 80, 560, 320, 0, 0, 0x142034)
bind('XStoreName', integer, ptr, ulong, c.c_char_p)(display, window, b'Dev Counter - Native DPK App')
atom = bind('XInternAtom', ulong, ptr, c.c_char_p, integer)(display, b'WM_DELETE_WINDOW', 0)
delete_atom = ulong(atom)
bind('XSetWMProtocols', integer, ptr, ulong, c.POINTER(ulong), integer)(display, window, c.byref(delete_atom), 1)
bind('XSelectInput', integer, ptr, ulong, c.c_long)(display, window, (1 << 15) | (1 << 2))
bind('XMapWindow', integer, ptr, ulong)(display, window)
gc = bind('XCreateGC', ptr, ptr, ulong, ulong, ptr)(display, window, 0, None)
foreground = bind('XSetForeground', integer, ptr, ptr, ulong)
draw = bind('XDrawString', integer, ptr, ulong, ptr, integer, integer, c.c_char_p, integer)
fill = bind('XFillRectangle', integer, ptr, ulong, ptr, integer, integer, c.c_uint, c.c_uint)
flush = bind('XFlush', integer, ptr)
pending = bind('XPending', integer, ptr)
next_event = bind('XNextEvent', integer, ptr, ptr)


class Button(c.Structure):
    _fields_ = [('type', integer), ('serial', ulong), ('send_event', integer), ('display', ptr),
                ('window', ulong), ('root', ulong), ('subwindow', ulong), ('time', ulong),
                ('x', integer), ('y', integer), ('x_root', integer), ('y_root', integer),
                ('state', c.c_uint), ('button', c.c_uint), ('same_screen', integer)]


class Client(c.Structure):
    _fields_ = [('type', integer), ('serial', ulong), ('send_event', integer), ('display', ptr),
                ('window', ulong), ('message_type', ulong), ('format', integer), ('data', c.c_long * 5)]


class Event(c.Union):
    _fields_ = [('type', integer), ('button', Button), ('client', Client), ('pad', c.c_long * 24)]


def label(text, left, top, color=0xe5edf8):
    foreground(display, gc, color)
    encoded = text.encode('ascii', errors='replace')
    draw(display, window, gc, left, top, encoded, len(encoded))


data = Path(os.environ['DEVOS_DATA_DIR'])
test_mode = '--test' in sys.argv
started = time.monotonic()
captured = False
running = True
while running:
    while pending(display):
        event = Event()
        next_event(display, c.byref(event))
        if event.type == 33 and event.client.data[0] == atom:
            running = False
        if event.type == 4 and 28 <= event.button.x <= 220 and 250 <= event.button.y <= 286:
            running = False
    foreground(display, gc, 0x142034)
    fill(display, window, gc, 0, 0, 560, 320)
    label('DEV OS / NATIVE APP', 28, 40, 0x65e0bf)
    label('Dev Counter', 28, 78)
    try:
        state = json.loads((data / 'counter.json').read_text())
        status = 'Running' if time.time() - state['updated'] < 3 else 'Stopped'
        label('Background: ' + status, 28, 122)
        label('Counter: ' + str(state['ticks']), 28, 158, 0x65e0bf)
    except (OSError, ValueError, KeyError):
        label('Background: start it with dev start desktop-counter', 28, 122)
    label('This window and the background are separate processes.', 28, 200)
    label('Closing this window leaves the counter running.', 28, 224)
    foreground(display, gc, 0x28425e)
    fill(display, window, gc, 28, 250, 192, 36)
    label('Close window', 50, 273)
    flush(display)
    if test_mode and not captured and time.monotonic() - started > 2:
        get_image = bind('XGetImage', ptr, ptr, ulong, integer, integer, c.c_uint, c.c_uint, ulong, integer)
        image = get_image(display, window, 0, 0, 560, 320, c.c_ulong(-1).value, 2)
        if image:
            pixel = bind('XGetPixel', ulong, ptr, integer, integer)
            with (data / 'window.ppm').open('wb') as output:
                output.write(b'P6\n560 320\n255\n')
                for y in range(320):
                    row = bytearray()
                    for horizontal in range(560):
                        value = pixel(image, horizontal, y)
                        row.extend(((value >> 16) & 255, (value >> 8) & 255, value & 255))
                    output.write(row)
            bind('XDestroyImage', integer, ptr)(image)
            captured = True
    if test_mode and time.monotonic() - started > 4:
        running = False
    time.sleep(0.1)
bind('XFreeGC', integer, ptr, ptr)(display, gc)
bind('XDestroyWindow', integer, ptr, ulong)(display, window)
bind('XCloseDisplay', integer, ptr)(display)
