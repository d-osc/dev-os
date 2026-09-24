#!/usr/bin/python3
"""Web: the minimal Dev OS browser — fetch http(s) and render local HTML.

A URL bar, a Back button, and the wallpaper engine's HTML renderer
(background color/gradient, styled text, images) on a scrolled canvas;
plain text and JSON fall back to monospaced lines. fetch() is pure
enough to unit test; rendering shares dev_background's subset honestly —
this is a reader, not an engine: no CSS layout, no scripts.
"""
import argparse
import os
from pathlib import Path
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.append('/usr/lib/devos')
import dev_background  # noqa: E402
import dev_gui  # noqa: E402

WIDTH, HEIGHT = 700, 500
TITLE_HEIGHT = 84


def normalize(url):
    """Bare hosts become http://; returns None when nothing to load."""
    url = (url or '').strip()
    if not url:
        return None
    if not (url.startswith('http://') or url.startswith('https://')
            or url.startswith('file://')):
        url = 'http://' + url
    return url


def fetch(url, timeout=6):
    """(kind, payload) for one URL: 'html' text, 'text' lines, or an error."""
    try:
        if url.startswith('file://'):
            body = Path(url[7:]).read_text()[:60000]
        else:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                body = response.read(60000).decode('utf-8', 'replace')
        stripped = body.lstrip().lower()
        if stripped.startswith('<!doctype html') or stripped.startswith('<html'):
            return 'html', body
        return 'text', body
    except (OSError, ValueError) as error:
        return 'error', str(error)[:120]


def render_page(cairo, cr, kind, payload, width, height):
    """Paint one fetched page onto the window canvas."""
    if kind == 'html':
        background, items = dev_background.parse_html(payload)
        dev_background._paint_html(cairo, cr, width, height, background, items, '.')
        return
    cairo.set_rgba(cr, *dev_gui.PALETTE['bg'], 1.0)
    cairo.paint(cr)
    y = 44
    step = 22
    lines = (payload.splitlines() if kind == 'text'
             else ['error: ' + str(payload)])[:40]
    for line in lines:
        cairo.set_rgba(cr, *dev_gui.PALETTE['text'], 1.0)
        cairo.move_to(cr, 16, y)
        cairo.show_text(cr, line[:96].encode('utf-8'))
        y += step


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url', nargs='?', help='first URL or file path')
    parser.add_argument('--test', action='store_true',
                        help='render once, capture a PNG, print JSON, exit')
    args = parser.parse_args()

    state = {'url': normalize(args.url) or 'http://10.0.2.2:8000/',
             'kind': 'text', 'payload': 'type an address and press Enter'}
    toolkit = dev_gui.Toolkit()
    window = dev_gui.Window(toolkit, WIDTH, HEIGHT, title='Web', x=110, y=80)
    address = window.add_entry(16, 44, WIDTH - 130, 32, label='Address')
    address.text = state['url']

    def load():
        state['url'] = normalize(address.text) or state['url']
        address.text = state['url']
        state['kind'], state['payload'] = fetch(state['url'])
        window._dirty = True

    window.add_button('Go', WIDTH - 100, 44, 80, 32, load)

    def draw(win):
        cr = win.cr
        cairo = toolkit.cairo
        tk = toolkit
        tk.text(cr, 'WEB', 16, 72, dev_gui.PALETTE['dim'], 10.5, True)
        tk.text(cr, state['kind'], 60, 72, dev_gui.PALETTE['dim'], 10.5)
        render_page(cairo, cr, state['kind'], state['payload'],
                    win.width, win.height)

    window.draw_callback = draw

    def on_key(keysym, char, modifiers):
        if keysym == 0xFF0D and address.focused:      # Enter loads
            load()

    window.on_key = on_key
    if args.test:
        load()
    window.show()
    if args.test:
        import json as _json
        data = Path(os.environ.get('DEVOS_DATA_DIR', '/tmp')) / 'web.png'
        window.run(on_tick_capture=(1.4, data))
        print(_json.dumps({'kind': state['kind'],
                           'url': state['url'],
                           'payload': len(state['payload'])}))
    else:
        window.run()


if __name__ == '__main__':
    main()
