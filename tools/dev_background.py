"""Desktop backgrounds from settings.json: color, PNG, JPG, SVG or HTML.

'desktop.background' accepts 'none', a #RRGGBB color, or a file path ending
.png/.jpg/.jpeg/.svg/.html. PNG decodes through cairo itself, JPG through a
TurboJPEG binding, and SVG/HTML through small strictly-validated subsets of
our own (shapes and line paths for SVG; background color/gradient, text and
a PNG image for HTML) — no new runtime dependencies. Files are size-capped
and every failure falls back to the theme background, because a wallpaper
must never take the desktop down.
"""
import ctypes as c
import ctypes.util
import html.parser
from pathlib import Path
import re
import xml.etree.ElementTree as Tree

FILE_LIMIT = 256 * 1024
IMAGE_LIMIT = 16 * 1024 * 1024
SVG_ELEMENT_LIMIT = 512
HTML_ITEM_LIMIT = 64
COORD_LIMIT = 100000

SVG_SHAPES = ('rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon', 'path')
PATH_STEP = {'M': 2, 'L': 2, 'H': 1, 'V': 1, 'C': 6, 'Q': 4, 'S': 4, 'T': 2, 'A': 7}
NAMED = {'black': '#000000', 'white': '#ffffff', 'red': '#ff0000',
         'green': '#008000', 'blue': '#0000ff', 'yellow': '#ffff00',
         'gray': '#808080', 'grey': '#808080', 'orange': '#ffa500',
         'purple': '#800080', 'cyan': '#00ffff', 'magenta': '#ff00ff'}


def background_kind(value):
    """'none' | 'color' | 'png' | 'jpg' | 'svg' | 'html' for a setting."""
    if value in ('none', ''):
        return 'none'
    if value.startswith('#'):
        return 'color'
    suffix = Path(value).suffix.lower()
    if suffix == '.png':
        return 'png'
    if suffix in ('.jpg', '.jpeg'):
        return 'jpg'
    if suffix == '.svg':
        return 'svg'
    if suffix == '.html':
        return 'html'
    raise ValueError('Unsupported background: %s (use none, #RRGGBB or a '
                     '.png/.jpg/.svg/.html file)' % value[:64])


def parse_color(value):
    """Hex or the handful of named colors to an (r, g, b) tuple."""
    if not isinstance(value, str):
        raise ValueError('Bad color')
    value = NAMED.get(value.strip().lower(), value.strip())
    digits = value[1:] if value.startswith('#') else None
    if digits is None or len(digits) not in (3, 6) or any(
            character not in '0123456789abcdefABCDEF' for character in digits):
        raise ValueError('Bad color: %s' % value[:32])
    if len(digits) == 3:
        digits = ''.join(character * 2 for character in digits)
    return tuple(int(digits[place:place + 2], 16) / 255.0
                 for place in (0, 2, 4))


# ----------------------------------------------------------------- parsing

def _numbers(text, limit=COORD_LIMIT):
    values = []
    for piece in re.findall(r'[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?',
                            text or ''):
        number = float(piece)
        if abs(number) > limit:
            raise ValueError('SVG coordinate out of range')
        values.append(number)
    return values


def _strip_ns(tag):
    return tag.rsplit('}', 1)[-1]


def _path_points(data):
    """Vertices of the line skeleton of an SVG path (curves are skipped)."""
    tokens = re.findall(r'[MmLlHhVvCcQqSsTtAaZz]|[-+]?[0-9]*\.?[0-9]+'
                        r'(?:[eE][-+]?[0-9]+)?', data or '')
    points = []
    position = start = (0.0, 0.0)
    command = None
    pending = []
    for token in tokens:
        if token.isalpha():
            command, pending = token, []
            if command in 'Zz' and position != start:
                points.append(start)
                position = start
            continue
        pending.append(float(token))
        step = PATH_STEP[command.upper()]
        while len(pending) >= step:
            chunk, pending = pending[:step], pending[step:]
            relative = command.islower()
            x, y = chunk[0], chunk[1] if step > 1 else 0.0
            upper = command.upper()
            if upper == 'M':
                target = (position[0] + x, position[1] + y) if relative else (x, y)
                position = start = target
                points.append(target)
            elif upper == 'L':
                target = (position[0] + x, position[1] + y) if relative else (x, y)
                position = target
                points.append(target)
            elif upper == 'H':
                position = (position[0] + x, position[1])
                points.append(position)
            elif upper == 'V':
                position = (position[0], position[1] + x)
                points.append(position)
            else:                                   # curves: skip the segment
                if step > 1:
                    end = (chunk[-2], chunk[-1])
                    position = (position[0] + end[0], position[1] + end[1]) \
                        if relative else end
    if len(points) > 4096:
        raise ValueError('SVG path too complex')
    return points


