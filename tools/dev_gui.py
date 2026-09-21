"""Small ctypes X11 + Cairo widget toolkit for Dev OS.

Shared by the desktop shell and DPK window apps: connection helpers, a
decorated toplevel Window with title bar, drag and close, popup windows,
anti-aliased Buttons and Labels with hover/press feedback, and window
capture for tests. The host must provide libX11, libcairo and fontconfig
fonts, exactly like the shell itself. Pure-logic parts (hit testing and
button state) stay importable everywhere for unit tests.
"""
import ctypes as c
import time

TITLE_HEIGHT = 30
RADIUS = 10
BUTTON_RADIUS = 8
FONT = b'DejaVu Sans'
PALETTE = {'bg': (0.055, 0.094, 0.161), 'chrome': (0.078, 0.125, 0.204),
           'chrome_low': (0.043, 0.078, 0.133), 'text': (0.898, 0.929, 0.973),
           'dim': (0.576, 0.655, 0.769), 'accent': (0.398, 0.878, 0.749),
           'accent_dark': (0.051, 0.086, 0.149),
           'bar_low': (0.043, 0.082, 0.149), 'bar_high': (0.094, 0.153, 0.251),
           'panel': (0.051, 0.086, 0.149)}


# ------------------------------------------------- pure widget/state logic

def click_completes(pressed_inside, released_inside):
    """A full click fires only when both press and release hit the widget."""
    return pressed_inside and released_inside


