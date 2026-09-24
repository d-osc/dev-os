"""Small ctypes X11 + Cairo widget toolkit for Dev OS.

Shared by the desktop shell and DPK window apps: connection helpers, a
decorated toplevel Window with title bar, drag and the minimize /
maximize / close controls, popup windows, anti-aliased Buttons and Labels
with hover/press feedback, and window capture for tests. The host must
provide libX11, libcairo and fontconfig fonts, exactly like the shell
itself. Pure-logic parts (hit testing, control zones and button state)
stay importable everywhere for unit tests.
"""
import ctypes as c
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dev_theme  # noqa: E402

TITLE_HEIGHT = 30
CONTROL_WIDTH = 26
FONT = b'DejaVu Sans'
# The shared design language of the shell: flat near-black surfaces, #111827
# chrome, #222D3D separators, a #00FF9C accent and #F1F5F9 text. Everything
# below is a plain default; set_theme() restyles it from a JSON theme file.
DEFAULT_THEME = dev_theme.resolve({'name': 'Dev OS Dark'})
PALETTE = dev_theme.gui_palette(DEFAULT_THEME)
ICONS = dict(DEFAULT_THEME['icons'])
THEME_COLORS = dict(DEFAULT_THEME['colors'])
CORNERS = dict(DEFAULT_THEME['corners'])


def set_theme(theme):
    """Apply a resolved dev_theme theme to every window drawn afterwards."""
    PALETTE.update(dev_theme.gui_palette(theme))
    ICONS.update(theme['icons'])
    THEME_COLORS.update(theme['colors'])
    CORNERS.update(theme['corners'])


def set_font(family):
    """Use this font family for all toolkit and shell text."""
    global FONT
    FONT = family.encode('ascii')


# ------------------------------------------------- pure widget/state logic

def click_completes(pressed_inside, released_inside):
    """A full click fires only when both press and release hit the widget."""
    return pressed_inside and released_inside


def rect_hit(x, y, left, top, width, height):
    return left <= x < left + width and top <= y < top + height


def control_at(x, y, width, height=TITLE_HEIGHT):
    """'min'/'max'/'close' for a title-bar point; None outside the controls."""
    if not 0 <= y < height:
        return None
    for name, start in (('close', width - 28), ('max', width - 54), ('min', width - 80)):
        if start <= x < start + CONTROL_WIDTH:
            return name
    return None


def toggle_maximize(current, screen, stashed):
    """(next geometry, stashed previous) for a maximize/restore click."""
    if stashed is None:
        return {'x': 0, 'y': 0, 'width': screen[0], 'height': screen[1]}, dict(current)
    return dict(stashed), None


def ellipsize(text, measure, max_px):
    """Shorten text to max_px with '...' using measure(text)->pixels."""
    if measure(text) <= max_px:
        return text
    while text and measure(text + '...') > max_px:
        text = text[:-1]
    return (text + '...') if text else '...'


def double_click(previous, time, x, y, gap_ms=400, distance=6):
    """True when this title-bar press repeats the previous one quickly."""
    if previous is None:
        return False
    return abs(time - previous['time']) <= gap_ms and abs(x - previous['x']) <= distance \
        and abs(y - previous['y']) <= distance


# ---------------------------------------------------------------- X11 layer

class XAny(c.Structure):
    _fields_ = [('type', c.c_int), ('serial', c.c_ulong), ('send_event', c.c_int),
                ('display', c.c_void_p), ('window', c.c_ulong)]


class XButton(c.Structure):
    _fields_ = [('type', c.c_int), ('serial', c.c_ulong), ('send_event', c.c_int),
                ('display', c.c_void_p), ('window', c.c_ulong), ('root', c.c_ulong),
                ('subwindow', c.c_ulong), ('time', c.c_ulong), ('x', c.c_int), ('y', c.c_int),
                ('x_root', c.c_int), ('y_root', c.c_int), ('state', c.c_uint),
                ('button', c.c_uint), ('same_screen', c.c_int)]


class XKey(c.Structure):
    _fields_ = [('type', c.c_int), ('serial', c.c_ulong), ('send_event', c.c_int),
                ('display', c.c_void_p), ('window', c.c_ulong), ('root', c.c_ulong),
                ('subwindow', c.c_ulong), ('time', c.c_ulong), ('x', c.c_int), ('y', c.c_int),
                ('x_root', c.c_int), ('y_root', c.c_int), ('state', c.c_uint),
                ('keycode', c.c_uint), ('same_screen', c.c_int)]


