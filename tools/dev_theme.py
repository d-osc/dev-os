"""Color and icon themes for the Dev OS GUI, loaded from JSON files.

A theme file works like a VS Code theme: a partial overlay of named color
tokens plus optional vector icon overrides. Everything the shell and the
window toolkit draw resolves through these tokens, so one file restyles
the whole desktop. Theme files are untrusted input: they are size-capped,
strictly validated and merged over the built-in defaults, and nothing but
colors and icon geometry can come out of them.
"""
import json
import math
from pathlib import Path

LIMIT = 65536
COLOR_TOKENS = ('bg', 'chrome', 'line', 'text', 'dim', 'accent', 'accentText', 'blue', 'red')
CORNER_TOKENS = ('window', 'button', 'menu', 'row', 'chip', 'start', 'icon')
ICON_NAMES = ('start', 'mark', 'wifi', 'volume', 'bell',
              'minimize', 'maximize', 'restore', 'close')
ICON_KINDS = ('line', 'poly', 'rect', 'circle', 'arc')

# The default look of Dev OS: flat near-black surfaces, #111827 chrome,
# #222D3D separators, a #00FF9C accent and #F1F5F9 text.
DEFAULT_COLORS = {'bg': '#0b0f16', 'chrome': '#111827', 'line': '#222D3D',
                  'text': '#F1F5F9', 'dim': '#6F8098', 'accent': '#00FF9C',
                  'accentText': '#0b0f16', 'blue': '#00AAFF', 'red': '#FF4444'}

# Corner radii in pixels; 0 draws square corners. Defaults preserve the
# classic look, so a theme only names the tokens it wants to change.
DEFAULT_CORNERS = {'window': 10, 'button': 8, 'menu': 12, 'row': 8,
                   'chip': 11, 'start': 6, 'icon': 6}

# Icons live in their own view boxes and are drawn one-to-one; each element
# inherits the caller's color unless it names a token.
DEFAULT_ICONS = {
    'start': {'view': [100, 26], 'elements': [
        {'kind': 'poly', 'points': [[18, 15.8], [25.4, 20.3], [18, 24.9]], 'width': 2.2},
        {'kind': 'rect', 'x': 27.5, 'y': 26.1, 'w': 7.8, 'h': 2.3, 'fill': True},
    ]},
    'mark': {'view': [30, 30], 'elements': [
        {'kind': 'poly', 'points': [[12, 11.5], [16, 15], [12, 18.5]], 'width': 1.6},
        {'kind': 'rect', 'x': 18, 'y': 18.6, 'w': 3.5, 'h': 1.5, 'fill': True},
    ]},
    'wifi': {'view': [16, 16], 'elements': [
        {'kind': 'arc', 'cx': 8, 'cy': 11, 'r': 3.2, 'from': -135, 'to': -45},
        {'kind': 'arc', 'cx': 8, 'cy': 11, 'r': 6.4, 'from': -140, 'to': -40},
        {'kind': 'circle', 'cx': 8, 'cy': 11, 'r': 1.2, 'fill': True},
    ]},
    'volume': {'view': [20, 16], 'elements': [
        {'kind': 'poly',
         'points': [[2, 6], [5, 6], [8.5, 2.5], [8.5, 13.5], [5, 10], [2, 10]], 'fill': True},
        {'kind': 'arc', 'cx': 9.5, 'cy': 8, 'r': 4.5, 'from': -49, 'to': 49},
    ]},
    'bell': {'view': [16, 16], 'elements': [
        {'kind': 'arc', 'cx': 8, 'cy': 7.5, 'r': 3.8, 'from': 180, 'to': 360,
         'lines': [[12.2, 10.5], [3.8, 10.5]], 'closed': True, 'fill': True},
        {'kind': 'arc', 'cx': 8, 'cy': 10.5, 'r': 2, 'from': 0, 'to': 180},
        {'kind': 'circle', 'cx': 12.5, 'cy': 3.5, 'r': 2.6, 'color': 'red', 'fill': True},
    ]},
    'minimize': {'view': [26, 30], 'elements': [
        {'kind': 'line', 'x1': 8, 'y1': 18.5, 'x2': 18, 'y2': 18.5, 'width': 2.0},
    ]},
    'maximize': {'view': [26, 30], 'elements': [
        {'kind': 'rect', 'x': 8.5, 'y': 10.5, 'w': 9, 'h': 9, 'r': 1.5, 'width': 1.8},
    ]},
    'restore': {'view': [26, 30], 'elements': [
        {'kind': 'rect', 'x': 11, 'y': 9, 'w': 8, 'h': 8, 'r': 1.5, 'width': 1.8},
        {'kind': 'rect', 'x': 7, 'y': 13, 'w': 8, 'h': 8, 'r': 1.5,
         'color': 'chrome', 'fill': True},
        {'kind': 'rect', 'x': 7, 'y': 13, 'w': 8, 'h': 8, 'r': 1.5, 'width': 1.8},
    ]},
    'close': {'view': [26, 30], 'elements': [
        {'kind': 'line', 'x1': 9.5, 'y1': 11.5, 'x2': 16.5, 'y2': 18.5, 'width': 2.0},
        {'kind': 'line', 'x1': 16.5, 'y1': 11.5, 'x2': 9.5, 'y2': 18.5, 'width': 2.0},
    ]},
}

