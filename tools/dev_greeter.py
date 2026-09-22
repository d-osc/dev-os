#!/usr/bin/python3
"""Dev OS greeter: the GUI login screen of desktop mode.

Runs as the xinit client on tty1 (root): draws the sign-in card, checks
the password against /etc/shadow through libcrypt, then starts dev-shell
as the authenticated user — setuid plus USER/HOME/XAUTHORITY — so every
account signs into its own settings, themes and extensions, like a real
display manager. When the session ends the greeter returns for the next
login. Pure logic (user listing, shadow parsing, authentication and the
session spawn) stays testable without a display.
"""
import argparse
import ctypes as c
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.append('/usr/lib/devos')
import dev_gui  # noqa: E402
import dev_theme  # noqa: E402

CARD_WIDTH, CARD_HEIGHT = 380, 344


def login_users(passwd_text):
    """(name, full name) of the human accounts that may sign in."""
    found = []
    for line in passwd_text.splitlines():
        fields = line.split(':')
        if len(fields) < 7:
            continue
        name, _, uid, _, gecos, _home, shell = fields[:7]
        try:
            number = int(uid)
        except ValueError:
            continue
        if number < 1000 or number == 65534:        # root/system/nobody stay out
            continue
        if shell.endswith('nologin') or shell.endswith('/false'):
            continue
        found.append((name, gecos.split(',')[0] or name))
    return sorted(found)


def shadow_hashes(shadow_text):
    """name -> password hash, from /etc/shadow content."""
    hashes = {}
    for line in shadow_text.splitlines():
        fields = line.split(':')
        if fields and fields[0]:
            hashes[fields[0]] = fields[1] if len(fields) > 1 else ''
    return hashes


def authenticate(name, password, shadow_text=None):
    """True when the password matches the account's /etc/shadow hash."""
    try:
        text = Path('/etc/shadow').read_text() if shadow_text is None else shadow_text
    except OSError:
        return False
    hash_ = shadow_hashes(text).get(name, '')
    if not hash_.startswith('$'):
        return False                        # empty, locked or crypt(3)-unsupported
    for library in ('libcrypt.so.1', 'libc.so.6'):
        try:
            lib = c.CDLL(library)
        except OSError:
            continue
        crypt = lib.crypt
        crypt.restype = c.c_char_p
        crypt.argtypes = [c.c_char_p, c.c_char_p]
        return crypt(password.encode(), hash_.encode()) == hash_.encode()
    return False


def spawn_session(name, command=('/usr/bin/dev-shell',)):
    """Start the session process as the signed-in user; (pid, authority)."""
    import pwd
    record = pwd.getpwnam(name)
    authority = None
    source = os.environ.get('XAUTHORITY')
    if source and Path(source).is_file():
        authority = Path('/tmp/.devos-auth-%d' % os.getpid())
        authority.write_bytes(Path(source).read_bytes())
        authority.chmod(0o444)              # cookie lives only while X does
    pid = os.fork()
    if pid == 0:
        try:
            if os.getuid() == 0:
                os.initgroups(record.pw_name, record.pw_gid)
                os.setgid(record.pw_gid)
                os.setuid(record.pw_uid)
            os.chdir(record.pw_dir or '/')
            os.environ.update({'USER': record.pw_name, 'LOGNAME': record.pw_name,
                               'HOME': record.pw_dir, 'SHELL': record.pw_shell,
                               'DISPLAY': os.environ.get('DISPLAY', ':0')})
            if authority:
                os.environ['XAUTHORITY'] = str(authority)
            os.execv(command[0], list(command))
        except Exception as error:           # never leak a root shell on failure
            print('greeter session failed to start: %s' % error, file=sys.stderr)
        os._exit(111)
    return pid, authority


def wait_session(pid, authority):
    while True:
        try:
            os.waitpid(pid, 0)
            break
        except InterruptedError:
            continue
    if authority:
        try:
            authority.unlink()
        except OSError:
            pass


