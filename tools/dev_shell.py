#!/usr/bin/python3
"""Dev OS desktop shell: a 24px taskbar with an application menu and clock.

X11 through ctypes with Cairo for detailed rendering: anti-aliased TrueType
text, gradients and rounded corners, on the same stack the DPK window runtime
uses plus libcairo/fontconfig (the OS image must ship them). The bar reserves
the bottom 24 pixels of the screen with EWMH struts. The menu is a translucent
32-bit ARGB popup when the server offers that visual; evidence capture uses
24-bit windows because XWayland on the test display cannot capture ARGB or
override-redirect windows. Launching an app needs an explicit per-launch
consent and then runs `dev launch <name> --allow <declared permissions>`: the
shell never widens a permission set and keeps no grants. It is a normal user
process for an X11 session; the OS image does not start it automatically yet.
"""
import argparse
import ctypes as c
import json
from pathlib import Path
import struct
import subprocess
import sys
import time
import zlib

BAR_HEIGHT = 24
MENU_BUTTON_WIDTH = 64
TASK_BUTTON_WIDTH = 160
CLOCK_PAD = 10
MENU_WIDTH = 320
MENU_ITEM_HEIGHT = 36
MENU_HEADER_HEIGHT = 26
CONSENT_HEIGHT = 52
MENU_RADIUS = 12
ALLOW_X, CANCEL_X = 214, 288
FONT = b'DejaVu Sans'
PALETTE = {'bar_low': (0.043, 0.082, 0.149), 'bar_high': (0.094, 0.153, 0.251),
           'panel': (0.051, 0.086, 0.149), 'panel_border': (0.398, 0.878, 0.749),
           'text': (0.898, 0.929, 0.973), 'dim': (0.576, 0.655, 0.769),
           'accent': (0.398, 0.878, 0.749), 'accent_dark': (0.051, 0.086, 0.149)}


# ---------------------------------------------------------------- pure logic

def applications(database):
    """Menu entries for packages that declare a window, sorted by label."""
    items = []
    for name, record in (database or {}).items():
        if not isinstance(record, dict) or 'window' not in record:
            continue
        launcher = record.get('launcher') or {}
        label = launcher.get('name') or record.get('display_name') or name
        items.append({'name': name, 'label': str(label)[:48],
                      'comment': str(launcher.get('comment') or record.get('description') or '')[:80],
                      'categories': launcher.get('categories') or ['Utility'],
                      'permissions': list(record.get('permissions') or [])})
    return sorted(items, key=lambda item: item['label'].lower())


def grant_for(item):
    """The exact allow list `dev launch` expects; never wider than declared."""
    return ','.join(item['permissions'])


def launch_command(dev, root, item):
    """The argv that opens one app. A bare name uses the installed dev."""
    base = [dev] if dev == 'dev' else [sys.executable, str(dev), '--root', str(root)]
    return base + ['launch', item['name'], '--allow', grant_for(item)]


def clock_text(moment=None):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(moment))


def truncate(text, measure, max_px):
    """Shorten text to max_px using measure(text)->pixels."""
    if measure(text) <= max_px:
        return text
    while text and measure(text + '...') > max_px:
        text = text[:-1]
    return (text + '...') if text else '...'


def bar_regions(width, clock, task_count=0):
    """Clickable spans of the bar: (kind, start, end, index)."""
    regions = [('menu', 0, MENU_BUTTON_WIDTH, None)]
    left = MENU_BUTTON_WIDTH + 1
    for index in range(task_count):
        regions.append(('task', left, left + TASK_BUTTON_WIDTH - 8, index))
        left += TASK_BUTTON_WIDTH
    regions.append(('clock', width - CLOCK_PAD * 2 - len(clock) * 6, width, None))
    return regions


def bar_hit(width, clock, x, task_count=0):
    for kind, start, end, index in bar_regions(width, clock, task_count):
        if start <= x < end:
            return kind, index
    return None, None


def menu_geometry(screen_width, screen_height, item_count, consent=False):
    height = MENU_HEADER_HEIGHT + max(1, item_count) * MENU_ITEM_HEIGHT
    height = min(height + (CONSENT_HEIGHT if consent else 0), screen_height - BAR_HEIGHT - 2)
    return {'x': 2, 'y': screen_height - BAR_HEIGHT - height - 2,
            'width': min(MENU_WIDTH, screen_width - 4), 'height': height}