ELEMENT_FIELDS = {
    'line': (('x1', 'y1', 'x2', 'y2'), ()),
    'poly': (('points',), ()),
    'rect': (('x', 'y', 'w', 'h'), ('r',)),
    'circle': (('cx', 'cy', 'r'), ()),
    'arc': (('cx', 'cy', 'r', 'from', 'to'), ('lines', 'closed')),
}


# ---------------------------------------------------------------- validation

def parse_color(value):
    """'#RGB' or '#RRGGBB' to (r, g, b) floats; anything else is an error."""
    if not isinstance(value, str):
        raise ValueError('Theme color must be a string')
    digits = value[1:] if value.startswith('#') else None
    if digits is None or len(digits) not in (3, 6) or any(
            character not in '0123456789abcdefABCDEF' for character in digits):
        raise ValueError('Theme color must be #RGB or #RRGGBB: ' + value[:32])
    if len(digits) == 3:
        digits = ''.join(character * 2 for character in digits)
    return tuple(int(digits[index:index + 2], 16) / 255.0 for index in (0, 2, 4))


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value) and abs(value) <= 1024


def _point(value):
    return isinstance(value, (list, tuple)) and len(value) == 2 \
        and all(_number(coordinate) for coordinate in value)


def validate_element(name, element):
    if not isinstance(element, dict):
        raise ValueError('Theme icon %s element must be an object' % name)
    kind = element.get('kind')
    if kind not in ICON_KINDS:
        raise ValueError('Theme icon %s has an unknown element kind' % name)
    required, optional = ELEMENT_FIELDS[kind]
    unknown = set(element) - {'kind', 'color', 'fill', 'width'} - set(required) - set(optional)
    if unknown:
        raise ValueError('Theme icon %s element has unknown keys: %s'
                         % (name, ', '.join(sorted(unknown))))
    for field in required:
        if field not in element:
            raise ValueError('Theme icon %s element misses %s' % (name, field))
    if kind == 'poly':
        points = element['points']
        if not isinstance(points, list) or not 2 <= len(points) <= 16:
            raise ValueError('Theme icon %s poly needs 2..16 points' % name)
        if not all(_point(point) for point in points):
            raise ValueError('Theme icon %s poly has a bad point' % name)
    elif not all(_number(element[field]) for field in required):
        raise ValueError('Theme icon %s element has a bad number' % name)
    if kind == 'rect' and (element['w'] <= 0 or element['h'] <= 0
                           or element.get('r', 0) < 0):
        raise ValueError('Theme icon %s rect has a bad size' % name)
    if kind in ('circle', 'arc') and element['r'] <= 0:
        raise ValueError('Theme icon %s has a bad radius' % name)
    if kind == 'arc':
        if element['from'] == element['to']:
            raise ValueError('Theme icon %s arc has equal angles' % name)
        lines = element.get('lines', [])
        if not isinstance(lines, list) or len(lines) > 16:
            raise ValueError('Theme icon %s arc has bad lines' % name)
        if not all(_point(point) for point in lines):
            raise ValueError('Theme icon %s arc lines have a bad point' % name)
        if 'closed' in element and not isinstance(element['closed'], bool):
            raise ValueError('Theme icon %s arc closed must be a boolean' % name)
    if 'color' in element and element['color'] not in COLOR_TOKENS:
        raise ValueError('Theme icon %s element has an unknown color' % name)
    if 'fill' in element and not isinstance(element['fill'], bool):
        raise ValueError('Theme icon %s element fill must be a boolean' % name)
    if 'width' in element and not (_number(element['width']) and 0 < element['width'] <= 16):
        raise ValueError('Theme icon %s element has a bad width' % name)


def validate_icon(name, icon):
    if not isinstance(icon, dict):
        raise ValueError('Theme icon %s must be an object' % name)
    unknown = set(icon) - {'view', 'elements'}
    if unknown:
        raise ValueError('Theme icon %s has unknown keys' % name)
    view = icon.get('view')
    if not isinstance(view, list) or len(view) != 2 \
            or not all(_number(side) and 4 <= side <= 512 for side in view):
        raise ValueError('Theme icon %s needs a [width, height] view' % name)
    elements = icon.get('elements')
    if not isinstance(elements, list) or not 1 <= len(elements) <= 32:
        raise ValueError('Theme icon %s needs 1..32 elements' % name)
    for element in elements:
        validate_element(name, element)


