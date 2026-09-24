#!/usr/bin/python3
"""Dev OS desktop shell: the design taskbar, application menu and clock.

A flat near-black bar (40px) matching the reference design: a green-outlined
`>_ DEVOS` start button on the left, pinned-app icons with running
dots and a blue active underline, decorative tray glyphs (wifi, volume,
notifications) and a two-line clock on the right. Rendering and X11 plumbing
come from the shared dev_gui toolkit (ctypes + Cairo): anti-aliased TrueType
text, rounded corners, hover feedback. The bar reserves the bottom pixels
with EWMH struts; the menu is a translucent ARGB popup when the server
offers that visual (evidence capture uses plain windows because the test
display's XWayland cannot capture ARGB or override-redirect windows).
Clicking a pinned app focuses its window, or opens the consent row when none
is open; launching then runs `dev launch <name> --allow <declared
permissions>`: the shell never widens a permission set and keeps no grants.
It is a normal user process for an X11 session; the OS image does not start
it automatically yet.
"""
import argparse
import ctypes as c
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.append('/usr/lib/devos')
import dev_gui  # noqa: E402
import dev_extensions  # noqa: E402
import dev_settings  # noqa: E402
import dev_theme  # noqa: E402

BAR_HEIGHT = 40
PILL_X, PILL_WIDTH = 8, 100
MENU_END = PILL_X + PILL_WIDTH
SEPARATOR_OFF = 15
PIN_PAD = 12
PIN_START = MENU_END + SEPARATOR_OFF + PIN_PAD
PIN_SIZE, PIN_GAP = 28, 10
TRAY_SIZE, TRAY_GAP, TRAY_PITCH, TRAY_LEFT = 16, 8, 24, 88
MAX_PINNED = 9
TRAY_RESERVE = 220
CLOCK_PAD = 10
CLOCK_BLOCK = 68
MENU_WIDTH = 320
MENU_ITEM_HEIGHT = 36
MENU_HEADER_HEIGHT = 26
CONSENT_HEIGHT = 52
ALLOW_X, CANCEL_X = 214, 288
PALETTE = dev_gui.PALETTE
# The shell design tokens derive from the same JSON theme as the windows:
# an accent start button, a blue active-app underline, a red badge.
DESIGN = dev_theme.shell_design(dev_gui.DEFAULT_THEME)
ACCENT = DESIGN['green']
THEME_SOURCE = [None]


def apply_theme(theme):
    """Restyle the shell and every window app from one resolved theme."""
    global ACCENT
    dev_gui.set_theme(theme)
    DESIGN.update(dev_theme.shell_design(theme))
    ACCENT = DESIGN['green']


# ---------------------------------------------------------------- pure logic