def item_at(item_count, y, consent=False):
    """Menu item index for a click on the popup; -1 hits the consent row."""
    index = (y - MENU_HEADER_HEIGHT) // MENU_ITEM_HEIGHT
    if 0 <= index < item_count:
        return index
    return -1 if consent and y >= MENU_HEADER_HEIGHT + item_count * MENU_ITEM_HEIGHT else None


def consent_choice(x, y, item_count, consent):
    """None/'allow'/'cancel' for a click in the consent row."""
    if not consent or y < MENU_HEADER_HEIGHT + item_count * MENU_ITEM_HEIGHT:
        return None
    if ALLOW_X <= x < CANCEL_X:
        return 'allow'
    if x >= CANCEL_X:
        return 'cancel'
    return None


def write_png(path, width, height, rgb_rows):
    """Write RGB rows (each width*3 bytes) as a PNG file."""

    def chunk(tag, data):
        block = tag + data
        return struct.pack('>I', len(data)) + block + struct.pack('>I', zlib.crc32(block))

    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    raw = b''.join(b'\x00' + bytes(row) for row in rgb_rows)
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) +
                           chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


def load_database(root):
    path = Path(root) / 'var/lib/dev/installed.json'
    if not path.is_file():
        return {}
    database = json.loads(path.read_text())
    if not isinstance(database, dict):
        raise SystemExit('Invalid installed package database')
    return database


# ------------------------------------------------------------------- X11 side

class XAny(c.Structure):
    _fields_ = [('type', c.c_int), ('serial', c.c_ulong), ('send_event', c.c_int),
                ('display', c.c_void_p), ('window', c.c_ulong)]


class XButton(c.Structure):
    _fields_ = [('type', c.c_int), ('serial', c.c_ulong), ('send_event', c.c_int),
                ('display', c.c_void_p), ('window', c.c_ulong), ('root', c.c_ulong),
                ('subwindow', c.c_ulong), ('time', c.c_ulong), ('x', c.c_int), ('y', c.c_int),
                ('x_root', c.c_int), ('y_root', c.c_int), ('state', c.c_uint),
                ('button', c.c_uint), ('same_screen', c.c_int)]


class XClient(c.Structure):
    _fields_ = [('type', c.c_int), ('serial', c.c_ulong), ('send_event', c.c_int),
                ('display', c.c_void_p), ('window', c.c_ulong), ('message_type', c.c_ulong),
                ('format', c.c_int), ('data', c.c_long * 5)]


class XEvent(c.Union):
    _fields_ = [('any', XAny), ('button', XButton), ('client', XClient), ('pad', c.c_long * 24)]


class XImage(c.Structure):
    _fields_ = [('width', c.c_int), ('height', c.c_int), ('xoffset', c.c_int),
                ('format', c.c_int), ('data', c.c_void_p), ('byte_order', c.c_int),
                ('bitmap_unit', c.c_int), ('bitmap_bit_order', c.c_int),
                ('bitmap_pad', c.c_int), ('depth', c.c_int), ('bytes_per_line', c.c_int),
                ('bits_per_pixel', c.c_int), ('red_mask', c.c_long), ('green_mask',
                c.c_long), ('blue_mask', c.c_long)]


class VisualInfo(c.Structure):
    _fields_ = [('visual', c.c_void_p), ('visualid', c.c_ulong), ('screen', c.c_int),
                ('depth', c.c_int), ('class_', c.c_int), ('red_mask', c.c_ulong),
                ('green_mask', c.c_ulong), ('blue_mask', c.c_ulong), ('colormap_size', c.c_int),
                ('bits_per_rgb', c.c_int)]


class SetWindowAttributes(c.Structure):
    _fields_ = [('background_pixmap', c.c_ulong), ('background_pixel', c.c_ulong),
                ('border_pixmap', c.c_ulong), ('border_pixel', c.c_ulong),
                ('bit_gravity', c.c_int), ('win_gravity', c.c_int), ('backing_store', c.c_int),
                ('backing_planes', c.c_ulong), ('backing_pixel', c.c_ulong), ('save_under', c.c_int),
                ('event_mask', c.c_long), ('do_not_propagate_mask', c.c_int),
                ('override_redirect', c.c_int), ('colormap', c.c_ulong), ('cursor', c.c_ulong)]


