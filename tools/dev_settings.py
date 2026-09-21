"""User settings for the Dev OS desktop, in a VS Code-style settings.json.

Settings are flat `section.name` keys validated against a fixed schema and
merged over built-in defaults. Files load from three layers, later wins:
/etc/devos/settings.json, ~/.config/devos/settings.json and an explicit
override (the --settings flag or $DEVOS_SETTINGS). The `theme` value is a
theme name resolved against the theme directories, or a path, or 'default'
for the built-in look. Like theme files, settings are untrusted input:
size-capped and strictly validated.
"""
import json
from pathlib import Path

LIMIT = 16384
SYSTEM = Path('/etc/devos/settings.json')
USER = Path.home() / '.config/devos/settings.json'
THEME_DIRS = (Path('themes'), Path('/usr/share/devos/themes'))

DEFAULTS = {'theme': 'dev-dark', 'clock.hour12': False, 'clock.showSeconds': True,
            'clock.dateFormat': '%b %d, %Y', 'font.family': 'DejaVu Sans'}
BOOLEANS = ('clock.hour12', 'clock.showSeconds')


def _printable(value, limit):
    return isinstance(value, str) and 1 <= len(value) <= limit \
        and all(32 <= ord(character) < 127 for character in value)


def validate(raw):
    """Check a parsed settings object; partial files are fine."""
    if not isinstance(raw, dict):
        raise ValueError('Settings must be a JSON object')
    unknown = set(raw) - set(DEFAULTS)
    if unknown:
        raise ValueError('Unknown setting: ' + ', '.join(sorted(unknown)))
    limits = {'theme': 128, 'clock.dateFormat': 48, 'font.family': 64}
    for key, value in raw.items():
        if key in BOOLEANS:
            if not isinstance(value, bool):
                raise ValueError('Setting %s must be a boolean' % key)
        elif not _printable(value, limits[key]):
            raise ValueError('Setting %s must be 1..%d printable characters' % (key, limits[key]))
    return raw


def resolve(raw):
    settings = dict(DEFAULTS)
    settings.update(validate(raw))
    return settings


def load(path):
    data = Path(path).read_bytes()
    if len(data) > LIMIT:
        raise ValueError('Settings file exceeds %d bytes' % LIMIT)
    return resolve(json.loads(data))


def active(extra=None):
    """Merged settings: system file, then user file, then the override."""
    overlay = {}
    for path in (SYSTEM, USER, extra):
        if path is not None and Path(path).is_file():
            overlay.update(load_raw(path))
    settings = dict(DEFAULTS)
    settings.update(overlay)
    return settings


def load_raw(path):
    data = Path(path).read_bytes()
    if len(data) > LIMIT:
        raise ValueError('Settings file exceeds %d bytes' % LIMIT)
    return validate(json.loads(data))


def theme_path(value, dirs=THEME_DIRS):
    """A theme setting to a file path; None means the built-in default."""
    if value == 'default':
        return None
    if value.endswith('.json') or '/' in value or '\\' in value:
        return Path(value)
    for directory in dirs:
        found = Path(directory) / (value + '.json')
        if found.is_file():
            return found
    raise ValueError('Unknown theme name: ' + value)