class XClient(c.Structure):
    _fields_ = [('type', c.c_int), ('serial', c.c_ulong), ('send_event', c.c_int),
                ('display', c.c_void_p), ('window', c.c_ulong), ('message_type', c.c_ulong),
                ('format', c.c_int), ('data', c.c_long * 5)]


class XEvent(c.Union):
    _fields_ = [('any', XAny), ('button', XButton), ('key', XKey), ('client', XClient),
                ('pad', c.c_long * 24)]


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
    """Bind libX11; swallow async errors through a retained handler."""
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
        'create_window': bind('XCreateWindow', c.c_ulong, c.c_void_p, c.c_ulong, c.c_int, c.c_int,
                              c.c_uint, c.c_uint, c.c_uint, c.c_int, c.c_uint, c.c_void_p,
                              c.c_ulong, c.c_void_p),
        'move_resize': bind('XMoveResizeWindow', c.c_int, c.c_void_p, c.c_ulong, c.c_int,
                            c.c_int, c.c_uint, c.c_uint),
        'move': bind('XMoveWindow', c.c_int, c.c_void_p, c.c_ulong, c.c_int, c.c_int),
        'warp': bind('XWarpPointer', None, c.c_void_p, c.c_ulong, c.c_ulong,
                     c.c_int, c.c_int, c.c_uint, c.c_uint, c.c_int, c.c_int),
        'store_name': bind('XStoreName', c.c_int, c.c_void_p, c.c_ulong, c.c_char_p),
        'select_input': bind('XSelectInput', c.c_int, c.c_void_p, c.c_ulong, c.c_long),
        'map': bind('XMapWindow', c.c_int, c.c_void_p, c.c_ulong),
        'unmap': bind('XUnmapWindow', c.c_int, c.c_void_p, c.c_ulong),
        'atom': bind('XInternAtom', c.c_ulong, c.c_void_p, c.c_char_p, c.c_int),
        'change_property': bind('XChangeProperty', c.c_int, c.c_void_p, c.c_ulong, c.c_ulong,
                                c.c_ulong, c.c_int, c.c_int, c.c_void_p, c.c_int),
        'set_protocols': bind('XSetWMProtocols', c.c_int, c.c_void_p, c.c_ulong,
                              c.POINTER(c.c_ulong), c.c_int),
        'flush': bind('XFlush', c.c_int, c.c_void_p),
        'pending': bind('XPending', c.c_int, c.c_void_p),
        'next_event': bind('XNextEvent', c.c_int, c.c_void_p, c.c_void_p),
        'sync': bind('XSync', c.c_int, c.c_void_p, c.c_int),
        'free': bind('XFree', c.c_int, c.c_void_p),
        'default_visual': bind('XDefaultVisual', c.c_void_p, c.c_void_p, c.c_int),
        'match_visual': bind('XMatchVisualInfo', c.c_int, c.c_void_p, c.c_int, c.c_int, c.c_int,
                             c.POINTER(VisualInfo)),
        'create_colormap': bind('XCreateColormap', c.c_ulong, c.c_void_p, c.c_ulong,
                                c.c_void_p, c.c_int),
        'get_image': bind('XGetImage', c.c_void_p, c.c_void_p, c.c_ulong, c.c_int, c.c_int,
                          c.c_uint, c.c_uint, c.c_ulong, c.c_int),
        'fetch_name': bind('XFetchName', c.c_int, c.c_void_p, c.c_ulong, c.POINTER(c.c_char_p)),
        'get_property': bind('XGetWindowProperty', c.c_int, c.c_void_p, c.c_ulong, c.c_ulong,
                             c.c_long, c.c_long, c.c_int, c.c_void_p, c.c_void_p, c.c_void_p,
                             c.c_void_p, c.c_void_p, c.POINTER(c.c_void_p)),
        'raise_window': bind('XRaiseWindow', c.c_int, c.c_void_p, c.c_ulong),
        'set_input_focus': bind('XSetInputFocus', c.c_int, c.c_void_p, c.c_ulong, c.c_int, c.c_long),
        'iconify': bind('XIconifyWindow', c.c_int, c.c_void_p, c.c_int, c.c_ulong),
        'grab_pointer': bind('XGrabPointer', c.c_int, c.c_void_p, c.c_ulong, c.c_int, c.c_uint,
                             c.c_uint, c.c_uint, c.c_ulong, c.c_long),
        'ungrab_pointer': bind('XUngrabPointer', c.c_int, c.c_void_p, c.c_long),
        'lookup_string': bind('XLookupString', c.c_int, c.c_void_p, c.c_char_p, c.c_int,
                              c.POINTER(c.c_ulong), c.c_void_p),
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
    """The slice of Cairo the toolkit needs, bound through ctypes."""

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
        self.set_rgba = bind('cairo_set_source_rgba', None, c.c_void_p, c.c_double,
                             c.c_double, c.c_double, c.c_double)
        self.paint = bind('cairo_paint', None, c.c_void_p)
        self.new_sub_path = bind('cairo_new_sub_path', None, c.c_void_p)
        self.arc = bind('cairo_arc', None, c.c_void_p, c.c_double, c.c_double, c.c_double,
                        c.c_double, c.c_double)
        self.close_path = bind('cairo_close_path', None, c.c_void_p)
        self.fill = bind('cairo_fill', None, c.c_void_p)
        self.stroke = bind('cairo_stroke', None, c.c_void_p)
        self.set_line_width = bind('cairo_set_line_width', None, c.c_void_p, c.c_double)
        self.move_to = bind('cairo_move_to', None, c.c_void_p, c.c_double, c.c_double)
        self.line_to = bind('cairo_line_to', None, c.c_void_p, c.c_double, c.c_double)
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
        self.save = bind('cairo_save', None, c.c_void_p)
        self.restore = bind('cairo_restore', None, c.c_void_p)
        self.rectangle = bind('cairo_rectangle', None, c.c_void_p, c.c_double,
                              c.c_double, c.c_double, c.c_double)
        self.clip = bind('cairo_clip', None, c.c_void_p)
        self.scale = bind('cairo_scale', None, c.c_void_p, c.c_double, c.c_double)
        self.surface_from_png = bind('cairo_image_surface_create_from_png',
                                     c.c_void_p, c.c_char_p)
        self.surface_from_data = bind('cairo_image_surface_create_for_data',
                                      c.c_void_p, c.c_void_p, c.c_int, c.c_int,
                                      c.c_int, c.c_int)
        self.image_width = bind('cairo_image_surface_get_width', c.c_int, c.c_void_p)
        self.image_height = bind('cairo_image_surface_get_height', c.c_int, c.c_void_p)
        self.set_source_surface = bind('cairo_set_source_surface', None, c.c_void_p,
                                       c.c_void_p, c.c_double, c.c_double)
        self.surface_destroy = bind('cairo_surface_destroy', None, c.c_void_p)

    def rounded(self, cr, x, y, width, height, radius):
        import math
        half = math.pi / 2
        self.new_sub_path(cr)
        if radius <= 0:
            self.move_to(cr, x, y)
            self.line_to(cr, x + width, y)
            self.line_to(cr, x + width, y + height)
            self.line_to(cr, x, y + height)
            self.close_path(cr)
            return
        self.arc(cr, x + width - radius, y + radius, radius, -half, 0)
        self.arc(cr, x + width - radius, y + height - radius, radius, 0, half)
        self.arc(cr, x + radius, y + height - radius, radius, half, 2 * half)
        self.arc(cr, x + radius, y + radius, radius, 2 * half, 3 * half)
        self.close_path(cr)

    def rounded_top(self, cr, x, y, width, height, radius):
        """A plate with rounded top corners and a flat bottom edge."""
        import math
        half = math.pi / 2
        self.new_sub_path(cr)
        if radius <= 0:
            self.move_to(cr, x, y)
            self.line_to(cr, x + width, y)
            self.line_to(cr, x + width, y + height)
            self.line_to(cr, x, y + height)
            self.close_path(cr)
            return
        self.move_to(cr, x, y + height)
        self.arc(cr, x + radius, y + radius, radius, math.pi, 3 * half)
        self.arc(cr, x + width - radius, y + radius, radius, -half, 0)
        self.line_to(cr, x + width, y + height)
        self.close_path(cr)