def parse_svg(text):
    """A validated SVG subset -> (viewBox, shapes) for the painter."""
    if not isinstance(text, str) or len(text) > FILE_LIMIT:
        raise ValueError('SVG file exceeds %d bytes' % FILE_LIMIT)
    root = Tree.fromstring(text)
    if _strip_ns(root.tag) != 'svg':
        raise ValueError('Not an SVG document')
    view = _numbers(root.get('viewBox', ''))
    if len(view) != 4 or view[2] <= 0 or view[3] <= 0:
        view = [0.0, 0.0, 1000.0, 1000.0]
    shapes = []

    def walk(element, fill, stroke, stroke_width):
        for child in element:
            tag = _strip_ns(child.tag)
            if len(shapes) > SVG_ELEMENT_LIMIT:
                raise ValueError('Too many SVG elements')
            if tag == 'g':
                walk(child,
                     parse_color(child.get('fill')) if child.get('fill', '').startswith('#')
                     or child.get('fill', '').lower() in NAMED else fill,
                     stroke, stroke_width)
                continue
            if tag not in SVG_SHAPES:
                continue
            raw_fill = child.get('fill', fill)
            raw_stroke = child.get('stroke', stroke)
            try:
                width = float(_numbers(child.get('stroke-width', stroke_width))[0])
            except (ValueError, IndexError):
                width = 1.0
            fill_color = None if raw_fill in (None, 'none') else parse_color(raw_fill)
            stroke_color = None if raw_stroke in (None, 'none') else parse_color(raw_stroke)
            numbers = _numbers(' '.join(
                child.get(name, '') for name in ('x', 'y', 'width', 'height',
                                                 'rx', 'ry', 'cx', 'cy', 'r',
                                                 'x1', 'y1', 'x2', 'y2')))
            points = [pair for pair in zip(_numbers(child.get('points', ''))[::2],
                                           _numbers(child.get('points', ''))[1::2])]
            if tag == 'path':
                shapes.append(('polyline', _path_points(child.get('d', '')),
                               fill_color, stroke_color, width))
            elif tag in ('polyline', 'polygon'):
                if tag == 'polygon' and points:
                    points = points + [points[0]]
                shapes.append(('polyline', points, fill_color, stroke_color, width))
            elif tag in ('circle', 'ellipse'):
                shapes.append((tag, numbers, fill_color, stroke_color, width))
            else:
                shapes.append((tag, numbers, fill_color, stroke_color, width))

    walk(root, '#000000', 'none', '1')
    return view, shapes


class _HtmlWallpaper(html.parser.HTMLParser):
    """HTML wallpapers: background(-color), linear-gradient, text, image."""

    TEXT_TAGS = ('h1', 'h2', 'h3', 'p')

    def __init__(self):
        super().__init__()
        self.background = ('color', (0.043, 0.059, 0.086))
        self.items = []
        self._text = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in ('body', 'div') and 'style' in attributes:
            self._style_background(attributes['style'])
        elif tag in self.TEXT_TAGS and 'style' in attributes:
            self._text = {'text': '', 'x': 40.0, 'y': 120.0, 'size': 48.0,
                          'bold': False, 'color': (0.9, 0.9, 0.9)}
            self._style_text(attributes['style'])
        elif tag == 'img':
            source = attributes.get('src', '')
            if len(self.items) < HTML_ITEM_LIMIT and re.fullmatch(
                    r'[A-Za-z0-9._/-]{1,128}', source):
                self.items.append(('image', source))

    def handle_endtag(self, tag):
        if self._text is not None and tag in self.TEXT_TAGS:
            text = self._text['text'].strip()[:80]
            if text and len(self.items) < HTML_ITEM_LIMIT:
                self.items.append(('text', text, self._text['x'], self._text['y'],
                                   self._text['size'], self._text['bold'],
                                   self._text['color']))
            self._text = None

    def handle_data(self, data):
        if self._text is not None:
            self._text['text'] += data

    def _style_background(self, style):
        for declaration in style.split(';'):
            name, _, value = declaration.partition(':')
            name, value = name.strip().lower(), value.strip()
            try:
                if name == 'background-color':
                    self.background = ('color', parse_color(value))
                elif name == 'background' and 'linear-gradient' in value:
                    colors = [parse_color(piece) for piece in
                              value.split('(', 1)[1].rstrip(')').split(',')]
                    if len(colors) == 2:
                        self.background = ('gradient', tuple(colors))
            except ValueError:
                continue

    def _style_text(self, style):
        for declaration in style.split(';'):
            name, _, value = declaration.partition(':')
            name, value = name.strip().lower(), value.strip()
            try:
                if name in ('left', 'top'):
                    self._text['x' if name == 'left' else 'y'] = \
                        float(_numbers(value)[0])
                elif name == 'font-size':
                    self._text['size'] = float(_numbers(value)[0])
                elif name == 'font-weight':
                    self._text['bold'] = value in ('bold', '700', '800', '900')
                elif name == 'color':
                    self._text['color'] = parse_color(value)
            except (ValueError, IndexError):
                continue


