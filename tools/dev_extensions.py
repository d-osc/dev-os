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
import traceback

MANIFEST_LIMIT = 4096
CODE_LIMIT = 64 * 1024
TRAY_LIMIT = 4
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


class ExtensionApi:
    """The API surface extensions code against (version 1).

    register_command(id, title, handler, detail='') shows a menu entry that
    runs handler() when chosen. register_tray(id, icon, command_id=None,
    color='accent') adds a taskbar glyph (icon: a theme icon name or an
    icon dict in the THEMES.md format) that runs a command when clicked.
    notify(title, body='') posts a desktop notification, and set_theme(path)
    switches the live theme of the whole desktop. settings/theme/screen are
    read-only views for orientation.
    """

    version = 1

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
        before = (len(self.commands), len(self.tray))
        if hasattr(module, 'activate'):
            module.activate(api)
        if len(self.commands) != before[0] or len(self.tray) != before[1]:
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
        self.commands, self.tray, self.modules = [], [], []