class TextExtents(c.Structure):
    _fields_ = [(name, c.c_double) for name in
                ('x_bearing', 'y_bearing', 'width', 'height', 'x_advance', 'y_advance')]


_X_ERROR_HANDLER = None


def connect():
    x = c.CDLL('libX11.so.6')

    def bind(name, result, *arguments):
        function = getattr(x, name)
        function.restype, function.argtypes = result, list(arguments)
        return function

    api = {
        'open_display': bind('XOpenDisplay', c.c_void_p, c.c_char_p),
        'display_width': bind('XDisplayWidth', c.c_int, c.c_void_p, c.c_int),
        'display_height': bind('XDisplayHeight', c.c_int, c.c_void_p, c.c_int),
        'root_window': bind('XRootWindow', c.c_ulong, c.c_void_p, c.c_int),
        'create': bind('XCreateSimpleWindow', c.c_ulong, c.c_void_p, c.c_ulong, c.c_int,
                       c.c_int, c.c_uint, c.c_uint, c.c_uint, c.c_ulong, c.c_ulong),
        'move_resize': bind('XMoveResizeWindow', c.c_int, c.c_void_p, c.c_ulong, c.c_int,
                            c.c_int, c.c_uint, c.c_uint),
        'store_name': bind('XStoreName', c.c_int, c.c_void_p, c.c_ulong, c.c_char_p),
        'select_input': bind('XSelectInput', c.c_int, c.c_void_p, c.c_ulong, c.c_long),
        'map': bind('XMapWindow', c.c_int, c.c_void_p, c.c_ulong),
        'unmap': bind('XUnmapWindow', c.c_int, c.c_void_p, c.c_ulong),
        'create_gc': bind('XCreateGC', c.c_void_p, c.c_void_p, c.c_ulong, c.c_ulong, c.c_void_p),
        'fetch_name': bind('XFetchName', c.c_int, c.c_void_p, c.c_ulong, c.POINTER(c.c_char_p)),
        'flush': bind('XFlush', c.c_int, c.c_void_p),
        'pending': bind('XPending', c.c_int, c.c_void_p),
        'next_event': bind('XNextEvent', c.c_int, c.c_void_p, c.c_void_p),
        'atom': bind('XInternAtom', c.c_ulong, c.c_void_p, c.c_char_p, c.c_int),
        'change_property': bind('XChangeProperty', c.c_int, c.c_void_p, c.c_ulong, c.c_ulong,
                                c.c_ulong, c.c_int, c.c_int, c.c_void_p, c.c_int),
        'get_property': bind('XGetWindowProperty', c.c_int, c.c_void_p, c.c_ulong, c.c_ulong,
                             c.c_long, c.c_long, c.c_int, c.c_void_p, c.c_void_p, c.c_void_p,
                             c.c_void_p, c.c_void_p, c.POINTER(c.c_void_p)),
        'raise_window': bind('XRaiseWindow', c.c_int, c.c_void_p, c.c_ulong),
        'set_input_focus': bind('XSetInputFocus', c.c_int, c.c_void_p, c.c_ulong, c.c_int, c.c_long),
        'grab_pointer': bind('XGrabPointer', c.c_int, c.c_void_p, c.c_ulong, c.c_int, c.c_uint,
                             c.c_uint, c.c_uint, c.c_ulong, c.c_long),
        'ungrab_pointer': bind('XUngrabPointer', c.c_int, c.c_void_p, c.c_long),
        'get_image': bind('XGetImage', c.c_void_p, c.c_void_p, c.c_ulong, c.c_int, c.c_int,
                          c.c_uint, c.c_uint, c.c_ulong, c.c_int),
        'sync': bind('XSync', c.c_int, c.c_void_p, c.c_int),
        'free': bind('XFree', c.c_int, c.c_void_p),
        'set_protocols': bind('XSetWMProtocols', c.c_int, c.c_void_p, c.c_ulong,
                              c.POINTER(c.c_ulong), c.c_int),
        'match_visual': bind('XMatchVisualInfo', c.c_int, c.c_void_p, c.c_int, c.c_int, c.c_int,
                             c.POINTER(VisualInfo)),
        'default_visual': bind('XDefaultVisual', c.c_void_p, c.c_void_p, c.c_int),
        'create_colormap': bind('XCreateColormap', c.c_ulong, c.c_void_p, c.c_ulong,
                                c.c_void_p, c.c_int),
        'create_window': bind('XCreateWindow', c.c_ulong, c.c_void_p, c.c_ulong, c.c_int, c.c_int,
                              c.c_uint, c.c_uint, c.c_uint, c.c_int, c.c_uint, c.c_void_p,
                              c.c_ulong, c.c_void_p),
    }
    x.XSetErrorHandler.argtypes = [c.c_void_p]
    x.XSetErrorHandler.restype = c.c_int

    def ignore(*_):
        return 0

    # The callback must outlive every X call: a collected handler crashes the
    # process the moment the server reports its first async error.
    global _X_ERROR_HANDLER
    _X_ERROR_HANDLER = c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_void_p, c.c_void_p)(ignore)
    x.XSetErrorHandler(_X_ERROR_HANDLER)
    return x, api