def parse_html(text):
    if not isinstance(text, str) or len(text) > FILE_LIMIT:
        raise ValueError('HTML file exceeds %d bytes' % FILE_LIMIT)
    parser = _HtmlWallpaper()
    parser.feed(text)
    return parser.background, parser.items


# ---------------------------------------------------------------- rendering

def _cover(source_w, source_h, width, height):
    scale = max(width / max(source_w, 1.0), height / max(source_h, 1.0))
    return scale, (width - source_w * scale) / 2, (height - source_h * scale) / 2


class _Pinned:
    """Keep decoded image bytes referenced while cairo may read them."""

    def __init__(self, buffer, surface):
        self.buffer, self.surface = buffer, surface


_PINNED = []


def _jpeg_surface(cairo, path):
    turbo = None
    for name in ('libturbojpeg.so.0', 'libturbojpeg.so'):
        try:
            turbo = c.CDLL(name)
            break
        except OSError:
            continue
    if turbo is None:
        found = ctypes.util.find_library('turbojpeg')
        if not found:
            raise ValueError('libturbojpeg is not available for JPG backgrounds')
        turbo = c.CDLL(found)
    data = path.read_bytes()
    if len(data) > IMAGE_LIMIT:
        raise ValueError('Image exceeds %d bytes' % IMAGE_LIMIT)
    header = getattr(turbo, 'tjDecompressHeader3', None)
    if header is None:
        raise ValueError('libturbojpeg lacks tjDecompressHeader3')
    header.restype = c.c_int
    header.argtypes = [c.c_void_p, c.c_char_p, c.c_ulong, c.POINTER(c.c_int),
                       c.POINTER(c.c_int), c.POINTER(c.c_int), c.POINTER(c.c_int)]
    decompress = turbo.tjDecompress2
    decompress.restype = c.c_int
    decompress.argtypes = [c.c_void_p, c.c_char_p, c.c_ulong, c.c_void_p, c.c_int,
                           c.c_int, c.c_int, c.c_int, c.c_int]
    handle = turbo.tjInitDecompress()
    if not handle:
        raise ValueError('turbojpeg init failed')
    try:
        width, height, pixel, colorspace = (c.c_int(), c.c_int(), c.c_int(),
                                            c.c_int())
        if header(handle, data, len(data), c.byref(width), c.byref(height),
                  c.byref(pixel), c.byref(colorspace)) != 0 \
                or not 0 < width.value * height.value <= 4096 * 4096:
            raise ValueError('turbojpeg could not read the JPG header')
        stride = width.value * 4                       # cairo FORMAT_RGB24
        buffer = (c.c_ubyte * (stride * height.value))()
        if decompress(handle, data, len(data), buffer, width.value, stride,
                      height.value, 3, 0) != 0:         # TJPF_BGRX byte order
            raise ValueError('turbojpeg could not decode the JPG')
        surface = cairo.surface_from_data(buffer, 1, width.value,
                                          height.value, stride)
        if not surface:
            raise ValueError('cairo rejected the decoded JPG')
        _PINNED.append(_Pinned(buffer, surface))
        del _PINNED[:-8]
        return surface
    finally:
        turbo.tjDestroy(handle)


def _image_surface(cairo, path, kind):
    if path.stat().st_size > IMAGE_LIMIT:
        raise ValueError('Image exceeds %d bytes' % IMAGE_LIMIT)
    if kind == 'png':
        surface = cairo.surface_from_png(str(path).encode())
        if not surface:
            raise ValueError('cairo could not decode the PNG')
        return surface
    return _jpeg_surface(cairo, path)