class Toolkit:
    """One X connection with Cairo shared by every window of a process."""

    def __init__(self):
        self.x, self.api = connect()
        self.cairo = Cairo()
        self.display = self.api['open_display'](None)
        if not self.display:
            raise SystemExit('Unable to open desktop display')
        self.width = self.api['display_width'](self.display, 0)
        self.height = self.api['display_height'](self.display, 0)
        self.root = self.api['root_window'](self.display, 0)
        self.visual = self.api['default_visual'](self.display, 0)
        self.protocols = self.api['atom'](self.display, b'WM_PROTOCOLS', 1)
        self.delete = self.api['atom'](self.display, b'WM_DELETE_WINDOW', 1)
        self._extents = TextExtents()

    def text_width(self, cr, text, size=12.0, bold=False):
        self.cairo.font_size(cr, size)
        self.cairo.font_face(cr, FONT, 0, 1 if bold else 0)
        self.cairo.text_extents(cr, text.encode('utf-8'), c.byref(self._extents))
        return self._extents.x_advance

    def text(self, cr, content, x, y, color, size=12.0, bold=False, alpha=1.0):
        self.cairo.font_size(cr, size)
        self.cairo.font_face(cr, FONT, 0, 1 if bold else 0)
        self.cairo.set_rgba(cr, *color, alpha)
        self.cairo.move_to(cr, x, y)
        self.cairo.show_text(cr, content.encode('utf-8'))


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


