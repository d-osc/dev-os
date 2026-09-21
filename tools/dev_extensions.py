"""Dev OS extensions: VS Code-style contributions loaded beside the shell.

An extension is a directory with a manifest.json and an extension.py whose
activate(api) registers commands and tray icons through the ExtensionApi
object; deactivate() runs when the shell exits. The manifest format and the
API are language-agnostic on purpose: the desktop ships Python today, and a
JavaScript host (QuickJS/Node in a future image) can load the same manifests
without a format change. Extensions are trusted local code like VS Code
extensions — installing one is the consent; they run inside the shell
process, so only install what you trust. Manifests are strictly validated
and capped; a broken extension is reported and skipped, never fatal.
"""
import importlib.util
import json
from pathlib import Path
import re
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))

MANIFEST_LIMIT = 4096
CODE_LIMIT = 64 * 1024
TRAY_LIMIT = 4
WIDGET_LIMIT = 8
ZONES = ('left', 'right')
HIDEABLE = ('tray', 'clock', 'pinned')
ID = re.compile(r'[a-z0-9][a-z0-9-]*(\.[a-z0-9-]+)*')
VERSION = re.compile(r'\d+\.\d+\.\d+')
COLORS = ('bg', 'chrome', 'line', 'text', 'dim', 'accent', 'accentText', 'blue', 'red')


def validate(manifest):
    """Check one extension manifest; raise ValueError with the reason."""
    if not isinstance(manifest, dict):
        raise ValueError('Extension manifest must be a JSON object')
    unknown = set(manifest) - {'id', 'name', 'version', 'description', 'engine', 'main'}
    if unknown:
        raise ValueError('Unknown manifest key: ' + ', '.join(sorted(unknown)))
    for field in ('id', 'name', 'version', 'engine', 'main'):
        if field not in manifest:
            raise ValueError('Manifest misses %s' % field)
    identifier = manifest['id']
    if not isinstance(identifier, str) or len(identifier) > 64 or not ID.fullmatch(identifier):
        raise ValueError('Invalid extension id')
    if not isinstance(manifest['name'], str) or not 1 <= len(manifest['name']) <= 48:
        raise ValueError('Invalid extension name')
    if not isinstance(manifest['version'], str) or not VERSION.fullmatch(manifest['version']):
        raise ValueError('Invalid extension version (use MAJOR.MINOR.PATCH)')
    if type(manifest['engine']) is not int or manifest['engine'] != 1:
        raise ValueError('Unsupported extension engine')
    if manifest['main'] != 'extension.py':
        raise ValueError("Extension main must be 'extension.py'")
    description = manifest.get('description', '')
    if not isinstance(description, str) or len(description) > 160:
        raise ValueError('Invalid extension description')
    return manifest


class Painter:
    """The drawing surface handed to extension draw callbacks.

    Coordinates are local: (0, 0) is the top-left of the widget or panel.
    Colors are theme token names or (r, g, b) tuples; `colors` exposes the
    whole resolved palette and `raw` the (cairo, cr) pair for direct Cairo
    calls when the helpers are not enough.
    """

    def __init__(self, cairo, cr, x, y, width, height, colors, extents):
        self._cairo, self._cr, self._extents = cairo, cr, extents
        self._x, self._y = x, y
        self.width, self.height = width, height
        self.colors = colors

    @property
    def raw(self):
        return self._cairo, self._cr

    def _rgba(self, color, alpha):
        base = color if isinstance(color, tuple) else self.colors[color]
        return base + (alpha,)

    def text(self, value, x, y, color='text', size=12.0, bold=False, alpha=1.0):
        import dev_gui
        self._cairo.font_size(self._cr, size)
        self._cairo.font_face(self._cr, dev_gui.FONT, 0, 1 if bold else 0)
        self._cairo.set_rgba(self._cr, *self._rgba(color, alpha))
        self._cairo.move_to(self._cr, self._x + x, self._y + y)
        self._cairo.show_text(self._cr, str(value).encode('utf-8'))

    def text_width(self, value, size=12.0, bold=False):
        import dev_gui
        self._cairo.font_size(self._cr, size)
        self._cairo.font_face(self._cr, dev_gui.FONT, 0, 1 if bold else 0)
        self._cairo.text_extents(self._cr, str(value).encode('utf-8'), self._extents)
        return self._extents.x_advance

    def rect(self, x, y, width, height, color='chrome', radius=0, fill=True, alpha=1.0):
        self._cairo.set_rgba(self._cr, *self._rgba(color, alpha))
        self._cairo.rounded(self._cr, self._x + x, self._y + y, width, height, radius)
        self._cairo.fill(self._cr) if fill else self._cairo.stroke(self._cr)

    def line(self, x1, y1, x2, y2, color='text', width=1.5, alpha=1.0):
        self._cairo.set_rgba(self._cr, *self._rgba(color, alpha))
        self._cairo.set_line_width(self._cr, width)
        self._cairo.new_sub_path(self._cr)
        self._cairo.move_to(self._cr, self._x + x1, self._y + y1)
        self._cairo.line_to(self._cr, self._x + x2, self._y + y2)
        self._cairo.stroke(self._cr)

    def circle(self, cx, cy, radius, color='accent', fill=True, alpha=1.0):
        self._cairo.set_rgba(self._cr, *self._rgba(color, alpha))
        self._cairo.new_sub_path(self._cr)
        self._cairo.arc(self._cr, self._x + cx, self._y + cy, radius, 0, 6.2832)
        self._cairo.fill(self._cr) if fill else self._cairo.stroke(self._cr)

    def icon(self, icon, x, y, color='accent', width=1.5):
        import dev_gui
        import dev_theme
        resolved = dev_gui.ICONS[icon] if isinstance(icon, str) else icon
        dev_theme.draw_icon(self._cairo, self._cr, resolved, self._x + x, self._y + y,
                            self._rgba(color, 1.0)[:3], self.colors, width)