class Cairo:
    """The small slice of Cairo used by the shell, bound through ctypes."""

    def __init__(self):
        self.lib = c.CDLL('libcairo.so.2')
        lib = self.lib

        def bind(name, result, *arguments):
            function = getattr(lib, name)
            function.restype, function.argtypes = result, list(arguments)
            return function

        self.surface_create = bind('cairo_xlib_surface_create', c.c_void_p, c.c_void_p,
                                   c.c_ulong, c.c_void_p, c.c_int, c.c_int)
        self.surface_set_size = bind('cairo_xlib_surface_set_size', None, c.c_void_p, c.c_int,
                                     c.c_int)
        self.surface_flush = bind('cairo_surface_flush', None, c.c_void_p)
        self.create = bind('cairo_create', c.c_void_p, c.c_void_p)
        self.destroy = bind('cairo_destroy', None, c.c_void_p)
        self.set_rgba = bind('cairo_set_source_rgba', None, c.c_void_p, c.c_double,
                             c.c_double, c.c_double, c.c_double)
        self.paint = bind('cairo_paint', None, c.c_void_p)
        self.new_sub_path = bind('cairo_new_sub_path', None, c.c_void_p)
        self.arc = bind('cairo_arc', None, c.c_void_p, c.c_double, c.c_double, c.c_double,
                        c.c_double, c.c_double)
        self.line_to = bind('cairo_line_to', None, c.c_void_p, c.c_double, c.c_double)
        self.close_path = bind('cairo_close_path', None, c.c_void_p)
        self.fill = bind('cairo_fill', None, c.c_void_p)
        self.stroke = bind('cairo_stroke', None, c.c_void_p)
        self.set_line_width = bind('cairo_set_line_width', None, c.c_void_p, c.c_double)
        self.move_to = bind('cairo_move_to', None, c.c_void_p, c.c_double, c.c_double)
        self.show_text = bind('cairo_show_text', None, c.c_void_p, c.c_char_p)
        self.font_face = bind('cairo_select_font_face', None, c.c_void_p, c.c_char_p,
                              c.c_int, c.c_int)
        self.font_size = bind('cairo_set_font_size', None, c.c_void_p, c.c_double)
        self.text_extents = bind('cairo_text_extents', None, c.c_void_p, c.c_char_p,
                                 c.POINTER(TextExtents))
        self.pattern_linear = bind('cairo_pattern_create_linear', c.c_void_p, c.c_double,
                                   c.c_double, c.c_double, c.c_double)
        self.pattern_stop = bind('cairo_pattern_add_color_stop_rgba', None, c.c_void_p,
                                 c.c_double, c.c_double, c.c_double, c.c_double, c.c_double)
        self.set_source_pattern = bind('cairo_set_source', None, c.c_void_p, c.c_void_p)

    def surface(self, display, drawable, visual, width, height):
        return self.surface_create(display, drawable, visual, width, height)

    def rounded(self, cr, x, y, width, height, radius):
        """Trace a rounded rectangle path."""
        import math
        half = math.pi / 2
        self.new_sub_path(cr)
        self.arc(cr, x + width - radius, y + radius, radius, -half, 0)
        self.arc(cr, x + width - radius, y + height - radius, radius, 0, half)
        self.arc(cr, x + radius, y + height - radius, radius, half, 2 * half)
        self.arc(cr, x + radius, y + radius, radius, 2 * half, 3 * half)
        self.close_path(cr)