def applications(database):
    """Menu entries for packages that declare a window, sorted by label."""
    items = []
    for name, record in (database or {}).items():
        if not isinstance(record, dict) or 'window' not in record:
            continue
        launcher = record.get('launcher') or {}
        label = launcher.get('name') or record.get('display_name') or name
        items.append({'kind': 'app', 'name': name, 'label': str(label)[:48],
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


def time_text(moment=None, settings=None):
    settings = settings or {}
    if settings.get('clock.hour12'):
        pattern = '%I:%M:%S %p' if settings.get('clock.showSeconds', True) else '%I:%M %p'
    else:
        pattern = '%H:%M:%S' if settings.get('clock.showSeconds', True) else '%H:%M'
    return time.strftime(pattern, time.localtime(moment))


def date_text(moment=None, settings=None):
    pattern = (settings or {}).get('clock.dateFormat') or '%b %d, %Y'
    return time.strftime(pattern, time.localtime(moment)).upper()


def monogram(item):
    """The single-character glyph shown in a pinned app icon."""
    for character in item['label']:
        if character.isalnum():
            return character.upper()
    return '>'


def truncate(text, measure, max_px):
    """Shorten text to max_px using measure(text)->pixels."""
    if measure(text) <= max_px:
        return text
    while text and measure(text + '...') > max_px:
        text = text[:-1]
    return (text + '...') if text else '...'


def pinned_count(total, width):
    """How many pinned icons fit between the start pill and the tray."""
    room = width - PIN_START - TRAY_RESERVE
    return max(0, min(total, room // (PIN_SIZE + PIN_GAP), MAX_PINNED))


def window_for(item, clients):
    """The open window of a pinned app, if any; matched by title."""
    label, name = item['label'].lower(), item['name'].lower()
    for title, window in clients:
        if label in title.lower() or name in title.lower():
            return window
    return None


def pinned_states(items, clients):
    """(running flags, first running index) for the pinned icons."""
    windows = [window_for(item, clients) for item in items]
    active = next((index for index, window in enumerate(windows) if window), None)
    return [window is not None for window in windows], active


def bar_regions(width, app_count=0, tray_right=None, tray_count=0):
    """Clickable spans of the bar: (kind, start, end, index)."""
    regions = [('menu', 0, MENU_END, None)]
    left = PIN_START
    for index in range(app_count):
        regions.append(('app', left, left + PIN_SIZE, index))
        left += PIN_SIZE + PIN_GAP
    if tray_count and tray_right is not None:
        for index in range(tray_count):
            start = tray_right - TRAY_PITCH * (index + 1) + TRAY_GAP
            regions.append(('tray', start, start + TRAY_SIZE, index))
    regions.append(('clock', width - CLOCK_PAD - CLOCK_BLOCK, width, None))
    return regions


def bar_hit(width, x, app_count=0, tray_right=None, tray_count=0):
    for kind, start, end, index in bar_regions(width, app_count, tray_right, tray_count):
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


def hover_key(area, x, y, *, width=0, app_count=0, tray_right=None, tray_count=0,
              item_count=0, consent=False):
    """Which actionable element the pointer is over, for hover feedback."""
    if area == 'bar':
        for kind, start, end, index in bar_regions(width, app_count, tray_right, tray_count):
            if start <= x < end and kind != 'clock':
                return kind if index is None else (kind, index)
        return None
    index = item_at(item_count, y, consent)
    if index is None:
        return None
    if index == -1:
        if ALLOW_X <= x < CANCEL_X:
            return 'allow'
        return 'cancel' if x >= CANCEL_X else None
    return ('item', index)


def load_database(root):
    path = Path(root) / 'var/lib/dev/installed.json'
    if not path.is_file():
        return {}
    database = json.loads(path.read_text())
    if not isinstance(database, dict):
        raise SystemExit('Invalid installed package database')
    return database


# ------------------------------------------------------------------- X11 side

def screenshot(x, api, display, window, path, width, height):
    pointer = api['get_image'](display, window, 0, 0, width, height, 0xFFFFFFFF, 2)
    if not pointer:
        raise SystemExit('Could not capture the shell window')
    try:
        rows = dev_gui.decode_rows(dev_gui.XImage.from_address(pointer))
        dev_gui.write_png(path, width, height, rows)
    finally:
        x.XFree(pointer)


def property_windows(x, api, display, root, name):
    atom = api['atom'](display, name.encode(), 1)
    if not atom:
        return []
    actual, format_, count, remaining, data = (c.c_ulong(), c.c_int(), c.c_ulong(),
                                                c.c_ulong(), c.c_void_p())
    result = api['get_property'](display, root, atom, 0, 1024, 0, 0,
                                 c.byref(actual), c.byref(format_), c.byref(count),
                                 c.byref(remaining), c.byref(data))
    if result != 0 or not count.value or format_.value != 32:
        return []
    try:
        return list((c.c_ulong * count.value).from_address(data.value))
    finally:
        x.XFree(data.value)


def toast_layout(messages, now, width, height):
    """(x, y, title, body, alpha) for each live toast, top-right stacked."""
    cards = []
    for order, message in enumerate(messages):
        age = now - message['at']
        if age > 5.0:
            continue
        alpha = 1.0 if age < 4.0 else max(0.15, 1.0 - (age - 4.0))
        y = 12 + order * 74
        cards.append((width - 296, y, message['title'], message['body'], alpha))
    return cards


def network_state(command='ip'):
    """('online' | 'offline', detail) from the running ip command."""
    try:
        listing = subprocess.run([command, '-4', 'addr', 'show', 'scope', 'global'],
                                 capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return 'offline', 'no network tool'
    for line in listing.splitlines():
        if line.strip().startswith('inet '):
            address = line.strip().split()[1].split('/')[0]
            return 'online', address
    return 'offline', 'no address'


def password_ok(password, sudo='sudo'):
    """Verify against the real account via sudo -S; never reads shadow."""
    if not password:
        return False
    try:
        result = subprocess.run([sudo, '-S', '-k', '-u', 'root', 'true'],
                                input=(password + chr(10)).encode(),
                                capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def lock_layout(width, height):
    """Geometry of the lock card: centered, matching the greeter's look."""
    return (width - 380) // 2, (height - 200) // 2, 380, 200


def mode_error(mode):
    """None when the shell may run in this system mode, else a message."""
    return None if mode == 'desktop' else \
        'dev-shell runs in desktop mode only (current: %s); ' \
        'use `dev mode set desktop` to switch' % mode


def theme_from(path, settings=None, settings_dir=None):
    """--theme flag > DEVOS_THEME > the settings file > built-in default."""
    source = path or os.environ.get('DEVOS_THEME')
    if source:
        return dev_theme.load(source), source
    value = (settings or {}).get('theme', 'dev-dark')
    if value == 'default':
        return dev_gui.DEFAULT_THEME, None
    dirs = ((settings_dir / 'themes',) if settings_dir else ()) + dev_settings.THEME_DIRS
    resolved = dev_settings.theme_path(value, dirs)
    if resolved is None:
        return dev_gui.DEFAULT_THEME, None
    return dev_theme.load(resolved), str(resolved)


def run(root, *, dev='dev', shots=None, theme=None, theme_source=None, settings=None,
        extension_dirs=None):
    settings = settings or {}
    problem = mode_error(dev_settings.read_mode(root))
    if problem:
        raise SystemExit(problem)
    if theme is None:
        theme, theme_source = dev_gui.DEFAULT_THEME, None
    apply_theme(theme)
    THEME_SOURCE[0] = theme_source
    x, api = dev_gui.connect()
    cairo = dev_gui.Cairo()
    display = api['open_display'](None)
    if not display:
        raise SystemExit('Unable to open desktop display')
    width = api['display_width'](display, 0)
    height = api['display_height'](display, 0)
    root_window = api['root_window'](display, 0)
    default_visual = api['default_visual'](display, 0)
    # Shell chrome is override-redirect: a window manager (openbox manages
    # application windows) must not reparent, decorate or reposition it.
    bar_attributes = dev_gui.SetWindowAttributes(
        border_pixel=0, override_redirect=1,
        event_mask=(1 << 15) | (1 << 2) | (1 << 3) | (1 << 6))
    bar = api['create_window'](display, root_window, 0, height - BAR_HEIGHT,
                               width, BAR_HEIGHT, 0, 0, 1, default_visual,
                               (1 << 9) | (1 << 11) | (1 << 17),
                               c.byref(bar_attributes))
    api['store_name'](display, bar, b'Dev OS Shell')

    # The menu prefers a 32-bit ARGB visual for true translucency; capture
    # mode stays on the default visual because the test display's XWayland
    # cannot capture ARGB or override-redirect windows.
    info = dev_gui.VisualInfo()
    argb = shots is None and api['match_visual'](display, 0, 32, 4, c.byref(info))
    if argb:
        colormap = api['create_colormap'](display, root_window, info.visual, 0)
        attributes = dev_gui.SetWindowAttributes(border_pixel=0, colormap=colormap,
                                                 override_redirect=1, event_mask=1 << 15)
        menu = api['create_window'](display, root_window, 0, 0, 100, 100, 0, 32, 1,
                                    info.visual, 1 | 2 | 0x400 | 0x800, c.byref(attributes))
        menu_visual = info.visual
    else:
        menu = api['create'](display, root_window, 0, 0, 100, 100, 1, 0x10151d, 0x10151d)
        menu_visual = default_visual
    api['store_name'](display, menu, b'Dev OS Menu')

    def set_atom_values(window, name, values, kind):
        array = (c.c_ulong * len(values))(*values)
        api['change_property'](display, window, api['atom'](display, name.encode(), 0),
                               api['atom'](display, kind.encode(), 0), 32, 0,
                               c.cast(array, c.c_void_p), len(values))

    def set_atoms(window, name, value_names):
        set_atom_values(window, name, [api['atom'](display, item.encode(), 1)
                                       for item in value_names], 'ATOM')

    set_atoms(bar, '_NET_WM_WINDOW_TYPE', ['_NET_WM_WINDOW_TYPE_DOCK'])
    set_atoms(bar, '_NET_WM_STATE', ['_NET_WM_STATE_ABOVE', '_NET_WM_STATE_SKIP_TASKBAR',
                                     '_NET_WM_STATE_SKIP_PAGER'])
    set_atom_values(bar, '_NET_WM_DESKTOP', [0xFFFFFFFF], 'CARDINAL')
    set_atom_values(bar, '_NET_WM_STRUT', [0, 0, 0, BAR_HEIGHT], 'CARDINAL')
    set_atom_values(bar, '_NET_WM_STRUT_PARTIAL',
                    [0, 0, 0, BAR_HEIGHT, 0, 0, 0, 0, 0, 0, 0, width], 'CARDINAL')
    protocols = api['atom'](display, b'WM_PROTOCOLS', 1)
    delete = api['atom'](display, b'WM_DELETE_WINDOW', 1)
    api['set_protocols'](display, bar, c.byref(c.c_ulong(delete)), 1)

    # The desktop wallpaper lives on its own bottom-of-stack window: drawing
    # on the root window itself cannot be captured and does not survive
    # exposes on every X server.
    desktop_window = desktop_surface = desktop_cr = None
    if True:                                # always paint over stale pixels
        import dev_background
        desktop_attributes = dev_gui.SetWindowAttributes(border_pixel=0,
                                                         override_redirect=1)
        desktop_window = api['create_window'](display, root_window, 0, 0,
                                              width, height, 0, 0, 1, default_visual,
                                              (1 << 9) | (1 << 17),
                                              c.byref(desktop_attributes))
        api['store_name'](display, desktop_window, b'Dev OS Desktop')
        set_atoms(desktop_window, '_NET_WM_WINDOW_TYPE', ['_NET_WM_WINDOW_TYPE_DESKTOP'])
        desktop_surface = cairo.surface_create(display, desktop_window,
                                               default_visual, width, height)
        desktop_cr = cairo.create(desktop_surface)

    lock_attributes = dev_gui.SetWindowAttributes(
        border_pixel=0, override_redirect=1,
        event_mask=(1 << 0) | (1 << 2) | (1 << 6))
    lock_window = api['create_window'](display, root_window, 0, 0, width, height,
                                       0, 0, 1, default_visual,
                                       (1 << 0) | (1 << 2) | (1 << 6) | (1 << 9) | (1 << 11) | (1 << 17),
                                       c.byref(lock_attributes))
    api['store_name'](display, lock_window, b'Dev OS Lock')
    lock_surface = cairo.surface_create(display, lock_window, default_visual,
                                        width, height)
    lock_cr = cairo.create(lock_surface)
    lock_mapped = [False]

    bar_surface = cairo.surface_create(display, bar, default_visual, width, BAR_HEIGHT)
    cr_bar = cairo.create(bar_surface)
    menu_surface = [None]
    cr_menu = [None]

    def menu_surface_for(w, h):
        if menu_surface[0] is None:
            menu_surface[0] = cairo.surface_create(display, menu, menu_visual, w, h)
            cr_menu[0] = cairo.create(menu_surface[0])
        else:
            cairo.surface_set_size(menu_surface[0], w, h)
        return cr_menu[0]

    def text(cr, content, px, py, color, size=12.0, bold=False, alpha=1.0):
        cairo.font_size(cr, size)
        cairo.font_face(cr, dev_gui.FONT, 0, 1 if bold else 0)
        cairo.set_rgba(cr, *color, alpha)
        cairo.move_to(cr, px, py)
        cairo.show_text(cr, content.encode('utf-8'))

    extents = dev_gui.TextExtents()

    def measure(content, size=12.0, bold=False):
        cairo.font_size(cr_bar, size)
        cairo.font_face(cr_bar, dev_gui.FONT, 0, 1 if bold else 0)
        cairo.text_extents(cr_bar, content.encode('utf-8'), c.byref(extents))
        return extents.x_advance

    apps = applications(load_database(root))
    pinned = apps[:pinned_count(len(apps), width)]
    icons_left = PIN_START

    def switch_theme(source):
        nonlocal theme
        theme = dev_theme.load(source)
        apply_theme(theme)
        THEME_SOURCE[0] = source

    def notify_bridge(title, body):
        try:
            sys.path.append('/usr/lib/devos')
            import dev_notifications
            dev_notifications.send(title, body)
        except Exception:
            print('notification: %s — %s' % (title, body), file=sys.stderr)

    host = None
    if extension_dirs:
        host = dev_extensions.Host({
            'settings': lambda: settings,
            'theme': lambda: {'name': theme['name']},
            'screen': lambda: [width, height],
            'notify': notify_bridge,
            'set_theme': switch_theme,
        }).load(extension_dirs)
        for broken in host.report:
            print('extension %s failed: %s' % (broken['id'], broken['error']),
                  file=sys.stderr)
    system_apps = []
    for label, program in (('Terminal', '/usr/bin/xterm'), ('Files', '/usr/bin/dev-files')):
        if Path(program).is_file():
            system_apps.append({'kind': 'app', 'name': program, 'label': label,
                                'comment': 'system application', 'categories': ['System'],
                                'permissions': []})
    system_apps.append({'kind': 'lock', 'name': 'lock', 'label': 'Lock',
                        'comment': 'lock this session', 'categories': ['System'],
                        'permissions': []})
    entries = apps + system_apps + (host.command_entries() if host else [])
    consent = None
    menu_open = False
    clock = ''
    hover = [None]
    tray_right = [None]
    widget_zones = [[]]
    widget_end = [0]
    warned = set()
    panel_state = {}
    toasts = []
    toast_fifo = None
    locked = [bool(os.environ.get('DEVOS_LOCK'))]
    lock_input = ['']

    def hidden(section):
        return bool(host and section in host.hidden)

    def paint_extension(draw, x, y, w, h, tag):
        """Run one extension draw callback inside its clipped box; never fatal.

        The clip is what keeps neighbouring widgets apart: an extension may
        declare 80 pixels but draw at x=200 — nothing lands outside its box.
        """
        cairo.save(cr_bar)
        cairo.rectangle(cr_bar, x, y, w, h)
        cairo.clip(cr_bar)
        painter = dev_extensions.Painter(cairo, cr_bar, x, y, w, h,
                                         dev_gui.THEME_COLORS, extents)
        try:
            draw(painter)
        except Exception as error:
            print('extension %s failed to draw: %s' % (tag, error), file=sys.stderr)
            cairo.set_rgba(cr_bar, 1.0, 0.27, 0.27, 0.35)
            cairo.rounded(cr_bar, x, y, w, h, 4)
            cairo.fill(cr_bar)
        finally:
            cairo.restore(cr_bar)

    def clients():
        found = []
        for window in property_windows(x, api, display, root_window, '_NET_CLIENT_LIST'):
            name = c.c_char_p()
            if window not in (bar, menu) and api['fetch_name'](display, window, c.byref(name)) \
                    and name.value:
                found.append((name.value.decode('utf-8', 'replace'), window))
                x.XFree(name)          # free the pointer X gave, not a bytes copy
        return found

    def place_menu():
        geometry = menu_geometry(width, height, len(entries), consent is not None)
        api['move_resize'](display, menu, geometry['x'], geometry['y'],
                           geometry['width'], geometry['height'])
        menu_surface_for(geometry['width'], geometry['height'])

    def open_menu(state):
        nonlocal menu_open, consent
        menu_open, consent = state, None
        hover[0] = None
        if state:
            place_menu()
            api['map'](display, menu)
            api['raise_window'](display, menu)
            api['grab_pointer'](display, menu, 0, 1 << 2, 1, 1, 0, 0, 0)
        else:
            api['ungrab_pointer'](display, 0)
            api['unmap'](display, menu)

    def draw_lock():
        cairo.set_rgba(lock_cr, *DESIGN['bg'], 1.0)
        cairo.paint(lock_cr)
        lx, ly, lw, lh = lock_layout(width, height)
        radius = dev_theme.corner_radius(dev_gui.CORNERS, 'window', lw, lh)
        cairo.set_rgba(lock_cr, *PALETTE['panel'], 1.0)
        cairo.rounded(lock_cr, lx, ly, lw, lh, radius)
        cairo.fill(lock_cr)
        cairo.set_rgba(lock_cr, *ACCENT, 0.35)
        cairo.set_line_width(lock_cr, 1)
        cairo.rounded(lock_cr, lx + 0.5, ly + 0.5, lw - 1, lh - 1, radius)
        cairo.stroke(lock_cr)
        dev_theme.draw_icon(cairo, lock_cr, dev_gui.ICONS['mark'], lx + 36, ly + 28,
                            DESIGN['green'], dev_gui.THEME_COLORS, 1.5)
        text(lock_cr, 'Locked', lx + 64, ly + 48, DESIGN['white'], 18.0, True)
        text(lock_cr, 'Enter your password to unlock', lx + 36, ly + 78,
             DESIGN['gray'], 11.0)
        entry_y = ly + 104
        cairo.set_rgba(lock_cr, *PALETTE['bg'], 1.0)
        cairo.rounded(lock_cr, lx + 32, entry_y, lw - 64, 36,
                      dev_theme.corner_radius(dev_gui.CORNERS, 'button', lw - 64, 36))
        cairo.fill(lock_cr)
        cairo.set_rgba(lock_cr, *ACCENT, 1.0)
        cairo.set_line_width(lock_cr, 1.2)
        cairo.rounded(lock_cr, lx + 32.6, entry_y + 0.6, lw - 65, 35,
                      max(0.0, dev_theme.corner_radius(dev_gui.CORNERS, 'button',
                                                        lw - 64, 36) - 0.6))
        cairo.stroke(lock_cr)
        shown = '*' * len(lock_input[0]) or 'password'
        text(lock_cr, shown, lx + 44, entry_y + 23,
             DESIGN['white'] if lock_input[0] else DESIGN['gray'], 13.0)
        cairo.surface_flush(lock_surface)
        api['flush'](display)

    def draw_bar():
        nonlocal clock
        # Flat design: near-black base, hairline separator on the top edge.
        cairo.set_rgba(cr_bar, *DESIGN['bg'], 1.0)
        cairo.paint(cr_bar)
        cairo.set_rgba(cr_bar, *DESIGN['line'], 1.0)
        cairo.set_line_width(cr_bar, 1)
        cairo.new_sub_path(cr_bar)
        cairo.line_to(cr_bar, 0, 0.5)
        cairo.line_to(cr_bar, width, 0.5)
        cairo.stroke(cr_bar)
        # Start button per the reference SVG: dark rounded rect outlined in
        # green, vector >_ glyph, white DEVOS lettering, then a separator.
        hovered = hover[0] == 'menu'
        start_r = dev_theme.corner_radius(dev_gui.CORNERS, 'start', PILL_WIDTH, BAR_HEIGHT - 14)
        cairo.set_rgba(cr_bar, *DESIGN['button'], 1.0)
        cairo.rounded(cr_bar, PILL_X, 7, PILL_WIDTH, BAR_HEIGHT - 14, start_r)
        cairo.fill(cr_bar)
        cairo.set_rgba(cr_bar, *DESIGN['green'], 1.0 if hovered else 0.85)
        cairo.set_line_width(cr_bar, 1.5)
        cairo.rounded(cr_bar, PILL_X + 0.75, 7.75, PILL_WIDTH - 1.5, BAR_HEIGHT - 15.5,
                      max(0.0, start_r - 0.75))
        cairo.stroke(cr_bar)
        dev_theme.draw_icon(cairo, cr_bar, dev_gui.ICONS['start'], PILL_X, 7,
                            DESIGN['green'], dev_gui.THEME_COLORS, 1.5)
        text(cr_bar, 'DEVOS', PILL_X + PILL_WIDTH * 0.355, 25.9, DESIGN['white'], 16.0, True)
        separator_x = MENU_END + SEPARATOR_OFF + 0.5
        cairo.set_rgba(cr_bar, *DESIGN['sep'], 1.0)
        cairo.set_line_width(cr_bar, 1.5)
        cairo.new_sub_path(cr_bar)
        cairo.line_to(cr_bar, separator_x, 10)
        cairo.line_to(cr_bar, separator_x, BAR_HEIGHT - 10)
        cairo.stroke(cr_bar)
        # Pinned app icons after the pill: monogram, running dot, active line.
        tasks = clients()
        running, active = pinned_states(pinned, tasks)
        for index, item in enumerate(() if hidden('pinned') else pinned):
            x, y = icons_left + index * (PIN_SIZE + PIN_GAP), 6
            hovered = hover[0] == ('app', index)
            cairo.set_rgba(cr_bar, 1.0, 1.0, 1.0,
                           0.12 if index == active else 0.08 if hovered else 0.04)
            cairo.rounded(cr_bar, x + 0.5, y + 0.5, PIN_SIZE - 1, PIN_SIZE - 1,
                          dev_theme.corner_radius(dev_gui.CORNERS, 'icon', PIN_SIZE - 1,
                                                  PIN_SIZE - 1))
            cairo.fill(cr_bar)
            glyph = monogram(item)
            text(cr_bar, glyph, x + PIN_SIZE / 2 - measure(glyph, 13.0, True) / 2, y + 18.5,
                 DESIGN['white'] if index == active or hovered else DESIGN['gray'], 13.0, True)
            if index == active:
                cairo.set_rgba(cr_bar, *DESIGN['blue'], 1.0)
                cairo.set_line_width(cr_bar, 2)
                cairo.new_sub_path(cr_bar)
                cairo.line_to(cr_bar, x + 8, y + PIN_SIZE - 4)
                cairo.line_to(cr_bar, x + PIN_SIZE - 8, y + PIN_SIZE - 4)
                cairo.stroke(cr_bar)
            elif running[index]:
                cairo.set_rgba(cr_bar, *DESIGN['white'], 0.8)
                cairo.arc(cr_bar, x + PIN_SIZE / 2, y + PIN_SIZE - 4, 1.7, 0, 6.2832)
                cairo.fill(cr_bar)
        # Two-line clock (or an extension override), separator, tray glyphs.
        clock = time_text(settings=settings)
        date = date_text(settings=settings)
        right = width - CLOCK_PAD
        time_width, date_width = measure(clock, 13.0, True), measure(date, 8.5)
        clock_width = 0
        override = host.clock_override if host else None
        if hidden('clock'):
            pass
        elif override:
            clock_width = override['width']
            paint_extension(override['draw'], right - clock_width, 0, clock_width,
                            BAR_HEIGHT, override['ext'] + ':clock')
        else:
            clock_width = max(time_width, date_width)
            text(cr_bar, clock, right - time_width, 18, DESIGN['white'], 13.0, True)
            text(cr_bar, date, right - date_width, 31, DESIGN['gray'], 8.5)
        separator = right - clock_width - 14 + 0.5
        cairo.set_rgba(cr_bar, *DESIGN['sep'], 1.0)
        cairo.set_line_width(cr_bar, 1)
        cairo.new_sub_path(cr_bar)
        cairo.line_to(cr_bar, separator, 10)
        cairo.line_to(cr_bar, separator, BAR_HEIGHT - 10)
        cairo.stroke(cr_bar)
        draw_icon = dev_theme.draw_icon
        colors = dev_gui.THEME_COLORS
        state, detail = network_state()
        if not hidden('tray'):
            draw_icon(cairo, cr_bar, dev_gui.ICONS['wifi'], separator - 32, 12,
                      DESIGN['green'] if state == 'online' else DESIGN['gray'],
                      colors, 1.4)
            text(cr_bar, detail, separator - 190, 24, DESIGN['gray'], 9.0)
            draw_icon(cairo, cr_bar, dev_gui.ICONS['volume'], separator - 52, 12,
                      DESIGN['gray'], colors, 1.4)
            draw_icon(cairo, cr_bar, dev_gui.ICONS['bell'], separator - 72, 12,
                      DESIGN['gray'], colors, 1.4)
        tray_right[0] = None
        if host and host.tray:
            tray_right[0] = separator - TRAY_LEFT
            for index, item in enumerate(host.tray):
                icon = item['icon'] if not isinstance(item['icon'], str)                     else dev_gui.ICONS[item['icon']]
                dev_theme.draw_icon(cairo, cr_bar, icon,
                                    tray_right[0] - TRAY_PITCH * index - TRAY_SIZE, 12,
                                    colors[item['color']], colors, 1.4)
        widget_end[0] = MENU_END + SEPARATOR_OFF + 4
        if pinned and not hidden('pinned'):
            widget_end[0] = PIN_START + len(pinned) * (PIN_SIZE + PIN_GAP)
        widget_zones[0] = []
        if host:
            def warn_dropped(widget):
                key = widget['ext'] + ':' + widget['id']
                if key not in warned:
                    warned.add(key)
                    print('extension widget %s does not fit and is hidden' % key,
                          file=sys.stderr)

            def overflow_marker(x):
                cairo.set_rgba(cr_bar, *DESIGN['red'], 0.9)
                cairo.rounded(cr_bar, x, 7, 14, BAR_HEIGHT - 14, 4)
                cairo.fill(cr_bar)
                text(cr_bar, '!', x + 5, 25, DESIGN['white'], 11.5, True)

            base = separator - TRAY_LEFT - TRAY_PITCH * len(host.tray)
            right = [(index, widget) for index, widget in enumerate(host.widgets)
                     if widget['zone'] == 'right']
            plan = dev_extensions.zone_layout(base - widget_end[0],
                                              [widget['width'] for _, widget in right])
            dropped = 0
            for (index, widget), fitted in zip(right, plan):
                if fitted is None:
                    dropped += 1
                    warn_dropped(widget)
                    continue
                base -= fitted
                paint_extension(widget['draw'], base, 0, fitted, BAR_HEIGHT,
                                widget['ext'] + ':' + widget['id'])
                widget_zones[0].append((base, base + fitted, index))
                base -= dev_extensions.ZONE_GAP
            if dropped:
                overflow_marker(base - 18)
            left = [(index, widget) for index, widget in enumerate(host.widgets)
                    if widget['zone'] == 'left']
            plan = dev_extensions.zone_layout(base - widget_end[0],
                                              [widget['width'] for _, widget in left])
            cursor, dropped = widget_end[0], 0
            for (index, widget), fitted in zip(left, plan):
                if fitted is None:
                    dropped += 1
                    warn_dropped(widget)
                    continue
                paint_extension(widget['draw'], cursor, 0, fitted, BAR_HEIGHT,
                                widget['ext'] + ':' + widget['id'])
                widget_zones[0].append((cursor, cursor + fitted, index))
                cursor += fitted + dev_extensions.ZONE_GAP
            if dropped:
                overflow_marker(cursor + 4)
        for x, y, title, body, alpha in toast_layout(toasts, time.monotonic(), width, height):
            cairo.set_rgba(cr_bar, *PALETTE['chrome'], min(alpha, 0.96))
            cairo.rounded(cr_bar, x, y, 284, 64, 10)
            cairo.fill(cr_bar)
            cairo.set_rgba(cr_bar, *ACCENT, min(alpha, 0.9))
            cairo.set_line_width(cr_bar, 1)
            cairo.rounded(cr_bar, x + 0.5, y + 0.5, 283, 63, 10)
            cairo.stroke(cr_bar)
            if title:
                text(cr_bar, title, x + 14, y + 24, DESIGN['white'], 12.0, True, alpha=alpha)
            if body:
                text(cr_bar, body, x + 14, y + 44, DESIGN['gray'], 10.5, alpha=alpha)
        cairo.surface_flush(bar_surface)
        api['flush'](display)
        return tasks

    def draw_menu(geometry):
        cr = menu_surface_for(geometry['width'], geometry['height'])
        w, h = geometry['width'], geometry['height']
        corners = dev_gui.CORNERS
        menu_r = dev_theme.corner_radius(corners, 'menu', w, h - 2)
        if argb:
            cairo.set_rgba(cr, 0, 0, 0, 0)
            cairo.paint(cr)
            cairo.set_rgba(cr, 0, 0, 0, 0.45)
            cairo.rounded(cr, 2, 3, w - 4, h, min(menu_r + 2, h / 2))
            cairo.fill(cr)
        else:
            # Without alpha the desktop behind is simulated so the rounded
            # corners stay visible in captured evidence.
            cairo.set_rgba(cr, *DESIGN['bg'], 1.0)
            cairo.paint(cr)
        cairo.set_rgba(cr, *PALETTE['panel'], 0.97)
        cairo.rounded(cr, 0, 0, w, h - 2, menu_r)
        cairo.fill(cr)
        cairo.set_rgba(cr, *ACCENT, 0.35)
        cairo.set_line_width(cr, 1)
        cairo.rounded(cr, 0.5, 0.5, w - 1, h - 3, menu_r)
        cairo.stroke(cr)
        cairo.set_rgba(cr, *ACCENT, 1.0)
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
        for index, item in enumerate(entries):
            hovered = hover[0] == ('item', index)
            if hovered or (consent is not None and item is consent):
                cairo.set_rgba(cr, *ACCENT, 0.16 if hovered else 0.10)
                cairo.rounded(cr, 4, top + 2, w - 8, MENU_ITEM_HEIGHT - 4,
                              dev_theme.corner_radius(corners, 'row', w - 8,
                                                      MENU_ITEM_HEIGHT - 4))
                cairo.fill(cr)
            text(cr, item['label'], 14, top + 17, PALETTE['text'], 12.5, True)
            detail = ' · '.join(item['categories'][:2] +
                                [','.join(item['permissions']) or 'no permissions'])
            text(cr, truncate(detail, lambda s: measure(s, 10.0), w - 30), 26, top + 31,
                 PALETTE['dim'], 10.0)
            top += MENU_ITEM_HEIGHT
        if consent:
            cairo.set_rgba(cr, *ACCENT, 0.08)
            cairo.rounded(cr, 4, top + 2, w - 8, CONSENT_HEIGHT - 6,
                          dev_theme.corner_radius(corners, 'row', w - 8, CONSENT_HEIGHT - 6))
            cairo.fill(cr)
            text(cr, 'Open ' + truncate(consent['label'], lambda s: measure(s, 12.0, True), 170)
                 + '?', 14, top + 19, PALETTE['text'], 12.0, True)
            text(cr, truncate(grant_for(consent), lambda s: measure(s, 10.0), 196)
                 or 'no permissions', 14, top + 37, PALETTE['dim'], 10.0)
            fill = 1.0 if hover[0] == 'allow' else 0.9
            cairo.set_rgba(cr, *ACCENT, fill)
            cairo.rounded(cr, ALLOW_X, top + 12, 64, 22,
                          dev_theme.corner_radius(corners, 'chip', 64, 22))
            cairo.fill(cr)
            text(cr, 'ALLOW', ALLOW_X + 14, top + 28, PALETTE['accent_dark'], 10.5, True)
            text(cr, 'cancel', CANCEL_X, top + 28,
                 PALETTE['text'] if hover[0] == 'cancel' else PALETTE['dim'], 10.5)
        cairo.surface_flush(menu_surface[0])
        api['flush'](display)

    def panel_window(handle):
        """Create (once) the override-redirect window behind a panel."""
        spec = handle.spec
        y = height - BAR_HEIGHT - spec['height'] - 8
        info = dev_gui.VisualInfo()
        visual = default_visual
        if shots is None and api['match_visual'](display, 0, 32, 4, c.byref(info)):
            colormap = api['create_colormap'](display, root_window, info.visual, 0)
            attributes = dev_gui.SetWindowAttributes(border_pixel=0, colormap=colormap,
                                                     override_redirect=1, event_mask=1 << 15)
            window = api['create_window'](display, root_window, spec['x'], y,
                                          spec['width'], spec['height'], 0, 32, 1,
                                          info.visual, 1 | 2 | 0x400 | 0x800,
                                          c.byref(attributes))
            visual = info.visual
        else:
            window = api['create'](display, root_window, spec['x'], y, spec['width'],
                                   spec['height'], 1, 0x10151d, 0x10151d)
        api['store_name'](display, window, ('Dev OS Panel ' + spec['id']).encode())
        api['select_input'](display, window, (1 << 15) | (1 << 2) | (1 << 6))
        surface = cairo.surface_create(display, window, visual, spec['width'], spec['height'])
        return {'window': window, 'surface': surface, 'cr': cairo.create(surface)}

    def service_panels():
        """Apply show/hide requests and repaint the visible panels."""
        if not host:
            return
        for handle in host.panels:
            request = handle.slot['request']
            handle.slot['request'] = None
            state = panel_state.get(handle.spec['id'])
            if request in ('show', 'toggle') and not handle.slot['visible']:
                if state is None:
                    state = panel_state[handle.spec['id']] = panel_window(handle)
                api['map'](display, state['window'])
                api['raise_window'](display, state['window'])
                api['grab_pointer'](display, state['window'], 0, 1 << 2, 1, 1, 0, 0, 0)
                handle.slot['visible'] = True
            elif request in ('hide', 'toggle') and handle.slot['visible'] and state:
                api['ungrab_pointer'](display, 0)
                api['unmap'](display, state['window'])
                handle.slot['visible'] = False
            if handle.slot['visible'] and state:
                cairo.save(state['cr'])
                cairo.rectangle(state['cr'], 0, 0, handle.spec['width'],
                                handle.spec['height'])
                cairo.clip(state['cr'])
                painter = dev_extensions.Painter(cairo, state['cr'], 0, 0,
                                                 handle.spec['width'],
                                                 handle.spec['height'],
                                                 dev_gui.THEME_COLORS, extents)
                try:
                    handle.spec['draw'](painter)
                except Exception as error:
                    print('extension %s panel failed to draw: %s'
                          % (handle.spec['id'], error), file=sys.stderr)
                finally:
                    cairo.restore(state['cr'])
                cairo.surface_flush(state['surface'])
        api['flush'](display)

    api['select_input'](display, bar, (1 << 15) | (1 << 2) | (1 << 3) | (1 << 6))
    api['select_input'](display, menu, (1 << 15) | (1 << 2) | (1 << 6))
    try:
        fifo_path = '/tmp/devos-notifications-%d' % os.getuid()
        os.mkfifo(fifo_path, 0o644)
    except FileExistsError:
        pass
    try:
        toast_fifo = os.open(fifo_path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        toast_fifo = None

    api['select_input'](display, root_window, 1 << 18)
    if desktop_window:
        api['map'](display, desktop_window)

    def paint_desktop():
        # Repainted every loop pass like the bar: XWayland drops pixels
        # drawn before a window is mapped and the first use of a fresh
        # image surface, so steady redraw is the only reliable recipe.
        dev_background.render(cairo, desktop_cr, width, height,
                              settings['desktop.background'], DESIGN['bg'])
        cairo.surface_flush(desktop_surface)
        api['flush'](display)

    api['map'](display, bar)
    api['raise_window'](display, bar)          # no WM: map order is not z-order
    api['move'](display, bar, 0, height - BAR_HEIGHT)  # openbox docks float otherwise
    running = True
    started = time.monotonic()
    captured = shots is None
    while running:
        now = time.monotonic()
        if toast_fifo is not None:
            try:
                for line in os.read(toast_fifo, 8192).decode('utf-8', 'replace').splitlines():
                    if not line.strip():
                        continue
                    try:
                        note = json.loads(line)
                        toasts.append({'title': str(note.get('title', ''))[:40],
                                       'body': str(note.get('body', ''))[:80],
                                       'at': now})
                    except ValueError:
                        toasts.append({'title': line[:40], 'body': '', 'at': now})
            except BlockingIOError:
                pass
            toasts[:] = toasts[-4:]
        geometry = menu_geometry(width, height, len(entries), consent is not None)
        if desktop_window:
            paint_desktop()
        if locked[0] and not lock_mapped[0]:
            api['map'](display, lock_window)
            api['raise_window'](display, lock_window)
            api['set_input_focus'](display, lock_window, 1, 0)
            lock_mapped[0] = True
        elif not locked[0] and lock_mapped[0]:
            api['unmap'](display, lock_window)
            lock_mapped[0] = False
        if locked[0]:
            draw_lock()
        api['raise_window'](display, bar)     # chrome above WM-managed windows
        tasks = draw_bar()
        if menu_open:
            draw_menu(geometry)
        while api['pending'](display):
            event = dev_gui.XEvent()
            api['next_event'](display, c.byref(event))
            kind = event.any.type
            if (kind == 33 and event.client.message_type == protocols
                    and event.client.data[0] == delete):
                running = False
            elif kind == 2 and locked[0] and event.key.window in (bar, lock_window):
                keysym = c.c_ulong()
                buffer = c.create_string_buffer(16)
                api['lookup_string'](c.byref(event.key), buffer, 16,
                                     c.byref(keysym), None)
                char = buffer.value.decode('ascii', 'ignore')[:1]
                symbol = keysym.value
                if symbol == 0xFF0D:                     # Return: verify via sudo
                    if password_ok(lock_input[0]):
                        locked[0] = False
                    lock_input[0] = ''
                elif symbol == 0xFF1B:                    # Escape clears
                    lock_input[0] = ''
                elif symbol == 0xFF08:
                    lock_input[0] = lock_input[0][:-1]
                elif char and 32 <= ord(char) < 127 and len(lock_input[0]) < 64:
                    lock_input[0] += char
            elif kind in (4, 5, 6) and locked[0]                     and event.button.window in (bar, lock_window):
                continue                                  # clicks are dead while locked
            elif kind in (4, 5, 6) and event.button.window == bar:
                position = event.button
                tray_count = len(host.tray) if host else 0
                if kind == 6 and not locked[0]:
                    hover[0] = hover_key('bar', position.x, position.y, width=width,
                                         app_count=len(pinned), tray_right=tray_right[0],
                                         tray_count=tray_count)
                elif kind == 4:
                    for panel_handle in (host.panels if host else []):
                        if panel_handle.slot['visible']:
                            panel_handle.slot['request'] = 'hide'
                    hit, index = bar_hit(width, position.x, len(pinned),
                                         tray_right[0], tray_count)
                    if hit is None and host:
                        for start, end, widget_index in widget_zones[0]:
                            if start <= position.x < end:
                                widget = host.widgets[widget_index]
                                if widget['on_click']:
                                    try:
                                        widget['on_click']()
                                    except Exception as error:
                                        print('widget %s failed: %s'
                                              % (widget['id'], error), file=sys.stderr)
                                break
                    if hit == 'tray' and host and index < len(host.tray):
                        try:
                            host.tray_click(index)
                        except Exception as error:
                            print('tray command failed: %s' % error, file=sys.stderr)
                    elif hit == 'menu':
                        open_menu(not menu_open)
                    elif hit == 'app' and index is not None and index < len(pinned):
                        target = pinned[index]
                        window = window_for(target, tasks)
                        if window:
                            api['raise_window'](display, window)
                            api['set_input_focus'](display, window, 1, 0)
                        else:
                            # A pinned app with no open window opens straight
                            # into its consent row; Allow launches it as usual.
                            open_menu(True)
                            consent = target
                            place_menu()
            elif host and kind in (4, 6) and any(
                    event.button.window == state['window']
                    for state in panel_state.values()):
                action = 'click' if kind == 4 else 'hover'
                for handle in host.panels:
                    state = panel_state.get(handle.spec['id'])
                    if not state or state['window'] != event.button.window:
                        continue
                    if handle.spec['on_event']:
                        try:
                            handle.spec['on_event'](action, event.button.x, event.button.y)
                        except Exception as error:
                            print('panel %s failed: %s' % (handle.spec['id'], error),
                                  file=sys.stderr)
            elif kind in (4, 6) and event.button.window == menu:
                position = event.button
                if kind == 6:
                    hover[0] = hover_key('menu', position.x, position.y,
                                         item_count=len(entries), consent=consent is not None)
                else:
                    index = item_at(len(entries), position.y, consent is not None)
                    choice = consent_choice(position.x, position.y, len(entries),
                                            consent is not None)
                    if choice == 'allow':
                        environment = dict(os.environ)
                        if THEME_SOURCE[0]:
                            # Launched apps inherit the active theme and font.
                            environment['DEVOS_THEME'] = THEME_SOURCE[0]
                        environment['DEVOS_FONT'] = settings.get(
                            'font.family', dev_settings.DEFAULTS['font.family'])
                        subprocess.Popen(launch_command(dev, root, consent),
                                         start_new_session=True, env=environment,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        open_menu(False)
                    elif choice == 'cancel':
                        consent = None
                        draw_menu(menu_geometry(width, height, len(items), False))
                    elif index is not None and index >= 0 and not consent:
                        entry = entries[index]
                        if entry.get('kind') == 'lock':
                            locked[0] = True
                            lock_input[0] = ''
                            open_menu(False)
                            continue
                        if entry.get('kind') == 'app' and entry['name'].startswith('/usr/bin/'):
                            try:                      # trusted system apps launch
                                subprocess.Popen([entry['name']], env=os.environ,  # directly
                                                 start_new_session=True,
                                                 stdout=subprocess.DEVNULL,
                                                 stderr=subprocess.DEVNULL)
                            except OSError as error:
                                print('launch %s failed: %s' % (entry['name'], error),
                                      file=sys.stderr)
                            open_menu(False)
                            continue
                        if entry.get('kind') == 'command' and host:
                            try:
                                host.run_command(entries[index]['name'])
                            except Exception as error:
                                print('command %s failed: %s'
                                      % (entries[index]['name'], error), file=sys.stderr)
                        elif entries[index].get('kind') != 'app':
                            consent = entries[index]
                            draw_menu(menu_geometry(width, height, len(entries), True))
        if not captured and time.monotonic() - started >= 1.0:
            captured = True
            api['sync'](display, 0)
            screenshot(x, api, display, bar, shots[0], width, BAR_HEIGHT)
            if not menu_open:
                open_menu(True)
            consent = apps[0] if apps else None
            place_menu()
            geometry = menu_geometry(width, height, len(entries), consent is not None)
            draw_menu(geometry)
            # XWayland needs a compositor round trip after a resize before the
            # window has a capturable surface again; redraw onto the settled
            # surface right before capturing it.
            api['sync'](display, 0)
            time.sleep(0.6)
            api['sync'](display, 0)
            draw_menu(geometry)
            api['sync'](display, 0)
            if locked[0]:
                screenshot(x, api, display, lock_window,
                           shots[0].rsplit('-bar', 1)[0] + '-lock.png', width, height)
                running = False
                continue
            screenshot(x, api, display, menu, shots[1], geometry['width'], geometry['height'])
            if desktop_window:
                screenshot(x, api, display, desktop_window,
                           shots[0].rsplit('-bar', 1)[0] + '-desktop.png',
                           width, height)
            for handle in (host.panels if host else []):
                if handle.slot['visible']:
                    state = panel_state[handle.spec['id']]
                    api['sync'](display, 0)
                    screenshot(x, api, display, state['window'],
                               shots[0].rsplit('-bar', 1)[0] + '-panel.png',
                               handle.spec['width'], handle.spec['height'])
                    break
            running = False
        service_panels()
        time.sleep(0.2)
    counts = (list(host.loaded), len(host.commands), len(host.widgets),
              len(host.panels)) if host else ([], 0, 0, 0)
    if host:
        for handle in host.panels:
            handle.slot['request'] = 'hide'
        service_panels()
        host.unload()
    return {'screen': [width, height], 'applications': len(apps), 'pinned': len(pinned),
            'theme': theme['name'], 'extensions': counts[0], 'commands': counts[1],
            'widgets': counts[2], 'panels': counts[3]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='/', help='target root (default: /)')
    parser.add_argument('--dev', default='dev', help='dev command used for launches')
    parser.add_argument('--settings', type=Path,
                        help='settings.json override (default: /etc then ~/.config/devos, '
                             'or $DEVOS_SETTINGS)')
    parser.add_argument('--theme', type=Path,
                        help='theme file or name overriding the settings ('
                             'default: $DEVOS_THEME or the settings theme)')
    parser.add_argument('--extensions', type=Path,
                        help='extensions directory override (default: '
                             '~/.config/devos/extensions then /usr/share/devos/extensions)')
    parser.add_argument('--screenshot-prefix', type=Path,
                        help='capture bar and menu PNGs once, then exit')
    args = parser.parse_args()
    shots = None
    if args.screenshot_prefix:
        args.screenshot_prefix.parent.mkdir(parents=True, exist_ok=True)
        shots = (str(args.screenshot_prefix) + '-bar.png', str(args.screenshot_prefix) + '-menu.png')
    try:
        settings = dev_settings.active(args.settings or os.environ.get('DEVOS_SETTINGS'))
        settings_dir = args.settings.parent if args.settings else None
        theme, theme_source = theme_from(args.theme, settings, settings_dir)
    except (OSError, ValueError) as error:
        raise SystemExit('Could not load settings or theme: %s' % error)
    dev_gui.set_font(settings['font.family'])
    extension_dirs = [args.extensions] if args.extensions else \
        [Path.home() / '.config/devos/extensions', Path('/usr/share/devos/extensions')]
    result = run(args.root, dev=args.dev, shots=shots, theme=theme,
                 theme_source=theme_source, settings=settings,
                 extension_dirs=extension_dirs)
    print(json.dumps(result))
    if shots:
        print('Screenshots: ' + ' '.join(shots))


if __name__ == '__main__':
    main()
