#!/usr/bin/python3
"""Music: the minimal Dev OS media player — WAV files through aplay.

Lists .wav files under the music directory, one click plays through
aplay (the same ALSA path proven in the VM), the playing row is
highlighted and a tone-safe note renders while it runs. listing() and
the row geometry are pure for unit tests.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.append('/usr/lib/devos')
import dev_gui  # noqa: E402

WIDTH, HEIGHT = 560, 420
ROW_HEIGHT = 32
LIST_TOP = 108


def listing(directory):
    """(name, seconds or None) for every WAV, sorted; None on a bad dir."""
    directory = Path(directory)
    try:
        files = sorted(directory.glob('*.wav'), key=lambda item: item.name.lower())
    except OSError:
        return None, []
    rows = []
    for item in files:
        seconds = wav_seconds(item)
        rows.append((item.name, seconds))
    return str(directory), rows


def wav_seconds(path):
    """Duration of a PCM WAV via its header, or None when unreadable."""
    try:
        import struct
        import wave
        with wave.open(str(path), 'rb') as stream:
            return round(stream.getnframes() / stream.getframerate(), 1)
    except (OSError, wave.Error, struct.error, ZeroDivisionError):
        return None


def row_at(y, rows, height):
    """The file name of one list row at a click, or None."""
    room = max(1, (height - LIST_TOP - 46) // ROW_HEIGHT)
    row = int((y - LIST_TOP) // ROW_HEIGHT)
    visible = rows[:room]
    return visible[row][0] if 0 <= row < len(visible) else None


def play_command(aplay='aplay'):
    """The player argv; exists so tests can stub the binary name."""
    return [aplay]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--music', default='~/Music', help='directory to list')
    parser.add_argument('--test', action='store_true',
                        help='render once, capture a PNG, print JSON, exit')
    args = parser.parse_args()
    directory = str(Path(args.music).expanduser())
    state = {'dir': directory, 'rows': [], 'playing': None, 'seconds': 0.0}

    toolkit = dev_gui.Toolkit()
    window = dev_gui.Window(toolkit, WIDTH, HEIGHT, title='Music', x=170, y=110)

    def reload():
        state['dir'], state['rows'] = listing(directory)
        window._dirty = True

    def play(name):
        path = Path(state['dir']) / name
        try:
            result = subprocess.run(play_command() + [str(path)],
                                   capture_output=True, timeout=30)
            state['playing'] = name if result.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            state['playing'] = None
        window._dirty = True

    reload()

    def draw(win):
        cr = win.cr
        tk = toolkit
        tk.text(cr, 'MUSIC', 16, 72, dev_gui.PALETTE['dim'], 10.5, True)
        tk.text(cr, '%d tracks' % len(state['rows']), 100, 72,
                dev_gui.PALETTE['dim'], 10.5)
        tk.text(cr, state['dir'] or 'folder not found', 16, 90,
                dev_gui.PALETTE['dim'], 9.5)
        for row, (name, seconds) in enumerate(state['rows'][:8]):
            y = LIST_TOP + row * ROW_HEIGHT
            active = state['playing'] == name
            if active:
                toolkit.cairo.set_rgba(cr, *dev_gui.PALETTE['accent'], 0.16)
                toolkit.cairo.rounded(cr, 6, y - 18, win.width - 16, ROW_HEIGHT, 6)
                toolkit.cairo.fill(cr)
            tk.text(cr, ('▶ ' if active else '  ') + name, 16, y + 4,
                    dev_gui.PALETTE['accent'] if active else dev_gui.PALETTE['text'],
                    12.5, active)
            detail = ('%ss' % seconds) if seconds is not None else 'wav'
            tk.text(cr, detail, win.width - 70, y + 4, dev_gui.PALETTE['dim'], 10.5)

    window.draw_callback = draw

    def clicked(x, y):
        name = row_at(y, state['rows'], window.height)
        if name:
            play(name)

    window.on_click = clicked
    window.show()
    if args.test:
        import json as _json
        data = Path(os.environ.get('DEVOS_DATA_DIR', '/tmp')) / 'music.png'
        window.run(on_tick_capture=(1.2, data))
        print(_json.dumps({'tracks': len(state['rows']),
                           'dir': state['dir'],
                           'playing': state['playing']}))
    else:
        window.run()


if __name__ == '__main__':
    main()