def decode_rows(image):
    """ZPixmap buffer to RGB rows using the visual's channel masks."""
    masks = {'red': image.red_mask, 'green': image.green_mask, 'blue': image.blue_mask}
    if not all(masks.values()) or image.bits_per_pixel not in (24, 32):
        raise SystemExit('Unsupported X visual for screenshots')
    shifts = {name: mask.bit_length() - 8 for name, mask in masks.items()}
    bypp = image.bits_per_pixel // 8
    raw = c.string_at(image.data, image.bytes_per_line * image.height)
    rows = []
    for y in range(image.height):
        row = bytearray()
        base = y * image.bytes_per_line
        for x in range(image.width):
            offset = base + x * bypp
            if image.bits_per_pixel == 24:
                blue, green, red = raw[offset], raw[offset + 1], raw[offset + 2]
            else:
                order = 'little' if image.byte_order == 0 else 'big'
                pixel = int.from_bytes(raw[offset:offset + bypp], order)
                red = (pixel & masks['red']) >> shifts['red']
                green = (pixel & masks['green']) >> shifts['green']
                blue = (pixel & masks['blue']) >> shifts['blue']
            row += bytes((red, green, blue))
        rows.append(row)
    return rows


def screenshot(x, api, display, window, path, width, height):
    pointer = api['get_image'](display, window, 0, 0, width, height, 0xFFFFFFFF, 2)
    if not pointer:
        raise SystemExit('Could not capture the shell window')
    try:
        write_png(path, width, height, decode_rows(XImage.from_address(pointer)))
    finally:
        x.XFree(pointer)


def property_windows(x, api, display, root, name):
    atom = api['atom'](display, name.encode(), 1)
    if not atom:
        return []
    actual, format_, count, data = c.c_ulong(), c.c_int(), c.c_ulong(), c.c_void_p()
    result = api['get_property'](display, root, atom, 0, 0, 1024, 0,
                                 None, c.byref(actual), c.byref(format_),
                                 c.byref(count), c.byref(data))
    if result != 0 or not count.value or format_.value != 32:
        return []
    try:
        return list((c.c_ulong * count.value).from_address(data.value))
    finally:
        x.XFree(data.value)


