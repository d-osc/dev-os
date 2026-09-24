#!/usr/bin/python3
"""Edit: the minimal Dev OS text editor, drawn with the shared toolkit.

One file, lines on a canvas, a caret, plain typing: arrows move, Home/
End jump, Enter splits, Backspace/Delete edit, Ctrl-S saves in place.
Pure line/cursor logic stays in edit_step() for unit tests.
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.append('/usr/lib/devos')
import dev_gui  # noqa: E402

WIDTH, HEIGHT = 620, 440
LINE_HEIGHT = 24
TEXT_TOP = 84
LEFT = 56

RETURN, BACKSPACE = 0xFF0D, 0xFF08
LEFT_KEY, RIGHT_KEY, UP, DOWN, HOME, END = 0xFF51, 0xFF53, 0xFF52, 0xFF54, 0xFF50, 0xFF57


def edit_step(lines, row, col, keysym, char):
    """One keypress -> (lines, row, col); the whole editing model."""
    lines = list(lines)
    row = max(0, min(row, len(lines) - 1))
    col = max(0, min(col, len(lines[row])))
    if keysym == RETURN:
        lines.insert(row + 1, lines[row][col:])
        lines[row] = lines[row][:col]
        row, col = row + 1, 0
    elif keysym == BACKSPACE:
        if col:
            lines[row] = lines[row][:col - 1] + lines[row][col:]
            col -= 1
        elif row:
            col = len(lines[row - 1])
            lines[row - 1] += lines[row]
            del lines[row]
            row -= 1
    elif keysym in (LEFT_KEY, RIGHT_KEY, UP, DOWN, HOME, END):
        if keysym == LEFT_KEY:
            if col:
                col -= 1
            elif row:
                row, col = row - 1, len(lines[row - 1])
        elif keysym == RIGHT_KEY:
            if col < len(lines[row]):
                col += 1
            elif row < len(lines) - 1:
                row, col = row + 1, 0
        elif keysym == UP and row:
            row, col = row - 1, min(col, len(lines[row - 1]))
        elif keysym == DOWN and row < len(lines) - 1:
            row, col = row + 1, min(col, len(lines[row + 1]))
        elif keysym == HOME:
            col = 0
        elif keysym == END:
            col = len(lines[row])
    elif char and 32 <= ord(char) < 127:
        lines[row] = lines[row][:col] + char + lines[row][col:]
        col += 1
    return lines, row, col


def visible_rows(lines, row, height):
    """Lines that fit and the scroll offset keeping the caret on screen."""
    room = max(1, (height - TEXT_TOP - 40) // LINE_HEIGHT)
    top = min(max(0, row - room + 1), max(0, len(lines) - room))
    return top, room


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', nargs='?', help='file to open')
    parser.add_argument('--test', action='store_true',
                        help='render once, capture a PNG, print JSON, exit')
    args = parser.parse_args()
    path = Path(args.file) if args.file else None
    if path and path.is_file():
        lines = path.read_text().splitlines() or ['']
    else:
        lines = ['']
    state = {'lines': lines, 'row': 0, 'col': 0, 'path': path, 'saved': True}

    toolkit = dev_gui.Toolkit()
    window = dev_gui.Window(toolkit, WIDTH, HEIGHT, title='Edit', x=150, y=100)

    def save():
        if state['path']:
            state['path'].write_text(chr(10).join(state['lines']) + chr(10))
            state['saved'] = True
            window._dirty = True

    window.add_button('Save', WIDTH - 100, 46, 80, 32, save)

    def draw(win):
        cr = win.cr
        tk = toolkit
        tk.text(cr, 'EDIT' + ('' if state['saved'] else ' *'), 16, 72,
                 dev_gui.PALETTE['dim'], 10.5, True)
        name = str(state['path']) if state['path'] else 'untitled'
        tk.text(cr, name, 60, 72, dev_gui.PALETTE['dim'], 10.5)
        top, room = visible_rows(state['lines'], state['row'], win.height)
        for offset in range(room):
            line_index = top + offset
            if line_index >= len(state['lines']):
                break
            y = TEXT_TOP + offset * LINE_HEIGHT
            active = line_index == state['row']
            if active:
                toolkit.cairo.set_rgba(cr, *dev_gui.PALETTE['accent'], 0.10)
                toolkit.cairo.rounded(cr, 4, y - 16, win.width - 12, LINE_HEIGHT, 4)
                toolkit.cairo.fill(cr)
            tk.text(cr, '%4d' % (line_index + 1), 8, y + 4,
                     dev_gui.PALETTE['dim'], 10.0)
            tk.text(cr, state['lines'][line_index] or ' ', LEFT, y + 4,
                    dev_gui.PALETTE['text'] if active else dev_gui.PALETTE['dim'],
                    12.5)
            if active:
                caret_x = LEFT + toolkit.text_width(
                    cr, state['lines'][line_index][:state['col']], 12.5)
                toolkit.cairo.set_rgba(cr, *dev_gui.PALETTE['accent'], 1.0)
                toolkit.cairo.set_line_width(cr, 1.4)
                toolkit.cairo.new_sub_path(cr)
                toolkit.cairo.move_to(cr, caret_x, y - 10)
                toolkit.cairo.line_to(cr, caret_x, y + 10)
                toolkit.cairo.stroke(cr)
        tk.text(cr, '%d lines' % len(state['lines']), 16, win.height - 14,
                 dev_gui.PALETTE['dim'], 10.0)

    window.draw_callback = draw

    def on_key(keysym, char, modifiers):
        control = bool(modifiers & 0x4)
        if control and char in ('s', 'S'):
            save()
            return
        lines, row, col = edit_step(state['lines'], state['row'], state['col'],
                                    keysym, char)
        if lines != state['lines'] and state['saved']:
            state['saved'] = False
        state['lines'], state['row'], state['col'] = lines, row, col
        window._dirty = True

    window.on_key = on_key
    window.show()
    if args.test:
        import json as _json
        data = Path(__import__('os').environ.get('DEVOS_DATA_DIR', '/tmp')) / 'edit.png'
        window.run(on_tick_capture=(1.2, data))
        print(_json.dumps({'lines': len(state['lines']), 'row': state['row'],
                           'path': str(state['path'] or 'untitled')}))
    else:
        window.run()


if __name__ == '__main__':
    main()