# -------------------------------------------------------------- widget layer

class Button:
    def __init__(self, label, left, top, width, height, callback=None, primary=False):
        self.label, self.rect = label, (left, top, width, height)
        self.callback, self.primary = callback, primary
        self.state, self.pressed_inside = 'normal', False

    def hit(self, x, y):
        return rect_hit(x, y, *self.rect)

    def motion(self, x, y):
        inside = self.hit(x, y)
        changed = (self.state == 'hover') != inside and self.state != 'pressed'
        self.state = 'hover' if inside else 'normal'
        return changed

    def press(self, x, y):
        self.pressed_inside = self.hit(x, y)
        if self.pressed_inside:
            self.state = 'pressed'
        return self.pressed_inside

    def release(self, x, y):
        fired = click_completes(self.pressed_inside, self.hit(x, y))
        self.state = 'hover' if self.hit(x, y) else 'normal'
        self.pressed_inside = False
        if fired and self.callback:
            self.callback()
        return fired

    def draw(self, tk, cr):
        left, top, width, height = self.rect
        radius = dev_theme.corner_radius(CORNERS, 'button', width, height)
        if self.primary:
            base = PALETTE['accent']
            fill = {'normal': 0.92, 'hover': 1.0, 'pressed': 0.70}[self.state]
            tk.cairo.set_rgba(cr, *base, fill)
            tk.cairo.rounded(cr, left, top, width, height, radius)
            tk.cairo.fill(cr)
            tk.text(cr, self.label, left + width / 2 - tk.text_width(cr, self.label, 10.5, True) / 2,
                    top + height / 2 + 4, PALETTE['accent_dark'], 10.5, True)
        else:
            alpha = {'normal': 0.10, 'hover': 0.22, 'pressed': 0.06}[self.state]
            tk.cairo.set_rgba(cr, 1.0, 1.0, 1.0, alpha)
            tk.cairo.rounded(cr, left, top, width, height, radius)
            tk.cairo.fill(cr)
            tk.cairo.set_rgba(cr, 1.0, 1.0, 1.0, 0.16)
            tk.cairo.set_line_width(cr, 1)
            tk.cairo.rounded(cr, left + 0.5, top + 0.5, width - 1, height - 1,
                             max(0.0, radius - 0.5))
            tk.cairo.stroke(cr)
            tk.text(cr, self.label, left + width / 2 - tk.text_width(cr, self.label, 10.5) / 2,
                    top + height / 2 + 4, PALETTE['text'], 10.5)


class Label:
    def __init__(self, text, x, y, size=12.0, color='text', bold=False):
        self.text, self.x, self.y = text, x, y
        self.size, self.bold = size, bold
        self.color = PALETTE[color] if isinstance(color, str) else color

    def draw(self, tk, cr):
        tk.text(cr, self.text, self.x, self.y, self.color, self.size, self.bold)


KEYSYM_RETURN, KEYSYM_BACKSPACE, KEYSYM_ESCAPE = 0xFF0D, 0xFF08, 0xFF1B