def rect_hit(x, y, left, top, width, height):
    return left <= x < left + width and top <= y < top + height


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
        'grab_pointer': bind('XGrabPointer', c.c_int, c.c_void_p, c.c_ulong, c.c_int, c.c_uint,
                             c.c_uint, c.c_uint, c.c_ulong, c.c_long),
        'ungrab_pointer': bind('XUngrabPointer', c.c_int, c.c_void_p, c.c_long),
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

    def rounded(self, cr, x, y, width, height, radius):
        import math
        half = math.pi / 2
        self.new_sub_path(cr)
        self.arc(cr, x + width - radius, y + radius, radius, -half, 0)
        self.arc(cr, x + width - radius, y + height - radius, radius, 0, half)
        self.arc(cr, x + radius, y + height - radius, radius, half, 2 * half)
        self.arc(cr, x + radius, y + radius, radius, 2 * half, 3 * half)
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
        if self.primary:
            base = PALETTE['accent']
            fill = {'normal': 0.92, 'hover': 1.0, 'pressed': 0.70}[self.state]
            tk.cairo.set_rgba(cr, *base, fill)
            tk.cairo.rounded(cr, left, top, width, height, BUTTON_RADIUS)
            tk.cairo.fill(cr)
            tk.text(cr, self.label, left + width / 2 - tk.text_width(cr, self.label, 10.5, True) / 2,
                    top + height / 2 + 4, PALETTE['accent_dark'], 10.5, True)
        else:
            alpha = {'normal': 0.10, 'hover': 0.22, 'pressed': 0.06}[self.state]
            tk.cairo.set_rgba(cr, 1.0, 1.0, 1.0, alpha)
            tk.cairo.rounded(cr, left, top, width, height, BUTTON_RADIUS)
            tk.cairo.fill(cr)
            tk.cairo.set_rgba(cr, 1.0, 1.0, 1.0, 0.16)
            tk.cairo.set_line_width(cr, 1)
            tk.cairo.rounded(cr, left + 0.5, top + 0.5, width - 1, height - 1, BUTTON_RADIUS)
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
                                            0x0e1829, 0x0e1829)
                self.visual = toolkit.visual
        else:
            self.window = api['create'](display, toolkit.root, x, y, width, height, 1,
                                        0x0e1829, 0x0e1829)
            self.visual = toolkit.visual
        api['store_name'](display, self.window, title.encode('utf-8'))
        delete = c.c_ulong(toolkit.delete)
        api['set_protocols'](display, self.window, c.byref(delete), 1)
        api['select_input'](display, self.window,
                            (1 << 15) | (1 << 2) | (1 << 3) | (1 << 6))
        self.surface = None
        self.cr = None
        self.buttons, self.labels = [], []
        self.draw_callback = None
        self.on_close = None
        self._drag = None
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

    def add_button(self, label, left, top, width, height, callback=None, primary=False):
        button = Button(label, left, top, width, height, callback, primary)
        self.buttons.append(button)
        return button

    def add_label(self, *args, **keywords):
        self.labels.append(Label(*args, **keywords))
        return self.labels[-1]

    def client_top(self):
        return TITLE_HEIGHT if self.kind == 'toplevel' else 0

    def draw(self):
        cr, tk, cairo = self.cr, self.tk, self.tk.cairo
        w, h = self.width, self.height
        cairo.set_rgba(cr, *PALETTE['bg'], 1.0)
        cairo.paint(cr)
        if self.kind == 'toplevel':
            gradient = cairo.pattern_linear(cr, 0, 0, 0, TITLE_HEIGHT)
            cairo.pattern_stop(gradient, 0.0, *PALETTE['chrome_low'], 1.0)
            cairo.pattern_stop(gradient, 1.0, *PALETTE['chrome'], 1.0)
            cairo.set_source_pattern(cr, gradient)
            cairo.rounded(cr, 0, 0, w, TITLE_HEIGHT + RADIUS, RADIUS)
            cairo.fill(cr)
            cairo.set_rgba(cr, *PALETTE['accent'], 0.30)
            cairo.set_line_width(cr, 1)
            cairo.new_sub_path(cr)
            cairo.line_to(cr, 0.5, TITLE_HEIGHT - 0.5)
            cairo.line_to(cr, w - 0.5, TITLE_HEIGHT - 0.5)
            cairo.stroke(cr)
            tk.text(cr, self.title, 12, TITLE_HEIGHT - 9, PALETTE['text'], 12.0, True)
            hover = self._close_hover
            cairo.set_rgba(cr, *PALETTE['accent'], 0.9 if hover else 0.45)
            cairo.arc(cr, w - 16, TITLE_HEIGHT / 2, 7.5, 0, 6.2832)
            cairo.fill(cr)
            cairo.set_rgba(cr, *PALETTE['chrome_low'], 1.0)
            cairo.set_line_width(cr, 1.6)
            cairo.new_sub_path(cr)
            cairo.line_to(cr, w - 19.5, TITLE_HEIGHT / 2 - 3.5)
            cairo.line_to(cr, w - 12.5, TITLE_HEIGHT / 2 + 3.5)
            cairo.stroke(cr)
            cairo.new_sub_path(cr)
            cairo.line_to(cr, w - 12.5, TITLE_HEIGHT / 2 - 3.5)
            cairo.line_to(cr, w - 19.5, TITLE_HEIGHT / 2 + 3.5)
            cairo.stroke(cr)
        if self.draw_callback:
            self.draw_callback(self)
        for label in self.labels:
            label.draw(tk, cr)
        for button in self.buttons:
            button.draw(tk, cr)
        cairo.set_rgba(cr, *PALETTE['accent'], 0.25)
        cairo.set_line_width(cr, 1)
        cairo.rounded(cr, 0.5, 0.5, w - 1, h - 1, RADIUS)
        cairo.stroke(cr)
        cairo.surface_flush(self.surface)
        tk.api['flush'](self.tk.display)
        self._dirty = False

    _close_hover = False

    def _in_close(self, x, y):
        return self.kind == 'toplevel' and (self.width - 28) <= x <= (self.width - 4) \
            and 2 <= y <= TITLE_HEIGHT - 2

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
                elif kind in (4, 5, 6):
                    button_event = event.button
                    if button_event.window != self.window:
                        continue
                    x, y = button_event.x, button_event.y
                    if kind == 6:
                        hover = self._in_close(x, y)
                        if hover != self._close_hover:
                            self._close_hover, self._dirty = hover, True
                        for item in self.buttons:
                            if item.motion(x, y):
                                self._dirty = True
                        if self._drag and button_event.state & 0x100:
                            self.x, self.y = self.x + x - self._drag[0], self.y + y - self._drag[1]
                            self._drag = (x, y)
                            api['move'](self.tk.display, self.window, self.x, self.y)
                    elif kind == 4:
                        if self._in_close(x, y):
                            self.open_ = False
                            if self.on_close:
                                self.on_close()
                            continue
                        if self.kind == 'toplevel' and y < TITLE_HEIGHT:
                            self._drag = (x, y)
                        for item in self.buttons:
                            item.press(x, y)
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