def validate(raw):
    """Check a parsed theme object; partial overlays are fine."""
    if not isinstance(raw, dict):
        raise ValueError('Theme must be a JSON object')
    unknown = set(raw) - {'name', 'colors', 'icons', 'corners'}
    if unknown:
        raise ValueError('Unknown theme section: ' + ', '.join(sorted(unknown)))
    name = raw.get('name', '')
    if not isinstance(name, str) or len(name) > 64:
        raise ValueError('Invalid theme name')
    corners = raw.get('corners', {})
    if not isinstance(corners, dict):
        raise ValueError('Theme corners must be an object')
    unknown = set(corners) - set(CORNER_TOKENS)
    if unknown:
        raise ValueError('Unknown theme corner: ' + ', '.join(sorted(unknown)))
    for token, value in corners.items():
        if not _number(value) or not 0 <= value <= 24:
            raise ValueError('Theme corner %s must be 0..24 pixels' % token)
    colors = raw.get('colors', {})
    if not isinstance(colors, dict):
        raise ValueError('Theme colors must be an object')
    unknown = set(colors) - set(COLOR_TOKENS)
    if unknown:
        raise ValueError('Unknown theme color: ' + ', '.join(sorted(unknown)))
    icons = raw.get('icons', {})
    if not isinstance(icons, dict):
        raise ValueError('Theme icons must be an object')
    unknown = set(icons) - set(ICON_NAMES)
    if unknown:
        raise ValueError('Unknown theme icon: ' + ', '.join(sorted(unknown)))
    for icon_name, icon in icons.items():
        validate_icon(icon_name, icon)
    return raw


def resolve(raw, base_colors=None, base_icons=None):
    """Merge a validated partial theme over the defaults into a full theme."""
    raw = validate(raw)
    colors = dict(DEFAULT_COLORS if base_colors is None else base_colors)
    colors.update(raw.get('colors', {}))
    icons = dict(DEFAULT_ICONS if base_icons is None else base_icons)
    icons.update(raw.get('icons', {}))
    corners = dict(DEFAULT_CORNERS)
    corners.update({token: float(value) for token, value in raw.get('corners', {}).items()})
    return {'name': raw.get('name') or 'Untitled',
            'colors': {token: parse_color(value) for token, value in colors.items()},
            'icons': icons, 'corners': corners}


def load(path):
    data = Path(path).read_bytes()
    if len(data) > LIMIT:
        raise ValueError('Theme file exceeds %d bytes' % LIMIT)
    return resolve(json.loads(data))


# ------------------------------------------------------------------ palettes

def corner_radius(corners, token, width, height):
    """A themed corner radius clamped to half the box's smaller side."""
    return max(0.0, min(corners[token], width / 2, height / 2))


def gui_palette(theme):
    """Map a theme onto the dev_gui PALETTE token names."""
    colors = theme['colors']
    return {'bg': colors['bg'], 'chrome': colors['chrome'], 'panel': colors['chrome'],
            'text': colors['text'], 'dim': colors['dim'], 'accent': colors['accent'],
            'accent_dark': colors['accentText'], 'line': colors['line'],
            'red': colors['red']}


def shell_design(theme):
    """Map a theme onto the shell DESIGN token names."""
    colors = theme['colors']
    return {'bg': colors['bg'], 'line': colors['line'], 'button': colors['chrome'],
            'sep': colors['line'], 'green': colors['accent'], 'blue': colors['blue'],
            'white': colors['text'], 'gray': colors['dim'], 'red': colors['red']}


# -------------------------------------------------------------------- drawing

def _rect_path(cairo, cr, x, y, width, height, radius):
    if radius:
        cairo.rounded(cr, x, y, width, height, radius)
    else:
        cairo.move_to(cr, x, y)
        cairo.line_to(cr, x + width, y)
        cairo.line_to(cr, x + width, y + height)
        cairo.line_to(cr, x, y + height)
        cairo.close_path(cr)


def draw_icon(cairo, cr, icon, x, y, default_color, colors, default_width=1.5):
    """Draw one validated icon at (x, y) in its own view-box units."""
    for element in icon['elements']:
        color = colors[element['color']] if 'color' in element else default_color
        cairo.set_rgba(cr, *color, 1.0)
        cairo.set_line_width(cr, element.get('width', default_width))
        kind = element['kind']
        cairo.new_sub_path(cr)
        if kind == 'line':
            cairo.move_to(cr, x + element['x1'], y + element['y1'])
            cairo.line_to(cr, x + element['x2'], y + element['y2'])
        elif kind == 'poly':
            first = element['points'][0]
            cairo.move_to(cr, x + first[0], y + first[1])
            for point_x, point_y in element['points'][1:]:
                cairo.line_to(cr, x + point_x, y + point_y)
            if element.get('fill'):
                cairo.close_path(cr)
        elif kind == 'rect':
            _rect_path(cairo, cr, x + element['x'], y + element['y'],
                       element['w'], element['h'], element.get('r', 0))
        elif kind == 'circle':
            cairo.arc(cr, x + element['cx'], y + element['cy'], element['r'], 0, 6.2832)
        else:  # arc
            cairo.arc(cr, x + element['cx'], y + element['cy'], element['r'],
                      math.radians(element['from']), math.radians(element['to']))
            for point_x, point_y in element.get('lines', ()):
                cairo.line_to(cr, x + point_x, y + point_y)
            if element.get('closed'):
                cairo.close_path(cr)
        if element.get('fill'):
            cairo.fill(cr)
        else:
            cairo.stroke(cr)
