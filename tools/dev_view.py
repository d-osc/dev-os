#!/usr/bin/python3
"""View: the minimal Dev OS image viewer — PNG through cairo.

Lists images under the pictures directory, shows the selected one scaled
to fit the canvas with the shared toolkit, and steps through the set
with Prev/Next. listing() and fit() are pure for unit tests; the JPEG
path is honest about needing cairo's jpeg loader at runtime.
"""
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.append('/usr/lib/devos')
import dev_gui  # noqa: E402

WIDTH, HEIGHT = 620, 480
LIST_TOP = 104
ROW_HEIGHT = 28
CANVAS_TOP = 230
EXTENSIONS = ('.png', '.jpg', '.jpeg')


def listing(directory):
    """Image file names under one directory, sorted; None when unreadable."""
    directory = Path(directory)
    try:
        found = sorted((child.name for child in directory.iterdir()
                        if child.suffix.lower() in EXTENSIONS),
                       key=str.lower)
    except OSError:
        return None
    return found


def fit(image_w, image_h, box_w, box_h):
    """(scale, dx, dy) centering an image inside a box, never stretched."""
    if image_w <= 0 or image_h <= 0 or box_w <= 0 or box_h <= 0:
        return 1.0, 0.0, 0.0
    scale = min(box_w / image_w, box_h / image_h)
    return scale, (box_w - image_w * scale) / 2, (box_h - image_h * scale) / 2


def row_at(y, names, height):
    """The image name for one click on the list, or None."""
    room = max(1, (CANVAS_TOP - LIST_TOP - 8) // ROW_HEIGHT)
    row = int((y - LIST_TOP) // ROW_HEIGHT)
    visible = names[:room]
    return visible[row] if 0 <= row < len(visible) else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pictures', default='~/Pictures',
                        help='directory to list')
    parser.add_argument('image', nargs='?', help='open this file first')
    parser.add_argument('--test', action='store_true',
                        help='render once, capture a PNG, print JSON, exit')
    args = parser.parse_args()
    directory = str(Path(args.pictures).expanduser())
    state = {'dir': directory, 'names': [], 'current': None, 'note': 'no image'}

    toolkit = dev_gui.Toolkit()
    window = dev_gui.Window(toolkit, WIDTH, HEIGHT, title='View', x=150, y=96)

    def reload():
        state['names'] = listing(directory) or []
        wanted = args.image if args.image else (
            state['names'][0] if state['names'] else None)
        state['current'] = wanted if wanted in state['names'] else (
            state['names'][0] if state['names'] else None)
        window._dirty = True

    def step(delta):
        if not state['names']:
            return
        index = state['names'].index(state['current']) \
            if state['current'] in state['names'] else 0
        state['current'] = state['names'][(index + delta) % len(state['names'])]
        window._dirty = True

    def go_next(_x=None, _y=None):
        step(1)

    def go_prev(_x=None, _y=None):
        step(-1)

    window.add_button('Prev', 16, 44, 74, 30, go_prev)
    window.add_button('Next', 96, 44, 74, 30, go_next)
    reload()

    def draw(win):
        cr, tk, cairo = win.cr, toolkit, toolkit.cairo
        tk.text(cr, 'VIEW', 190, 66, dev_gui.PALETTE['dim'], 10.5, True)
        tk.text(cr, '%d images' % len(state['names']), 240, 66,
                dev_gui.PALETTE['dim'], 10.5)
        for row, name in enumerate(state['names'][:4]):
            y = LIST_TOP + row * ROW_HEIGHT
            active = name == state['current']
            tk.text(cr, ('> ' if active else '  ') + name, 16, y,
                    dev_gui.PALETTE['accent'] if active else dev_gui.PALETTE['text'],
                    11.5, active)
        # The canvas: the current image centered and scaled to fit.
        canvas_h = win.height - CANVAS_TOP - 12
        cairo.set_rgba(cr, 0.0, 0.0, 0.0, 1.0)
        cairo.rectangle(cr, 12, CANVAS_TOP, win.width - 24, canvas_h)
        cairo.fill(cr)
        path = Path(state['dir']) / state['current'] if state['current'] else None
        if path is None:
            state['note'] = 'no image'
            tk.text(cr, state['note'], 24, CANVAS_TOP + 24,
                    dev_gui.PALETTE['dim'], 11.5)
            return
        try:
            surface = cairo.surface_from_png(str(path).encode())
            if not surface:
                raise ValueError('cairo could not decode this PNG')
            image_w = cairo.image_width(surface)
            image_h = cairo.image_height(surface)
            scale, dx, dy = fit(image_w, image_h, win.width - 48, canvas_h - 24)
            cairo.save(cr)
            cairo.rectangle(cr, 12, CANVAS_TOP, win.width - 24, canvas_h)
            cairo.clip(cr)
            cairo.translate(cr, 24 + dx, CANVAS_TOP + 12 + dy)
            cairo.scale(cr, scale, scale)
            cairo.set_source_surface(cr, surface, 0, 0)
            cairo.paint(cr)
            cairo.restore(cr)
            cairo.surface_destroy(surface)
            state['note'] = '%s %dx%d at %.2fx' % (state['current'], image_w,
                                                   image_h, scale)
        except (OSError, ValueError, RuntimeError) as error:
            state['note'] = '%s: %s' % (state['current'], str(error)[:60])
            tk.text(cr, state['note'][:72], 24, CANVAS_TOP + 24,
                    dev_gui.PALETTE['red'], 11.5)
            return
        tk.text(cr, state['note'], 24, win.height - 16,
                dev_gui.PALETTE['dim'], 10)

    window.draw_callback = draw

    def clicked(x, y):
        name = row_at(y, state['names'], window.height)
        if name:
            state['current'] = name
            window._dirty = True

    window.on_click = clicked
    window.show()
    if args.test:
        import json as _json
        data = Path(os.environ.get('DEVOS_DATA_DIR', '/tmp')) / 'view.png'
        window.run(on_tick_capture=(1.2, data))
        print(_json.dumps({'images': len(state['names']),
                           'current': state['current'],
                           'note': state['note']}))
    else:
        window.run()


if __name__ == '__main__':
    main()