def run(root, *, dev='dev', shots=None):
    x, api = connect()
    cairo = Cairo()
    display = api['open_display'](None)
    if not display:
        raise SystemExit('Unable to open desktop display')
    width = api['display_width'](display, 0)
    height = api['display_height'](display, 0)
    root_window = api['root_window'](display, 0)
    bar = api['create'](display, root_window, 0, height - BAR_HEIGHT, width, BAR_HEIGHT,
                        1, 0x142034, 0x142034)
    api['store_name'](display, bar, b'Dev OS Shell')

    # The menu prefers a 32-bit ARGB visual for true translucency; capture
    # mode stays on the default visual because the test display's XWayland
    # cannot capture ARGB or override-redirect windows.
    default_visual = api['default_visual'](display, 0)
    info = VisualInfo()
    argb = shots is None and api['match_visual'](display, 0, 32, 4, c.byref(info))
    if argb:
        colormap = api['create_colormap'](display, root_window, info.visual, 0)
        attributes = SetWindowAttributes(border_pixel=0, colormap=colormap,
                                         override_redirect=1, event_mask=1 << 15)
        menu = api['create_window'](display, root_window, 0, 0, 100, 100, 0, 32, 1,
                                    info.visual, 1 | 2 | 0x400 | 0x800, c.byref(attributes))
        menu_visual = info.visual
    else:
        menu = api['create'](display, root_window, 0, 0, 100, 100, 1, 0x101b2c, 0x101b2c)
        menu_visual = default_visual
    api['store_name'](display, menu, b'Dev OS Menu')

    def atoms(names):
        return [api['atom'](display, item.encode(), 1) for item in names]

    def set_atom_values(window, name, values, kind):
        array = (c.c_ulong * len(values))(*values)
        api['change_property'](display, window, api['atom'](display, name.encode(), 0),
                               api['atom'](display, kind.encode(), 0), 32, 0,
                               c.cast(array, c.c_void_p), len(values))

    def set_atoms(window, name, value_names):
        set_atom_values(window, name, atoms(value_names), 'ATOM')

    def set_cardinals(window, name, values):
        set_atom_values(window, name, values, 'CARDINAL')

    set_atoms(bar, '_NET_WM_WINDOW_TYPE', ['_NET_WM_WINDOW_TYPE_DOCK'])
    set_atoms(bar, '_NET_WM_STATE', ['_NET_WM_STATE_ABOVE', '_NET_WM_STATE_SKIP_TASKBAR',
                                     '_NET_WM_STATE_SKIP_PAGER'])
    set_cardinals(bar, '_NET_WM_DESKTOP', [0xFFFFFFFF])
    set_cardinals(bar, '_NET_WM_STRUT', [0, 0, 0, BAR_HEIGHT])
    set_cardinals(bar, '_NET_WM_STRUT_PARTIAL',
                  [0, 0, 0, BAR_HEIGHT, 0, 0, 0, 0, 0, 0, 0, width])
    protocols = api['atom'](display, b'WM_PROTOCOLS', 1)
    delete = api['atom'](display, b'WM_DELETE_WINDOW', 1)
    api['set_protocols'](display, bar, c.byref(c.c_ulong(delete)), 1)

    bar_surface = cairo.surface(display, bar, default_visual, width, BAR_HEIGHT)
    cr_bar = cairo.create(bar_surface)
    menu_surface = [None]
    cr_menu = [None]

    def menu_surface_for(w, h):
        if menu_surface[0] is None:
            menu_surface[0] = cairo.surface(display, menu, menu_visual, w, h)
            cr_menu[0] = cairo.create(menu_surface[0])
        else:
            cairo.surface_set_size(menu_surface[0], w, h)
        return cr_menu[0]

    def styled(cr, size=12.0, bold=False):
        cairo.font_size(cr, size)
        cairo.font_face(cr, FONT, 0, 1 if bold else 0)

    def text(cr, content, px, py, color, size=12.0, bold=False, alpha=1.0):
        styled(cr, size, bold)
        cairo.set_rgba(cr, *color, alpha)
        cairo.move_to(cr, px, py)
        cairo.show_text(cr, content.encode('utf-8'))

    extents = TextExtents()

    def measure(content, size=12.0, bold=False):
        styled(cr_bar, size, bold)
        cairo.text_extents(cr_bar, content.encode('utf-8'), c.byref(extents))
        return extents.x_advance

    items = applications(load_database(root))
    consent = None
    menu_open = False
    clock = ''

    def clients():
        found = []
        for window in property_windows(x, api, display, root_window, '_NET_CLIENT_LIST'):
            name = c.c_char_p()
            if window not in (bar, menu) and api['fetch_name'](display, window, c.byref(name)) \
                    and name.value:
                found.append((name.value.decode('utf-8', 'replace'), window))
                x.XFree(name.value)
        return found

    def place_menu():
        geometry = menu_geometry(width, height, len(items), consent is not None)
        api['move_resize'](display, menu, geometry['x'], geometry['y'],
                           geometry['width'], geometry['height'])
        menu_surface_for(geometry['width'], geometry['height'])

    def open_menu(state):
        nonlocal menu_open, consent
        menu_open, consent = state, None
        if state:
            place_menu()
            api['map'](display, menu)
            api['grab_pointer'](display, menu, 0, 1 << 2, 1, 1, 0, 0, 0)
        else:
            api['ungrab_pointer'](display, 0)
            api['unmap'](display, menu)

    def draw_bar():
        nonlocal clock
        gradient = cairo.pattern_linear(cr_bar, 0, 0, 0, BAR_HEIGHT)
        cairo.pattern_stop(gradient, 0.0, *PALETTE['bar_low'], 1.0)
        cairo.pattern_stop(gradient, 1.0, *PALETTE['bar_high'], 1.0)
        cairo.set_source_pattern(cr_bar, gradient)
        cairo.paint(cr_bar)
        # Hairline separating the bar from the desktop.
        cairo.set_rgba(cr_bar, *PALETTE['accent'], 0.30)
        cairo.set_line_width(cr_bar, 1)
        cairo.new_sub_path(cr_bar)
        cairo.line_to(cr_bar, 0, 0.5)
        cairo.line_to(cr_bar, width, 0.5)
        cairo.stroke(cr_bar)
        # MENU pill button with a mint underline.
        cairo.set_rgba(cr_bar, *PALETTE['accent'], 0.14)
        cairo.rounded(cr_bar, 4, 3, MENU_BUTTON_WIDTH - 10, BAR_HEIGHT - 6, 8)
        cairo.fill(cr_bar)
        text(cr_bar, 'MENU', 16, 16, PALETTE['accent'], 11.0, True)
        left = MENU_BUTTON_WIDTH + 1
        tasks = clients()
        room = int(max(0, (width - MENU_BUTTON_WIDTH - measure(clock_text(), 11.0) - 40)
                       // TASK_BUTTON_WIDTH))
        for title, window in tasks[:room]:
            cairo.set_rgba(cr_bar, 1.0, 1.0, 1.0, 0.06)
            cairo.rounded(cr_bar, left + 2, 3, TASK_BUTTON_WIDTH - 12, BAR_HEIGHT - 6, 7)
            cairo.fill(cr_bar)
            cairo.set_rgba(cr_bar, 1.0, 1.0, 1.0, 0.10)
            cairo.rounded(cr_bar, left + 2, 3, TASK_BUTTON_WIDTH - 12, BAR_HEIGHT - 6, 7)
            cairo.stroke(cr_bar)
            label = truncate(' '.join(title.split()), lambda s: measure(s, 10.5),
                             TASK_BUTTON_WIDTH - 28) or 'window'
            text(cr_bar, label, left + 10, 16, PALETTE['text'], 10.5)
            left += TASK_BUTTON_WIDTH
        clock = clock_text()
        text(cr_bar, clock, width - measure(clock, 11.0) - CLOCK_PAD, 16, PALETTE['text'], 11.0)
        cairo.surface_flush(bar_surface)
        api['flush'](display)
        return tasks

    def draw_menu(geometry):
        cr = menu_surface_for(geometry['width'], geometry['height'])
        w, h = geometry['width'], geometry['height']
        panel = PALETTE['panel']
        if argb:
            cairo.set_rgba(cr, 0, 0, 0, 0)
            cairo.paint(cr)
            cairo.set_rgba(cr, 0, 0, 0, 0.45)
            cairo.rounded(cr, 2, 3, w - 4, h, MENU_RADIUS + 2)
            cairo.fill(cr)
        else:
            # Without alpha the desktop behind is simulated so the rounded
            # corners stay visible in captured evidence.
            cairo.set_rgba(cr, *PALETTE['bar_low'], 1.0)
            cairo.paint(cr)
        cairo.set_rgba(cr, *panel, 0.97)
        cairo.rounded(cr, 0, 0, w, h - 2, MENU_RADIUS)
        cairo.fill(cr)
        cairo.set_rgba(cr, *PALETTE['panel_border'], 0.35)
        cairo.set_line_width(cr, 1)
        cairo.rounded(cr, 0.5, 0.5, w - 1, h - 3, MENU_RADIUS)
        cairo.stroke(cr)
        cairo.set_rgba(cr, *PALETTE['accent'], 1.0)
        cairo.arc(cr, 14, 14, 3, 0, 6.2832)
        cairo.fill(cr)
        text(cr, 'DEV OS', 24, 18, PALETTE['text'], 11.5, True)
        cairo.set_rgba(cr, 1.0, 1.0, 1.0, 0.10)
        cairo.set_line_width(cr, 1)
        cairo.new_sub_path(cr)
        cairo.line_to(cr, 8, MENU_HEADER_HEIGHT - 3.5)
        cairo.line_to(cr, w - 8, MENU_HEADER_HEIGHT - 3.5)
        cairo.stroke(cr)
        top = MENU_HEADER_HEIGHT
        for item in items:
            if consent is not None and item is consent:
                cairo.set_rgba(cr, *PALETTE['accent'], 0.10)
                cairo.rounded(cr, 4, top + 2, w - 8, MENU_ITEM_HEIGHT - 4, 8)
                cairo.fill(cr)
            text(cr, item['label'], 14, top + 17, PALETTE['text'], 12.5, True)
            detail = ' · '.join(item['categories'][:2] +
                                [','.join(item['permissions']) or 'no permissions'])
            text(cr, truncate(detail, lambda s: measure(s, 10.0), w - 30), 26, top + 31,
                 PALETTE['dim'], 10.0)
            top += MENU_ITEM_HEIGHT
        if consent:
            cairo.set_rgba(cr, *PALETTE['accent'], 0.08)
            cairo.rounded(cr, 4, top + 2, w - 8, CONSENT_HEIGHT - 6, 8)
            cairo.fill(cr)
            text(cr, 'Open ' + truncate(consent['label'], lambda s: measure(s, 12.0, True), 170)
                 + '?', 14, top + 19, PALETTE['text'], 12.0, True)
            text(cr, truncate(grant_for(consent), lambda s: measure(s, 10.0), 196)
                 or 'no permissions', 14, top + 37, PALETTE['dim'], 10.0)
            cairo.set_rgba(cr, *PALETTE['accent'], 1.0)
            cairo.rounded(cr, ALLOW_X, top + 12, 64, 22, 11)
            cairo.fill(cr)
            text(cr, 'ALLOW', ALLOW_X + 14, top + 28, PALETTE['accent_dark'], 10.5, True)
            text(cr, 'cancel', CANCEL_X, top + 28, PALETTE['dim'], 10.5)
        cairo.surface_flush(menu_surface[0])
        api['flush'](display)

    api['select_input'](display, bar, (1 << 15) | (1 << 2) | (1 << 3))
    api['select_input'](display, menu, (1 << 15) | (1 << 2))
    api['select_input'](display, root_window, 1 << 18)
    api['map'](display, bar)
    running = True
    started = time.monotonic()
    captured = shots is None
    while running:
        geometry = menu_geometry(width, height, len(items), consent is not None)
        tasks = draw_bar()
        if menu_open:
            draw_menu(geometry)
        while api['pending'](display):
            event = XEvent()
            api['next_event'](display, c.byref(event))
            kind = event.any.type
            if (kind == 33 and event.client.message_type == protocols
                    and event.client.data[0] == delete):
                running = False
            elif kind == 4 and event.button.window == bar:
                hit, index = bar_hit(width, clock, event.button.x, len(tasks))
                if hit == 'menu':
                    open_menu(not menu_open)
                elif hit == 'task' and index < len(tasks):
                    api['raise_window'](display, tasks[index][1])
                    api['set_input_focus'](display, tasks[index][1], 1, 0)
            elif kind == 4 and event.button.window == menu:
                index = item_at(len(items), event.button.y, consent is not None)
                choice = consent_choice(event.button.x, event.button.y, len(items),
                                        consent is not None)
                if choice == 'allow':
                    subprocess.Popen(launch_command(dev, root, consent), start_new_session=True,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    open_menu(False)
                elif choice == 'cancel':
                    consent = None
                    draw_menu(menu_geometry(width, height, len(items), False))
                elif index is not None and index >= 0 and not consent:
                    consent = items[index]
                    draw_menu(menu_geometry(width, height, len(items), True))
            elif kind == 4 and menu_open:
                open_menu(False)  # A click outside the popup closes it.
        if not captured and time.monotonic() - started >= 1.0:
            captured = True
            api['sync'](display, 0)
            screenshot(x, api, display, bar, shots[0], width, BAR_HEIGHT)
            if not menu_open:
                open_menu(True)
            consent = items[0] if items else None
            place_menu()
            geometry = menu_geometry(width, height, len(items), consent is not None)
            draw_menu(geometry)
            # XWayland needs a compositor round trip after a resize before the
            # window has a capturable surface again; redraw onto the settled
            # surface right before capturing it.
            api['sync'](display, 0)
            time.sleep(0.6)
            api['sync'](display, 0)
            draw_menu(geometry)
            api['sync'](display, 0)
            screenshot(x, api, display, menu, shots[1], geometry['width'], geometry['height'])
            running = False
        time.sleep(0.2)
    return {'screen': [width, height], 'applications': len(items)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='/', help='target root (default: /)')
    parser.add_argument('--dev', default='dev', help='dev command used for launches')
    parser.add_argument('--screenshot-prefix', type=Path,
                        help='capture bar and menu PNGs once, then exit')
    args = parser.parse_args()
    shots = None
    if args.screenshot_prefix:
        args.screenshot_prefix.parent.mkdir(parents=True, exist_ok=True)
        shots = (str(args.screenshot_prefix) + '-bar.png', str(args.screenshot_prefix) + '-menu.png')
    result = run(args.root, dev=args.dev, shots=shots)
    print(json.dumps(result))
    if shots:
        print('Screenshots: ' + ' '.join(shots))


if __name__ == '__main__':
    main()
