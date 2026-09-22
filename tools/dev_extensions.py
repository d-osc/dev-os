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
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))

MANIFEST_LIMIT = 4096
CODE_LIMIT = 64 * 1024
TRAY_LIMIT = 4
WIDGET_LIMIT = 8
OP_LIMIT = 64
OP_KINDS = ('text', 'rect', 'line', 'circle', 'icon')
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
    if manifest['main'] not in ('extension.py', 'extension.js'):
        raise ValueError("Extension main must be 'extension.py' or 'extension.js'")
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
        self.js = []                # JsSession processes
        self.loaded = []            # ids of extensions that activated cleanly
        self.report = []            # {'id','error'} for broken extensions

    def load(self, directories):
        seen = set()
        for directory in directories:
            directory = Path(directory)
            if not directory.is_dir():
                continue
            for path in sorted(directory.iterdir()):
                if not path.is_dir() or path.name.startswith('.') \
                        or (path / '.disabled').is_file():
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
        if manifest['main'] == 'extension.js':
            session = JsSession(manifest['id'], self,
                                Path(__file__).resolve().parent / 'ext-runner.js', path)
            session.start()
            self.js.append(session)
            self.loaded.append(manifest['id'])
            return
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
        for session in self.js:
            session.stop()
        self.commands, self.tray, self.widgets, self.panels, self.modules = [], [], [], [], []
        self.clock_override, self.hidden, self.js = None, set(), []


# ------------------------------------------------- JavaScript extensions

def _op_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and abs(value) <= 4096


def validate_ops(ops):
    """Check a declarative draw list (JSON-safe, what JS extensions send)."""
    if not isinstance(ops, list) or len(ops) > OP_LIMIT:
        raise ValueError('Draw ops must be a list of at most %d items' % OP_LIMIT)
    for op in ops:
        if not isinstance(op, dict) or op.get('op') not in OP_KINDS:
            raise ValueError('Unknown draw op')
        color = op.get('color')
        if color is not None and color not in COLORS:
            raise ValueError('Unknown draw op color: %s' % color)
        for key, value in op.items():
            if key in ('x', 'y', 'w', 'h', 'r', 'x1', 'y1', 'x2', 'y2', 'cx', 'cy',
                       'size', 'width', 'alpha') and not _op_number(value):
                raise ValueError('Draw op has a bad %s' % key)
        if op['op'] == 'text' and not isinstance(op.get('value', ''), str):
            raise ValueError('Text op needs a string value')
        if len(op.get('value', '')) > 80:
            raise ValueError('Text op value is too long')
        if op['op'] == 'icon' and not isinstance(op.get('icon'), (str, dict)):
            raise ValueError('Icon op needs an icon name or object')
    return ops


def play_ops(painter, ops):
    """Replay a validated draw list onto a Painter."""
    for op in ops:
        kind = op['op']
        if kind == 'text':
            painter.text(op.get('value', ''), op.get('x', 0), op.get('y', 0),
                         op.get('color', 'text'), float(op.get('size', 12.0)),
                         bool(op.get('bold', False)), float(op.get('alpha', 1.0)))
        elif kind == 'rect':
            painter.rect(op.get('x', 0), op.get('y', 0), op.get('w', 0), op.get('h', 0),
                         op.get('color', 'chrome'), radius=op.get('r', 0),
                         fill=bool(op.get('fill', True)), alpha=float(op.get('alpha', 1.0)))
        elif kind == 'line':
            painter.line(op.get('x1', 0), op.get('y1', 0), op.get('x2', 0),
                         op.get('y2', 0), op.get('color', 'text'),
                         width=op.get('width', 1.5), alpha=float(op.get('alpha', 1.0)))
        elif kind == 'circle':
            painter.circle(op.get('cx', 0), op.get('cy', 0), op.get('r', 1),
                           op.get('color', 'accent'), fill=bool(op.get('fill', True)),
                           alpha=float(op.get('alpha', 1.0)))
        else:  # icon
            painter.icon(op.get('icon'), op.get('x', 0), op.get('y', 0),
                         op.get('color', 'accent'), width=op.get('width', 1.5))


def _ops_drawer(surface):
    def draw(painter):
        play_ops(painter, surface['ops'])
    return draw