class PanelHandle:
    """A floating panel owned by an extension; show/hide/toggle drive it."""

    def __init__(self, spec):
        self.spec = spec
        self.slot = {'request': None, 'visible': False}

    def show(self):
        self.slot['request'] = 'show'

    def hide(self):
        self.slot['request'] = 'hide'

    def toggle(self):
        self.slot['request'] = 'toggle'

    @property
    def visible(self):
        return self.slot['visible']


class ExtensionApi:
    """The API surface extensions code against (version 2).

    Commands and tray icons cover the menu and the tray; widgets draw their
    own taskbar strips (register_widget), panels open floating surfaces
    drawn entirely by the extension (create_panel), override_clock replaces
    the built-in clock, and hide()/show() remove stock sections so an
    extension can rebuild any level of the bar. Draw callbacks receive a
    Painter; exceptions are caught and reported, never fatal to the shell.
    """

    version = 2

    def __init__(self, host, manifest):
        self._host = host
        self.manifest = manifest

    @property
    def settings(self):
        return dict(self._host.provides['settings']())

    @property
    def theme(self):
        return self._host.provides['theme']()

    @property
    def screen(self):
        return self._host.provides['screen']()

    def register_command(self, command_id, title, handler, detail=''):
        self._host.add_command(self.manifest['id'], command_id, title, handler, detail)

    def register_tray(self, icon_id, icon, command_id=None, color='accent'):
        self._host.add_tray(self.manifest['id'], icon_id, icon, command_id, color)

    def register_widget(self, zone, width, draw, on_click=None, widget_id=''):
        self._host.add_widget(self.manifest['id'], zone, width, draw, on_click, widget_id)

    def create_panel(self, panel_id, width, height, draw, on_event=None, x=8):
        return self._host.add_panel(self.manifest['id'], panel_id, width, height,
                                    draw, on_event, x)

    def override_clock(self, width, draw):
        self._host.set_clock_override(self.manifest['id'], width, draw)

    def hide(self, section):
        self._host.set_hidden(section, True)

    def show(self, section):
        self._host.set_hidden(section, False)

    def notify(self, title, body=''):
        self._host.provides['notify'](str(title)[:80], str(body)[:512])

    def set_theme(self, path):
        self._host.provides['set_theme'](str(path))