# Thai Kedmanee layout over a US keyboard: the ASCII character
# XLookupString reports for each key maps to the Thai character engraved
# on that key. The base layer keys on the lowercase ASCII character and
# the shift layer on the uppercase one.
THAI_KEDMANEE = {
    '`': '\u0e4f', '1': '\u0e45', '2': '/', '3': '-', '4': '\u0e20',
    '5': '\u0e16', '6': '\u0e38', '7': '\u0e36', '8': '\u0e04',
    '9': '\u0e15', '0': '\u0e08', '-': '\u0e02', '=': '\u0e0a',
    'q': '\u0e46', 'w': '\u0e44', 'e': '\u0e33', 'r': '\u0e1e',
    't': '\u0e30', 'y': '\u0e31', 'u': '\u0e35', 'i': '\u0e23',
    'o': '\u0e19', 'p': '\u0e22', '[': '\u0e1a', ']': '\u0e25',
    'a': '\u0e1f', 's': '\u0e2b', 'd': '\u0e01', 'f': '\u0e14',
    'g': '\u0e49', 'h': '\u0e48', 'j': '\u0e32', 'k': '\u0e2a',
    'l': '\u0e27', ';': '\u0e07', "'": '\u0e07', 'z': '\u0e1a',
    'x': '\u0e1b', 'c': '\u0e41', 'v': '\u0e2d', 'b': '\u0e34',
    'n': '\u0e37', 'm': '\u0e17', ',': '\u0e21', '.': '\u0e43',
    '/': '\u0e1d', '\\': '\u0e03',
}
THAI_KEDMANEE_SHIFT = {
    '#': '\u0e53', '$': '\u0e54', '%': '\u0e55', '^': '\u0e56',
    '&': '\u0e57', '*': '\u0e58', '(': '\u0e59', '_': '\u0e4f',
    '+': '\u0e4a', '"': '\u0e0b', '?': '\u0e0c', '>': '\u0e0e',
    '<': '\u0e11', '{': '\u0e24', '}': '\u0e26', ':': '\u0e4d',
    'Q': '\u0e50', 'W': '\u0e0b', 'E': '\u0e11', 'R': '\u0e18',
    'T': '\u0e4a', 'Y': '\u0e13', 'U': '\u0e0c', 'I': '\u0e4f',
    'O': '\u0e42', 'P': '\u0e0b', 'A': '\u0e24', 'S': '\u0e0b',
    'D': '\u0e0c', 'F': '\u0e26', 'G': '\u0e4d', 'H': '\u0e4a',
    '~': '\u0e4f',
}


def thai_char(character):
    """The Kedmanee character for one ASCII input character, or None."""
    if character in THAI_KEDMANEE:
        return THAI_KEDMANEE[character]
    if character.isupper():
        return THAI_KEDMANEE_SHIFT.get(character)
    if character.isalpha():
        return THAI_KEDMANEE.get(character.lower())
    return THAI_KEDMANEE_SHIFT.get(character)


class Entry:
    """A single-line text field with focus, masking and keyboard feeding.

    feed(keysym, char) takes one KeyPress (as XLookupString reports it) and
    returns None, 'submit' for Enter or 'clear' for Escape; the rest of the
    entry state — text, caret, mask — is plain data for unit tests.
    """

    LIMIT = 64

    def __init__(self, x, y, width, height, label='', placeholder='',
                 masked=False, thai=False):
        self.rect = (x, y, width, height)
        self.label, self.placeholder, self.masked = label, placeholder, masked
        self.thai = thai
        self.text, self.focused = '', False

    def hit(self, x, y):
        return rect_hit(x, y, *self.rect)

    def feed(self, keysym, char):
        if keysym == KEYSYM_RETURN:
            return 'submit'
        if keysym == KEYSYM_ESCAPE:
            self.text = ''
            return 'clear'
        if keysym == KEYSYM_BACKSPACE:
            self.text = self.text[:-1]
            return None
        if char and 32 <= ord(char) < 127 and len(self.text) < self.LIMIT:
            if self.thai:
                mapped = thai_char(char)
                if mapped:
                    self.text += mapped
            else:
                self.text += char
        return None

    def display_text(self):
        if self.masked:
            return '*' * len(self.text)
        return self.text or self.placeholder

    def draw(self, tk, cr):
        left, top, width, height = self.rect
        cairo = tk.cairo
        if self.label:
            tk.text(cr, self.label, left, top - 6, PALETTE['dim'], 10.0, True)
        radius = dev_theme.corner_radius(CORNERS, 'button', width, height)
        cairo.set_rgba(cr, *PALETTE['bg'], 1.0)
        cairo.rounded(cr, left, top, width, height, radius)
        cairo.fill(cr)
        border = PALETTE['accent'] if self.focused else PALETTE['line']
        cairo.set_rgba(cr, *border, 1.0)
        cairo.set_line_width(cr, 1.2)
        cairo.rounded(cr, left + 0.6, top + 0.6, width - 1.2, height - 1.2,
                      max(0.0, radius - 0.6))
        cairo.stroke(cr)
        shown = self.display_text()
        color = PALETTE['text'] if self.text or not self.placeholder else PALETTE['dim']
        tk.text(cr, shown, left + 12, top + height / 2 + 4.5, color, 13.0)
        if self.focused:
            caret = left + 14 + tk.text_width(cr, shown, 13.0)
            cairo.set_rgba(cr, *PALETTE['accent'], 1.0)
            cairo.set_line_width(cr, 1.4)
            cairo.new_sub_path(cr)
            cairo.move_to(cr, caret, top + 7)
            cairo.line_to(cr, caret, top + height - 7)
            cairo.stroke(cr)