class JsSession:
    """One Node.js extension process speaking line JSON with the shell.

    The runner (ext-runner.js) loads extension.js, which registers through
    the api exactly like a Python extension. Draw callbacks cannot cross a
    process boundary, so JS surfaces pass declarative draw-op lists that
    this side replays through a Painter; updateWidget/updatePanel replace
    the stored list. Commands, tray clicks and panel events travel back as
    messages the runner dispatches to the JS handlers.
    """

    def __init__(self, extension_id, host, runner, directory):
        self.id = extension_id
        self.host = host
        self.runner = Path(runner)
        self.directory = Path(directory)
        self.process = None
        self.surfaces = {}      # 'widget:<id>' / 'panel:<id>' / 'clock' -> {'ops'}
        self.panels = {}        # panel id -> PanelHandle

    def start(self):
        node = shutil.which('node')
        if node is None:
            raise ValueError('Node.js runtime not found for a JavaScript extension')
        context = json.dumps({'settings': self.host.provides['settings'](),
                              'theme': self.host.provides['theme'](),
                              'screen': self.host.provides['screen']()})
        environment = dict(os.environ, DEVOS_EXT_CONTEXT=context)
        self.process = subprocess.Popen(
            [node, str(self.runner), str(self.directory)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1, env=environment)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.process.stdout:
            try:
                self.handle_line(line)
            except Exception as error:
                print('extension %s sent a bad message: %s' % (self.id, error),
                      file=sys.stderr)

    def send(self, message):
        if self.process is not None and self.process.stdin:
            try:
                self.process.stdin.write(json.dumps(message) + '\n')
                self.process.stdin.flush()
            except (OSError, ValueError):
                pass  # the child is gone; its contributions stay inert

    def handle_line(self, line):
        message = json.loads(line)
        kind = message.get('type')
        if kind == 'command':
            command_id = str(message['id'])
            self.host.add_command(
                self.id, command_id, str(message.get('title', command_id)),
                lambda: self.send({'type': 'invoke', 'command': command_id}),
                str(message.get('detail', '')))
        elif kind == 'tray':
            self.host.add_tray(self.id, str(message['id']), message['icon'],
                               message.get('command_id'), message.get('color', 'accent'))
        elif kind == 'widget':
            surface = {'ops': validate_ops(message.get('ops', []))}
            widget_id = str(message.get('id', message['zone']))
            self.surfaces['widget:' + widget_id] = surface
            on_click = None
            if message.get('click'):
                on_click = lambda: self.send({'type': 'widget_click', 'id': widget_id})
            self.host.add_widget(self.id, message['zone'], message['width'],
                                 _ops_drawer(surface), on_click, widget_id)
        elif kind == 'panel':
            panel_id = str(message['id'])
            surface = {'ops': validate_ops(message.get('ops', []))}
            self.surfaces['panel:' + panel_id] = surface

            def on_event(action, x, y, panel_id=panel_id):
                self.send({'type': 'panel_event', 'id': panel_id,
                           'action': action, 'x': x, 'y': y})

            self.panels[panel_id] = self.host.add_panel(
                self.id, panel_id, message['width'], message['height'],
                _ops_drawer(surface), on_event, message.get('x', 8))
        elif kind == 'panel_cmd':
            handle = self.panels.get(str(message['id']))
            if handle is not None and message.get('cmd') in ('show', 'hide', 'toggle'):
                handle.slot['request'] = message['cmd']
        elif kind == 'update':
            surface = self.surfaces.get(str(message.get('target', '')) + ':'
                                        + str(message.get('id', '')))
            if surface is not None:
                surface['ops'] = validate_ops(message.get('ops', []))
        elif kind == 'clock_override':
            surface = {'ops': validate_ops(message.get('ops', []))}
            self.surfaces['clock'] = surface
            self.host.set_clock_override(self.id, message['width'], _ops_drawer(surface))
        elif kind == 'clock_restore':
            self.host.clock_override = None
        elif kind in ('hide', 'show'):
            self.host.set_hidden(str(message['section']), kind == 'hide')
        elif kind == 'notify':
            self.host.provides['notify'](str(message.get('title', '')),
                                         str(message.get('body', '')))
        elif kind == 'set_theme':
            self.host.provides['set_theme'](str(message['path']))
        elif kind != 'ready':
            raise ValueError('unknown message type %r' % kind)

    def stop(self):
        if self.process is None:
            return
        try:
            self.process.stdin.close()
            self.process.terminate()
            self.process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            self.process.kill()


# --------------------------------------------------------------- management

USER_ENV = 'DEVOS_EXTENSIONS_USER'
SOURCE_FILE_LIMIT = 16
SOURCE_SIZE_LIMIT = 256 * 1024


def extension_dirs(root='/'):
    """[user, system] extension directories; the env var exists for tests."""
    user = Path(os.environ.get(USER_ENV) or Path.home() / '.config/devos/extensions')
    return [user, Path(root) / 'usr/share/devos/extensions']


def scan(dirs):
    """Catalog every extension across directories with its state."""
    found = []
    for index, directory in enumerate(dirs):
        directory = Path(directory)
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if not path.is_dir() or path.name.startswith('.'):
                continue
            entry = {'source': 'user' if index == 0 else 'system', 'path': path,
                     'disabled': (path / '.disabled').is_file()}
            try:
                raw = (path / 'manifest.json').read_bytes()
                if len(raw) > MANIFEST_LIMIT:
                    raise ValueError('oversized manifest')
                manifest = validate(json.loads(raw))
                entry.update(id=manifest['id'], name=manifest['name'],
                             version=manifest['version'])
            except (OSError, ValueError) as error:
                entry.update(id=path.name, name='(invalid: %s)' % error,
                             version='-', invalid=True)
            found.append(entry)
    return found


def _check_source(source):
    """Validate an extension directory before it may be installed."""
    path = Path(source)
    if not path.is_dir():
        raise ValueError('Extension source must be a directory')
    if not (path / 'manifest.json').is_file():
        raise ValueError('manifest.json is missing')
    raw = (path / 'manifest.json').read_bytes()
    if len(raw) > MANIFEST_LIMIT:
        raise ValueError('Manifest exceeds %d bytes' % MANIFEST_LIMIT)
    manifest = validate(json.loads(raw))
    main = path / manifest['main']
    if not main.is_file():
        raise ValueError('Main file %s is missing' % manifest['main'])
    if main.stat().st_size > CODE_LIMIT:
        raise ValueError('Extension code exceeds %d bytes' % CODE_LIMIT)
    files = total = 0
    for item in path.iterdir():
        if item.is_symlink():
            raise ValueError('Symlinks are not allowed in an extension')
        if not item.is_file():
            raise ValueError('Subdirectories are not allowed in an extension')
        files += 1
        total += item.stat().st_size
    if files > SOURCE_FILE_LIMIT:
        raise ValueError('Extensions may carry at most %d files' % SOURCE_FILE_LIMIT)
    if total > SOURCE_SIZE_LIMIT:
        raise ValueError('Extensions may total at most %d bytes' % SOURCE_SIZE_LIMIT)
    return manifest


def install(source, dirs):
    """Copy a validated extension directory into the user directory."""
    manifest = _check_source(source)
    destination = Path(dirs[0]) / manifest['id']
    if destination.exists():
        raise ValueError('%s is already installed; uninstall it first' % manifest['id'])
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, symlinks=False)
    return manifest['id']