class Host:
    """Loads extensions and keeps what they contributed."""

    def __init__(self, provides):
        self.provides = provides
        self.commands = []          # {'id','ext','title','handler','detail'}
        self.tray = []              # {'ext','id','icon','command_id','color'}
        self.widgets = []           # {'ext','id','zone','width','draw','on_click'}
        self.panels = []            # PanelHandle objects
        self.hidden = set()         # stock sections switched off by extensions
        self.clock_override = None  # {'ext','width','draw'}
        self.modules = []           # loaded modules, newest first
        self.loaded = []            # ids of extensions that activated cleanly
        self.report = []            # {'id','error'} for broken extensions

    def load(self, directories):
        seen = set()
        for directory in directories:
            directory = Path(directory)
            if not directory.is_dir():
                continue
            for path in sorted(directory.iterdir()):
                if not path.is_dir() or path.name.startswith('.'):
                    continue
                if path.name in seen:
                    continue
                seen.add(path.name)
                try:
                    self._load_one(path)
                except Exception as error:            # a bad extension never
                    self.report.append({'id': path.name, 'error': str(error)})  # kills the shell
        return self

    def _load_one(self, path):
        raw = (path / 'manifest.json').read_bytes()
        if len(raw) > MANIFEST_LIMIT:
            raise ValueError('Manifest exceeds %d bytes' % MANIFEST_LIMIT)
        manifest = validate(json.loads(raw))
        code = path / manifest['main']
        size = code.stat().st_size
        if size > CODE_LIMIT:
            raise ValueError('Extension code exceeds %d bytes' % CODE_LIMIT)
        module_name = 'devos_ext_' + manifest['id'].replace('.', '_')
        spec = importlib.util.spec_from_file_location(module_name, code)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        api = ExtensionApi(self, manifest)
        before = (len(self.commands), len(self.tray), len(self.widgets), len(self.panels))
        if hasattr(module, 'activate'):
            module.activate(api)
        after = (len(self.commands), len(self.tray), len(self.widgets), len(self.panels))
        if after != before:
            self.modules.append(module)               # only keep contributing ones
            self.loaded.append(manifest['id'])
        elif hasattr(module, 'deactivate'):
            module.deactivate()

    def add_command(self, extension_id, command_id, title, handler, detail):
        if len(self.commands) >= 24:
            raise ValueError('Too many commands')
        if not callable(handler):
            raise ValueError('Command handler must be callable')
        self.commands.append({'ext': extension_id, 'id': str(command_id)[:64],
                              'title': str(title)[:48], 'handler': handler,
                              'detail': str(detail)[:80]})

    def add_tray(self, extension_id, icon_id, icon, command_id, color):
        if len(self.tray) >= TRAY_LIMIT:
            raise ValueError('Too many tray icons')
        if color not in COLORS:
            raise ValueError('Unknown tray color token')
        if isinstance(icon, str):
            from dev_theme import ICON_NAMES
            if icon not in ICON_NAMES:
                raise ValueError('Unknown theme icon: ' + icon)
        else:
            from dev_theme import validate_icon
            validate_icon(str(icon_id), icon)
        self.tray.append({'ext': extension_id, 'id': str(icon_id)[:64], 'icon': icon,
                          'command_id': command_id, 'color': color})

    def add_widget(self, extension_id, zone, width, draw, on_click, widget_id):
        if zone not in ZONES:
            raise ValueError('Widget zone must be left or right')
        if len(self.widgets) >= WIDGET_LIMIT:
            raise ValueError('Too many widgets')
        if not isinstance(width, int) or not 8 <= width <= 320:
            raise ValueError('Widget width must be 8..320 pixels')
        if not callable(draw) or (on_click is not None and not callable(on_click)):
            raise ValueError('Widget draw and on_click must be callable')
        self.widgets.append({'ext': extension_id, 'id': str(widget_id or zone)[:64],
                             'zone': zone, 'width': width, 'draw': draw,
                             'on_click': on_click})

    def add_panel(self, extension_id, panel_id, width, height, draw, on_event, x):
        if not isinstance(width, int) or not 64 <= width <= 800 \
                or not isinstance(height, int) or not 32 <= height <= 600:
            raise ValueError('Panel size must be 64..800 x 32..600 pixels')
        if not callable(draw) or (on_event is not None and not callable(on_event)):
            raise ValueError('Panel draw and on_event must be callable')
        if not isinstance(x, int) or not 0 <= x <= 4000:
            raise ValueError('Panel x must be a screen coordinate')
        handle = PanelHandle({'ext': extension_id, 'id': str(panel_id)[:64],
                              'width': width, 'height': height, 'draw': draw,
                              'on_event': on_event, 'x': x})
        self.panels.append(handle)
        return handle

    def set_clock_override(self, extension_id, width, draw):
        if not isinstance(width, int) or not 40 <= width <= 400:
            raise ValueError('Clock override width must be 40..400 pixels')
        if not callable(draw):
            raise ValueError('Clock override draw must be callable')
        self.clock_override = {'ext': extension_id, 'width': width, 'draw': draw}

    def set_hidden(self, section, hidden):
        if section not in HIDEABLE:
            raise ValueError('hide() accepts: ' + ', '.join(HIDEABLE))
        if hidden:
            self.hidden.add(section)
        else:
            self.hidden.discard(section)

    def command_entries(self):
        """Menu rows for the contributed commands."""
        return [{'kind': 'command', 'name': command['id'], 'label': command['title'],
                 'comment': command['detail'] or command['ext'],
                 'categories': ['Command'], 'permissions': []}
                for command in self.commands]

    def run_command(self, command_id):
        for command in self.commands:
            if command['id'] == command_id:
                command['handler']()
                return True
        return False

    def tray_click(self, index):
        command_id = self.tray[index]['command_id']
        if command_id is not None:
            self.run_command(command_id)

    def unload(self):
        for module in self.modules:
            deactivate = getattr(module, 'deactivate', None)
            if deactivate:
                try:
                    deactivate()
                except Exception:
                    traceback.print_exc()
        for handle in self.panels:
            handle.slot['request'] = 'hide'
        self.commands, self.tray, self.widgets, self.panels, self.modules = [], [], [], [], []
        self.clock_override, self.hidden = None, set()