class Window:
    """A Cairo-drawn window: decorated toplevel, dock or popup."""

    def __init__(self, toolkit, width, height, *, title='', kind='toplevel', x=80, y=80):
        self.tk = toolkit
        self.kind, self.title = kind, title
        self.width, self.height, self.x, self.y = width, height, x, y
        api, display = toolkit.api, toolkit.display
        if kind == 'popup':
            info = VisualInfo()
            argb = api['match_visual'](display, 0, 32, 4, c.byref(info))
            if argb:
                colormap = api['create_colormap'](display, toolkit.root, info.visual, 0)
                attributes = SetWindowAttributes(border_pixel=0, colormap=colormap,
                                                 override_redirect=1, event_mask=1 << 15)
                self.window = api['create_window'](display, toolkit.root, x, y, width, height,
                                                   0, 32, 1, info.visual,
                                                   1 | 2 | 0x400 | 0x800, c.byref(attributes))
                self.visual = info.visual
            else:
                self.window = api['create'](display, toolkit.root, x, y, width, height, 1,
                                            0x111827, 0x111827)
                self.visual = toolkit.visual
        else:
            self.window = api['create'](display, toolkit.root, x, y, width, height, 1,
                                        0x0b0f16, 0x0b0f16)
            self.visual = toolkit.visual
        api['store_name'](display, self.window, title.encode('utf-8'))
        delete = c.c_ulong(toolkit.delete)
        api['set_protocols'](display, self.window, c.byref(delete), 1)
        api['select_input'](display, self.window,
                            (1 << 15) | (1 << 2) | (1 << 3) | (1 << 6))
        self.surface = None
        self.cr = None
        self.buttons, self.labels, self.entries = [], [], []
        self.draw_callback = None
        self.on_close = None
        self.on_click = None      # (x, y) presses that hit no widget
        self.on_key = None        # (keysym, char, modifiers) key presses
        self._drag = None
        self._control_hover = None
        self._stashed = None
        self._last_title_press = None
        self._dirty = True
        self._surface_for(width, height)

    def _surface_for(self, width, height):
        if self.surface is None:
            self.surface = self.tk.cairo.surface_create(self.tk.display, self.window,
                                                       self.visual, width, height)
            self.cr = self.tk.cairo.create(self.surface)
        else:
            self.tk.cairo.surface_set_size(self.surface, width, height)
        return self.cr

    def resize(self, width, height):
        self.width, self.height = width, height
        self.tk.api['move_resize'](self.tk.display, self.window, self.x, self.y, width, height)
        self._surface_for(width, height)
        self._dirty = True

    def place(self, x, y, width, height):
        """Move and resize in one step (used by the maximize toggle)."""
        self.x, self.y, self.width, self.height = x, y, width, height
        self.tk.api['move_resize'](self.tk.display, self.window, x, y, width, height)
        self._surface_for(width, height)
        self._dirty = True

    def _control(self, x, y):
        return control_at(x, y, self.width) if self.kind == 'toplevel' else None

    def _minimize(self):
        if not self.tk.api['iconify'](self.tk.display, 0, self.window):
            # No window manager to iconify through: hide the window instead.
            self.tk.api['unmap'](self.tk.display, self.window)

    def _maximize(self):
        current = {'x': self.x, 'y': self.y, 'width': self.width, 'height': self.height}
        target, stashed = toggle_maximize(current, (self.tk.width, self.tk.height),
                                          self._stashed)
        self._stashed = stashed
        self.place(target['x'], target['y'], target['width'], target['height'])

    def add_button(self, label, left, top, width, height, callback=None, primary=False):
        button = Button(label, left, top, width, height, callback, primary)
        self.buttons.append(button)
        return button

    def add_label(self, *args, **keywords):
        self.labels.append(Label(*args, **keywords))
        return self.labels[-1]

    def add_entry(self, *args, **keywords):
        entry = Entry(*args, **keywords)
        self.entries.append(entry)
        return entry

    def client_top(self):
        return TITLE_HEIGHT if self.kind == 'toplevel' else 0

    def draw(self):
        cr, tk, cairo = self.cr, self.tk, self.tk.cairo
        w, h = self.width, self.height
        cairo.set_rgba(cr, *PALETTE['bg'], 1.0)
        cairo.paint(cr)
        if self.kind == 'toplevel':
            # Flat title plate closed by a separator hairline, the green >_
            # prompt mark, the title, and a close glyph that reddens on hover.
            cairo.set_rgba(cr, *PALETTE['chrome'], 1.0)
            cairo.rounded_top(cr, 0, 0, w, TITLE_HEIGHT,
                              dev_theme.corner_radius(CORNERS, 'window', w, TITLE_HEIGHT))
            cairo.fill(cr)
            cairo.set_rgba(cr, *PALETTE['line'], 1.0)
            cairo.set_line_width(cr, 1)
            cairo.new_sub_path(cr)
            cairo.line_to(cr, 0.5, TITLE_HEIGHT - 0.5)
            cairo.line_to(cr, w - 0.5, TITLE_HEIGHT - 0.5)
            cairo.stroke(cr)
            dev_theme.draw_icon(cairo, cr, ICONS['mark'], 0, 0, PALETTE['accent'],
                                 THEME_COLORS, 1.5)
            title = ellipsize(self.title, lambda s: tk.text_width(cr, s, 12.0, True), w - 120)
            tk.text(cr, title, 28, TITLE_HEIGHT - 9, PALETTE['text'], 12.0, True)
            # Window controls at the right: - (minimize), square (maximize or
            # restore), x (close). Gray at rest, lit on hover; close reddens.
            names = {'min': 'minimize', 'max': 'maximize', 'close': 'close'}
            for name, cx in (('min', w - 67), ('max', w - 41), ('close', w - 15)):
                hovered = self._control_hover == name
                color = PALETTE['dim']
                if hovered:
                    color = PALETTE['red'] if name == 'close' else PALETTE['text']
                    tint = PALETTE['red'] if name == 'close' else (1.0, 1.0, 1.0)
                    cairo.set_rgba(cr, *tint, 0.14)
                    cairo.rounded(cr, cx - 12, 3, 24, 24,
                                  dev_theme.corner_radius(CORNERS, 'icon', 24, 24))
                    cairo.fill(cr)
                icon = ICONS['restore'] if name == 'max' and self._stashed is not None \
                    else ICONS[names[name]]
                dev_theme.draw_icon(cairo, cr, icon, cx - 13, 0, color, THEME_COLORS, 1.5)
        if self.draw_callback:
            self.draw_callback(self)
        for label in self.labels:
            label.draw(tk, cr)
        for entry in self.entries:
            entry.draw(tk, cr)
        for button in self.buttons:
            button.draw(tk, cr)
        cairo.set_rgba(cr, *PALETTE['line'], 1.0)
        cairo.set_line_width(cr, 1)
        cairo.rounded(cr, 0.5, 0.5, w - 1, h - 1,
                      dev_theme.corner_radius(CORNERS, 'window', w, h))
        cairo.stroke(cr)
        cairo.surface_flush(self.surface)
        tk.api['flush'](tk.display)
        self._dirty = False

    def _in_close(self, x, y):
        return self._control(x, y) == 'close'

    def capture(self, path, width=None, height=None):
        """Self-capture; waits out the compositor and redraws, per XWayland."""
        import dev_gui
        self.draw()
        api = self.tk.api
        api['sync'](self.tk.display, 0)
        time.sleep(0.6)
        api['sync'](self.tk.display, 0)
        self.draw()
        api['sync'](self.tk.display, 0)
        pointer = api['get_image'](self.tk.display, self.window, 0, 0,
                                   width or self.width, height or self.height, 0xFFFFFFFF, 2)
        if not pointer:
            raise SystemExit('Could not capture the window')
        try:
            rows = decode_rows(XImage.from_address(pointer))
            dev_gui.write_png(path, width or self.width, height or self.height, rows)
        finally:
            self.tk.x.XFree(pointer)

    def close(self):
        self.tk.api['unmap'](self.tk.display, self.window)
        self.open_ = False

    open_ = False

    def show(self):
        self.tk.api['map'](self.tk.display, self.window)
        self.open_ = True

    def run(self, *, tick=None, interval=1.0, close_after=None, on_tick_capture=None):
        """Event loop: hover feedback, drag-to-move, clicks, close button."""
        api, cairo = self.tk.api, self.tk.cairo
        started, last_tick = time.monotonic(), 0.0
        while self.open_:
            while api['pending'](self.tk.display):
                event = XEvent()
                api['next_event'](self.tk.display, c.byref(event))
                kind = event.any.type
                if (kind == 33 and event.client.message_type == self.tk.protocols
                        and event.client.data[0] == self.tk.delete):
                    self.open_ = False
                    if self.on_close:
                        self.on_close()
                elif kind == 2:
                    if event.key.window == self.window and not self._drag:
                        keysym = c.c_ulong()
                        buffer = c.create_string_buffer(16)
                        self.tk.api['lookup_string'](c.byref(event.key), buffer, 16,
                                                     c.byref(keysym), None)
                        character = buffer.value.decode('ascii', 'ignore')[:1]
                        handled = False
                        if self.on_key:
                            self.on_key(keysym.value, character, event.key.state)
                            handled = True
                        for item in self.entries:
                            if item.focused and not handled:
                                item.feed(keysym.value, character)
                        self._dirty = True
                elif kind in (4, 5, 6):
                    button_event = event.button
                    if button_event.window != self.window:
                        continue
                    x, y = button_event.x, button_event.y
                    if kind == 6:
                        control = self._control(x, y)
                        if control != self._control_hover:
                            self._control_hover, self._dirty = control, True
                        for item in self.buttons:
                            if item.motion(x, y):
                                self._dirty = True
                        if self._drag and button_event.state & 0x100:
                            self.x, self.y = self.x + x - self._drag[0], self.y + y - self._drag[1]
                            self._drag = (x, y)
                            api['move'](self.tk.display, self.window, self.x, self.y)
                    elif kind == 4:
                        control = self._control(x, y)
                        if control == 'close':
                            self.open_ = False
                            if self.on_close:
                                self.on_close()
                            continue
                        if control == 'min':
                            self._minimize()
                            continue
                        if control == 'max':
                            self._maximize()
                            continue
                        if self.kind == 'toplevel' and y < TITLE_HEIGHT:
                            press = {'time': event.button.time, 'x': x, 'y': y}
                            if double_click(self._last_title_press, press['time'], x, y):
                                self._last_title_press = None
                                self._drag = None
                                self._maximize()
                            else:
                                self._last_title_press = press
                                self._drag = (x, y)
                        for item in self.entries:
                            item.focused = item.hit(x, y)
                        for item in self.buttons:
                            item.press(x, y)
                        if self.on_click and not self._drag:
                            self.on_click(x, y)
                    elif kind == 5:
                        self._drag = None
                        for item in self.buttons:
                            if item.release(x, y):
                                self._dirty = True
                    self._dirty = True
            now = time.monotonic()
            if tick and now - last_tick >= interval:
                last_tick = now
                tick(self)
                self._dirty = True
            if self._dirty:
                self.draw()
            if close_after and now - started >= close_after:
                self.open_ = False
            if on_tick_capture and now - started >= on_tick_capture[0]:
                self.capture(on_tick_capture[1])
                self.open_ = False
            time.sleep(0.02)


def write_png(path, width, height, rgb_rows):
    """Write RGB rows (each width*3 bytes) as a PNG file."""
    import zlib
    from pathlib import Path
    import struct

    def chunk(tag, data):
        block = tag + data
        return struct.pack('>I', len(data)) + block + struct.pack('>I', zlib.crc32(block))

    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    raw = b''.join(b'\x00' + bytes(row) for row in rgb_rows)
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) +
                           chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))