def _entry(extension_id, dirs):
    for entry in scan(dirs):
        if entry.get('id') == extension_id and not entry.get('invalid'):
            return entry
    raise ValueError('Unknown extension: ' + extension_id)


def uninstall(extension_id, dirs):
    entry = _entry(extension_id, dirs)
    if entry['source'] != 'user':
        raise ValueError('%s ships with the system image; it cannot be '
                         'uninstalled per user' % extension_id)
    shutil.rmtree(entry['path'])
    return entry['path']


def set_state(extension_id, dirs, disabled):
    entry = _entry(extension_id, dirs)
    marker = entry['path'] / '.disabled'
    if disabled:
        marker.touch()
    elif marker.exists():
        marker.unlink()
    return entry['path']


def manage(args, root='/'):
    """The `dev ext list|install|uninstall|enable|disable` command."""
    dirs = extension_dirs(root)
    if args.action == 'list':
        entries = scan(dirs)
        if not entries:
            print('No extensions installed')
        for entry in entries:
            print('%-26s %-8s %-26s %-8s %s'
                  % (entry['id'], entry['version'], entry['name'][:26],
                     'disabled' if entry['disabled'] else 'enabled',
                     entry['source']))
        return 0
    if not args.target:
        raise ValueError('dev ext %s needs an extension id or directory' % args.action)
    if args.action == 'install':
        print('Installed ' + install(args.target, dirs))
    elif args.action == 'uninstall':
        print('Uninstalled %s (%s)' % (args.target, uninstall(args.target, dirs)))
    else:
        set_state(args.target, dirs, args.action == 'disable')
        print('%s is now %s' % (args.target, 'disabled' if args.action == 'disable'
                                else 'enabled'))
    return 0