def _paint_image(cairo, cr, surface, width, height, x=0.0, y=0.0):
    try:
        scale, dx, dy = _cover(cairo.image_width(surface),
                               cairo.image_height(surface), width, height)
        cairo.save(cr)
        cairo.scale(cr, scale, scale)
        cairo.set_source_surface(cr, surface, (x + dx) / scale, (y + dy) / scale)
        cairo.paint(cr)
        cairo.restore(cr)
    finally:
        cairo.surface_destroy(surface)


def _paint_svg(cairo, cr, width, height, view, shapes):
    scale = max(width / view[2], height / view[3])
    offset_x = (width - view[2] * scale) / 2 - view[0] * scale
    offset_y = (height - view[3] * scale) / 2 - view[1] * scale

    def point(x, y):
        return offset_x + x * scale, offset_y + y * scale

    for tag, data, fill, stroke, stroke_width in shapes:
        numbers = points = data
        cairo.new_sub_path(cr)
        if tag == 'rect':
            if len(numbers) < 4:
                continue
            x, y = point(numbers[0], numbers[1])
            w, h = numbers[2] * scale, numbers[3] * scale
            cairo.move_to(cr, x, y)
            cairo.line_to(cr, x + w, y)
            cairo.line_to(cr, x + w, y + h)
            cairo.line_to(cr, x, y + h)
            cairo.close_path(cr)
        elif tag in ('circle', 'ellipse'):
            if len(numbers) < 3:
                continue
            cx, cy = point(numbers[0], numbers[1])
            radius = numbers[2] * scale
            cairo.arc(cr, cx, cy, radius, 0, 6.2832)
        elif tag == 'line':
            if len(numbers) < 4:
                continue
            cairo.move_to(cr, *point(numbers[0], numbers[1]))
            cairo.line_to(cr, *point(numbers[2], numbers[3]))
        else:                                          # polyline / path skeleton
            if not points:
                continue
            for index, (x, y) in enumerate(points):
                target = point(x, y)
                if index == 0:
                    cairo.move_to(cr, *target)
                else:
                    cairo.line_to(cr, *target)
        if fill is not None:
            cairo.set_rgba(cr, *fill, 1.0)
            cairo.fill(cr)
        if stroke is not None:
            cairo.set_rgba(cr, *stroke, 1.0)
            cairo.set_line_width(cr, max(stroke_width * scale, 0.5))
            cairo.stroke(cr)


def _paint_html(cairo, cr, width, height, background, items, source):
    import dev_gui
    if background[0] == 'gradient':
        (r1, g1, b1), (r2, g2, b2) = background[1]
        gradient = cairo.pattern_linear(cr, 0, 0, 0, height)
        cairo.pattern_stop(gradient, 0.0, r1, g1, b1, 1.0)
        cairo.pattern_stop(gradient, 1.0, r2, g2, b2, 1.0)
        cairo.set_source_pattern(cr, gradient)
        cairo.paint(cr)
    else:
        cairo.set_rgba(cr, *background[1], 1.0)
        cairo.paint(cr)
    base = Path(source).parent
    for item in items:
        if item[0] == 'text':
            _, text, x, y, size, bold, color = item
            cairo.font_size(cr, size)
            cairo.font_face(cr, dev_gui.FONT, 0, 1 if bold else 0)
            cairo.set_rgba(cr, *color, 1.0)
            cairo.move_to(cr, x, y)
            cairo.show_text(cr, text.encode('utf-8'))
        else:
            resolved = base / item[1]
            if resolved.suffix.lower() == '.png' and resolved.is_file():
                surface = cairo.surface_from_png(str(resolved).encode())
                if surface:
                    _paint_image(cairo, cr, surface, width, height)


def render(cairo, cr, width, height, value, fallback):
    """Paint one background value onto a full-screen context; never raises."""
    def flat(color):
        cairo.set_rgba(cr, *color, 1.0)
        cairo.paint(cr)

    try:
        kind = background_kind(value)
        if kind == 'none':
            flat(fallback)
        elif kind == 'color':
            flat(parse_color(value))
        elif kind in ('png', 'jpg'):
            _paint_image(cairo, cr, _image_surface(cairo, Path(value), kind),
                         width, height)
        elif kind == 'svg':
            view, shapes = parse_svg(Path(value).read_text())
            _paint_svg(cairo, cr, width, height, view, shapes)
        else:
            background, items = parse_html(Path(value).read_text())
            _paint_html(cairo, cr, width, height, background, items, value)
    except (OSError, ValueError, AttributeError, c.ArgumentError) as error:
        print('background %s failed: %s' % (str(value)[:48], error))
        flat(fallback)
