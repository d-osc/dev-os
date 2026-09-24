#!/usr/bin/python3
"""Files: the minimal Dev OS file manager, drawn with the shared toolkit.

A path bar with an Up button, directories first with counts, file sizes in
human units, and a click to descend. Nothing is ever written or executed —
a browser only, in the house style.
"""
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.append('/usr/lib/devos')
import dev_gui  # noqa: E402
import dev_settings  # noqa: E402

ROW_HEIGHT = 30
LIST_TOP = 112
WIDTH, HEIGHT = 640, 460


def entries(directory):
    """(name, is_dir, human size) for one directory, dirs first, sorted."""
    directory = Path(directory)
    found = []
    try:
        children = sorted(directory.iterdir(), key=lambda item: item.name.lower())
    except OSError:
        return None, []
    for child in children:
        try:
            is_dir = child.is_dir()
        except OSError:
            continue
        if is_dir:
            try:
                count = sum(1 for _ in child.iterdir())
            except OSError:
                count = 0
            found.append((child.name, True, '%d items' % count))
        else:
            try:
                size = child.stat().st_size
            except OSError:
                size = 0
            found.append((child.name, False, human(size)))
    found.sort(key=lambda item: (not item[1], item[0].lower()))
    return str(directory), found


def human(size):
    """A human-readable byte size."""
    for unit in ('B', 'KiB', 'MiB', 'GiB'):
        if size < 1024 or unit == 'GiB':
            return '%d %s' % (size, unit)
        size //= 1024
    return '%d GiB' % size


def room_for(height):
    """How many rows fit in the list area."""
    return max(1, (height - LIST_TOP - 50) // ROW_HEIGHT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', default='~', help='directory to open first')
    parser.add_argument('--test', action='store_true',
                        help='render once, capture a PNG, print JSON, exit')
    parser.add_argument('--label-thai', action='store_true',
                        help='test mode: put a Kedmanee-typed Thai label in the path bar')
    args = parser.parse_args()
    current = str(Path(args.start).expanduser())
    if not Path(current).is_dir():
        current = '/'

    toolkit = dev_gui.Toolkit()
    window = dev_gui.Window(toolkit, WIDTH, HEIGHT, title='Files', x=120, y=90)
    try:
        thai = bool(dev_settings.active().get('input.thai'))
    except Exception:
        thai = False
    path_entry = window.add_entry(16, 46, WIDTH - 130, 32, label='Path', thai=thai)
    up_button = window.add_button('Up', WIDTH - 100, 46, 80, 32)
    state = {'dir': current, 'rows': []}

    def reload(path):
        state['dir'], state['rows'] = entries(path)
        path_entry.text = state['dir'] or ''
        window._dirty = True

    def go_up(_x=None, _y=None):
        parent = str(Path(state['dir']).parent)
        if parent != state['dir']:
            reload(parent)

    up_button.callback = go_up
    reload(state['dir'])
    if args.label_thai:
        for character in 'l;kdk;':
            path_entry.feed(0, character)

    def row_at(x, y):
        if x < 8 or x > WIDTH - 16:
            return None
        row = int((y - LIST_TOP) // ROW_HEIGHT)
        rows = state['rows'][:room_for(window.height)]
        return rows[row][0] if 0 <= row < len(rows) else None

    def draw_files(win):
        cr, tk, cairo = win.cr, toolkit, toolkit.cairo
        tk.text(cr, 'FILES', 16, 72, dev_gui.PALETTE['dim'], 10.5, True)
        tk.text(cr, '%d entries' % len(state['rows']), WIDTH - 120, 72,
                dev_gui.PALETTE['dim'], 10.5)
        for name, is_dir, detail in state['rows'][:room_for(win.height)]:
            y = LIST_TOP + state['rows'].index((name, is_dir, detail)) * ROW_HEIGHT
            color = dev_gui.PALETTE['accent'] if is_dir else dev_gui.PALETTE['text']
            tk.text(cr, ('/  ' if is_dir else '   ') + name, 20, y + 4, color, 12.5, is_dir)
            tk.text(cr, detail, WIDTH - 24 - len(detail) * 6, y + 4,
                    dev_gui.PALETTE['dim'], 10.5)

    window.draw_callback = draw_files

    def clicked(x, y):
        name = row_at(x, y)
        if name:
            target = Path(state['dir']) / name
            if target.is_dir():
                reload(str(target))

    window.on_click = clicked
    window.show()
    if args.test:
        import json as _json
        data = Path(os.environ.get('DEVOS_DATA_DIR', '/tmp')) / 'files.png'
        window.run(on_tick_capture=(1.2, data))
        print(_json.dumps({'entries': len(state['rows']),
                           'rows': [row[0] for row in state['rows'][:8]],
                           'dir': state['dir']}))
    else:
        window.run()


if __name__ == '__main__':
    main()