def run(shot=None):
    x, api = dev_gui.connect()
    cairo = dev_gui.Cairo()
    display = api['open_display'](None)
    if not display:
        raise SystemExit('Unable to open desktop display')
    width = api['display_width'](display, 0)
    height = api['display_height'](display, 0)
    root = api['root_window'](display, 0)
    window = api['create'](display, root, 0, 0, width, height, 1, 0x0b0f16, 0x0b0f16)
    api['store_name'](display, window, b'Dev OS Greeter')
    visual = api['default_visual'](display, 0)
    surface = cairo.surface_create(display, window, visual, width, height)
    cr = cairo.create(surface)
    tk = _TextAdapter(cairo, cr)
    api['select_input'](display, window,
                        (1 << 0) | (1 << 2) | (1 << 3) | (1 << 6) | (1 << 15) | (1 << 17))

    try:
        passwd_text = Path('/etc/passwd').read_text()
    except OSError:
        passwd_text = ''
    users = login_users(passwd_text)
    card_x, card_y = (width - CARD_WIDTH) // 2, max(24, (height - CARD_HEIGHT) // 2)
    user_entry = dev_gui.Entry(card_x + 36, card_y + 132, CARD_WIDTH - 72, 36,
                               label='User', placeholder='username')
    pass_entry = dev_gui.Entry(card_x + 36, card_y + 196, CARD_WIDTH - 72, 36,
                               label='Password', placeholder='password', masked=True)
    if len(users) == 1:
        user_entry.text = users[0][0]
    entries = [user_entry, pass_entry]
    user_entry.focused = True
    status = {'text': 'Sign in to start your session', 'color': 'dim'}
    api['map'](display, window)
    api['flush'](display)
    login_button = dev_gui.Button('Log in', card_x + 36, card_y + 254, CARD_WIDTH - 72, 38,
                                  None, primary=True)

    def set_status(text, color='dim'):
        status['text'], status['color'] = text, color

    def attempt():
        name = user_entry.text.strip()
        if not name:
            set_status('Enter your username', 'red')
            return
        if not authenticate(name, pass_entry.text):
            set_status('Wrong password, try again', 'red')
            pass_entry.text = ''
            pass_entry.focused = True
            return
        set_status('Starting session for %s…' % name)
        draw()
        api['unmap'](display, window)
        api['flush'](display)
        pid, authority = spawn_session(name)
        wait_session(pid, authority)
        pass_entry.text = ''
        set_status('Signed out; sign in again', 'dim')
        api['map'](display, window)

    login_button.callback = attempt

    def draw():
        cairo.set_rgba(cr, *dev_gui.PALETTE['bg'], 1.0)
        cairo.paint(cr)
        radius = dev_theme.corner_radius(dev_gui.CORNERS, 'window', CARD_WIDTH,
                                         CARD_HEIGHT)
        cairo.set_rgba(cr, *dev_gui.PALETTE['chrome'], 1.0)
        cairo.rounded(cr, card_x, card_y, CARD_WIDTH, CARD_HEIGHT, radius)
        cairo.fill(cr)
        cairo.set_rgba(cr, *dev_gui.PALETTE['line'], 1.0)
        cairo.set_line_width(cr, 1)
        cairo.rounded(cr, card_x + 0.5, card_y + 0.5, CARD_WIDTH - 1, CARD_HEIGHT - 1,
                      radius)
        cairo.stroke(cr)
        dev_theme.draw_icon(cairo, cr, dev_gui.ICONS['mark'], card_x + 36, card_y + 26,
                            dev_gui.THEME_COLORS['accent'], dev_gui.THEME_COLORS, 1.5)
        tk.text(cr, 'DEV OS', card_x + 64, card_y + 48, dev_gui.PALETTE['text'], 18.0, True)
        tk.text(cr, 'Sign in', card_x + 36, card_y + 78, dev_gui.PALETTE['dim'], 11.0)
        for entry in entries:
            entry.draw(tk, cr)
        login_button.draw(tk, cr)
        color = dev_gui.PALETTE['red'] if status['color'] == 'red' \
            else dev_gui.PALETTE['dim']
        tk.text(cr, status['text'], card_x + 36, card_y + 320, color, 10.5)
        cairo.surface_flush(surface)
        api['flush'](display)

    running = True
    started = time.monotonic()
    captured = shot is None
    keysym = c.c_ulong()
    buffer = c.create_string_buffer(16)
    while running:
        draw()
        while api['pending'](display):
            event = dev_gui.XEvent()
            api['next_event'](display, c.byref(event))
            kind = event.any.type
            if kind == 2:                                    # KeyPress
                api['lookup_string'](display, c.byref(event.key), buffer, 16,
                                     c.byref(keysym), None)
                char = buffer.value.decode('ascii', 'ignore')[:1]
                symbol = keysym.value
                target = pass_entry if pass_entry.focused else user_entry
                outcome = target.feed(symbol, char)
                if outcome == 'submit' and target is user_entry:
                    user_entry.focused, pass_entry.focused = False, True
                elif outcome == 'submit':
                    attempt()
            elif kind in (4, 5, 6) and event.button.window == window:
                x_pos, y_pos = event.button.x, event.button.y
                if kind == 6:
                    login_button.motion(x_pos, y_pos)
                elif kind == 4:
                    if login_button.hit(x_pos, y_pos):
                        login_button.press(x_pos, y_pos)
                    for entry in entries:
                        if entry.hit(x_pos, y_pos):
                            for other in entries:
                                other.focused = other is entry
            elif kind == 5:
                if login_button.release(event.button.x, event.button.y):
                    pass                                      # callback ran
        if not captured and time.monotonic() - started >= 1.0:
            captured = True
            api['sync'](display, 0)
            time.sleep(0.6)
            api['sync'](display, 0)
            draw()
            api['sync'](display, 0)
            pointer = api['get_image'](display, window, 0, 0, width, height,
                                       0xFFFFFFFF, 2)
            if not pointer:
                raise SystemExit('Could not capture the greeter window')
            try:
                rows = dev_gui.decode_rows(dev_gui.XImage.from_address(pointer))
                dev_gui.write_png(shot, width, height, rows)
            finally:
                x.XFree(pointer)
            running = False
        time.sleep(0.05)
    return {'screen': [width, height], 'users': [name for name, _ in users]}


