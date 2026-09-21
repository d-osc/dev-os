#!/usr/bin/python3
"""Dev OS desktop shell: a 24px taskbar with an application menu and clock.

Rendering and X11 plumbing come from the shared dev_gui toolkit (ctypes +
Cairo): anti-aliased TrueType text, gradients, rounded corners, hover
feedback. The bar reserves the bottom 24 pixels with EWMH struts; the menu is
a translucent ARGB popup when the server offers that visual (evidence capture
uses plain windows because the test display's XWayland cannot capture ARGB or
override-redirect windows). Launching an app needs an explicit per-launch
consent and then runs `dev launch <name> --allow <declared permissions>`: the
shell never widens a permission set and keeps no grants. It is a normal user
process for an X11 session; the OS image does not start it automatically yet.
"""
import argparse
import ctypes as c
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.append('/usr/lib/devos')
import dev_gui  # noqa: E402

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
PALETTE = dev_gui.PALETTE
ACCENT = PALETTE['accent']


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


def hover_key(area, x, y, *, task_count=0, item_count=0, consent=False):
    """Which actionable element the pointer is over, for hover feedback."""
    if area == 'bar':
        if x < MENU_BUTTON_WIDTH:
            return 'menu'
        left = MENU_BUTTON_WIDTH + 1
        for index in range(task_count):
            if left <= x < left + TASK_BUTTON_WIDTH - 8:
                return ('task', index)
            left += TASK_BUTTON_WIDTH
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
    x, api = dev_gui.connect()
    cairo = dev_gui.Cairo()
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
        menu = api['create'](display, root_window, 0, 0, 100, 100, 1, 0x101b2c, 0x101b2c)
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

    items = applications(load_database(root))
    consent = None
    menu_open = False
    clock = ''
    hover = [None]

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
        hover[0] = None
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
        cairo.set_rgba(cr_bar, *ACCENT, 0.30)
        cairo.set_line_width(cr_bar, 1)
        cairo.new_sub_path(cr_bar)
        cairo.line_to(cr_bar, 0, 0.5)
        cairo.line_to(cr_bar, width, 0.5)
        cairo.stroke(cr_bar)
        # MENU pill button; brighter when hovered.
        cairo.set_rgba(cr_bar, *ACCENT, 0.26 if hover[0] == 'menu' else 0.14)
        cairo.rounded(cr_bar, 4, 3, MENU_BUTTON_WIDTH - 10, BAR_HEIGHT - 6, 8)
        cairo.fill(cr_bar)
        text(cr_bar, 'MENU', 16, 16, PALETTE['text'] if hover[0] == 'menu' else ACCENT,
             11.0, True)
        left = MENU_BUTTON_WIDTH + 1
        tasks = clients()
        room = int(max(0, (width - MENU_BUTTON_WIDTH - measure(clock_text(), 11.0) - 40)
                       // TASK_BUTTON_WIDTH))
        for index, (title, window) in enumerate(tasks[:room]):
            hovered = hover[0] == ('task', index)
            cairo.set_rgba(cr_bar, 1.0, 1.0, 1.0, 0.14 if hovered else 0.06)
            cairo.rounded(cr_bar, left + 2, 3, TASK_BUTTON_WIDTH - 12, BAR_HEIGHT - 6, 7)
            cairo.fill(cr_bar)
            cairo.set_rgba(cr_bar, 1.0, 1.0, 1.0, 0.22 if hovered else 0.10)
            cairo.set_line_width(cr_bar, 1)
            cairo.rounded(cr_bar, left + 2.5, 3.5, TASK_BUTTON_WIDTH - 13, BAR_HEIGHT - 7, 7)
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
        cairo.set_rgba(cr, *PALETTE['panel'], 0.97)
        cairo.rounded(cr, 0, 0, w, h - 2, MENU_RADIUS)
        cairo.fill(cr)
        cairo.set_rgba(cr, *ACCENT, 0.35)
        cairo.set_line_width(cr, 1)
        cairo.rounded(cr, 0.5, 0.5, w - 1, h - 3, MENU_RADIUS)
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
        for index, item in enumerate(items):
            hovered = hover[0] == ('item', index)
            if hovered or (consent is not None and item is consent):
                cairo.set_rgba(cr, *ACCENT, 0.16 if hovered else 0.10)
                cairo.rounded(cr, 4, top + 2, w - 8, MENU_ITEM_HEIGHT - 4, 8)
                cairo.fill(cr)
            text(cr, item['label'], 14, top + 17, PALETTE['text'], 12.5, True)
            detail = ' · '.join(item['categories'][:2] +
                                [','.join(item['permissions']) or 'no permissions'])
            text(cr, truncate(detail, lambda s: measure(s, 10.0), w - 30), 26, top + 31,
                 PALETTE['dim'], 10.0)
            top += MENU_ITEM_HEIGHT
        if consent:
            cairo.set_rgba(cr, *ACCENT, 0.08)
            cairo.rounded(cr, 4, top + 2, w - 8, CONSENT_HEIGHT - 6, 8)
            cairo.fill(cr)
            text(cr, 'Open ' + truncate(consent['label'], lambda s: measure(s, 12.0, True), 170)
                 + '?', 14, top + 19, PALETTE['text'], 12.0, True)
            text(cr, truncate(grant_for(consent), lambda s: measure(s, 10.0), 196)
                 or 'no permissions', 14, top + 37, PALETTE['dim'], 10.0)
            fill = 1.0 if hover[0] == 'allow' else 0.9
            cairo.set_rgba(cr, *ACCENT, fill)
            cairo.rounded(cr, ALLOW_X, top + 12, 64, 22, 11)
            cairo.fill(cr)
            text(cr, 'ALLOW', ALLOW_X + 14, top + 28, PALETTE['accent_dark'], 10.5, True)
            text(cr, 'cancel', CANCEL_X, top + 28,
                 PALETTE['text'] if hover[0] == 'cancel' else PALETTE['dim'], 10.5)
        cairo.surface_flush(menu_surface[0])
        api['flush'](display)

    api['select_input'](display, bar, (1 << 15) | (1 << 2) | (1 << 3) | (1 << 6))
    api['select_input'](display, menu, (1 << 15) | (1 << 2) | (1 << 6))
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
            event = dev_gui.XEvent()
            api['next_event'](display, c.byref(event))
            kind = event.any.type
            if (kind == 33 and event.client.message_type == protocols
                    and event.client.data[0] == delete):
                running = False
            elif kind in (4, 5, 6) and event.button.window == bar:
                position = event.button
                if kind == 6:
                    hover[0] = hover_key('bar', position.x, position.y, task_count=len(tasks))
                elif kind == 4:
                    hit, index = bar_hit(width, clock, position.x, len(tasks))
                    if hit == 'menu':
                        open_menu(not menu_open)
                    elif hit == 'task' and index < len(tasks):
                        api['raise_window'](display, tasks[index][1])
                        api['set_input_focus'](display, tasks[index][1], 1, 0)
            elif kind in (4, 6) and event.button.window == menu:
                position = event.button
                if kind == 6:
                    hover[0] = hover_key('menu', position.x, position.y,
                                         item_count=len(items), consent=consent is not None)
                else:
                    index = item_at(len(items), position.y, consent is not None)
                    choice = consent_choice(position.x, position.y, len(items),
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