class _TextAdapter:
    """Give Entry/Button the Toolkit text/cairo surface they expect."""

    def __init__(self, cairo, cr):
        self.cairo, self.cr = cairo, cr
        self._extents = dev_gui.TextExtents()

    def text(self, cr, content, x, y, color, size=12.0, bold=False, alpha=1.0):
        self.cairo.font_size(cr, size)
        self.cairo.font_face(cr, dev_gui.FONT, 0, 1 if bold else 0)
        self.cairo.set_rgba(cr, *color, alpha)
        self.cairo.move_to(cr, x, y)
        self.cairo.show_text(cr, str(content).encode('utf-8'))

    def text_width(self, cr, content, size=12.0, bold=False):
        self.cairo.font_size(cr, size)
        self.cairo.font_face(cr, dev_gui.FONT, 0, 1 if bold else 0)
        self.cairo.text_extents(cr, str(content).encode('utf-8'),
                                c.byref(self._extents))
        return self._extents.x_advance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screenshot', type=Path,
                        help='render the login screen once, capture a PNG, exit')
    args = parser.parse_args()
    result = run(shot=str(args.screenshot) if args.screenshot else None)
    print(json.dumps(result))
    if args.screenshot:
        print('Screenshot: ' + str(args.screenshot))


if __name__ == '__main__':
    main()
