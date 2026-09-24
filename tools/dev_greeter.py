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
import dev_extensions  # noqa: E402
import dev_gui  # noqa: E402
import dev_settings  # noqa: E402
import dev_theme  # noqa: E402

CARD_WIDTH, CARD_HEIGHT = 380, 344
GREETER_DIRS = (Path('/etc/devos/greeter-extensions'),
                Path('/usr/share/devos/greeter-extensions'))


class GreeterApi:
    """Design API for login-screen extensions (version 1).

    paint_background(draw) paints the whole screen behind the card and
    paint_card(draw) replaces the card surface beneath the stock fields;
    draw receives a Painter in theme colors, clipped to its area. Calling
    more than once replaces the earlier hook. Extensions here run as root
    before any login — only administrators install them, from the system
    greeter-extension directories.
    """

    version = 1

    def __init__(self, host, manifest):
        self._host, self.manifest = host, manifest

    def paint_background(self, draw):
        self._host.add_paint('background', self.manifest['id'], draw)

    def paint_card(self, draw):
        self._host.add_paint('card', self.manifest['id'], draw)

    def set_subtitle(self, text):
        self._host.subtitle = str(text)[:80]


class GreeterHost:
    """Loads the root-context design extensions of the login screen."""

    def __init__(self):
        self.hooks = {}          # 'background'/'card' -> (owner id, draw)
        self.subtitle = None
        self.loaded, self.report = [], []

    def add_paint(self, target, owner, draw):
        if target not in ('background', 'card'):
            raise ValueError('Greeter paint hook must be background or card')
        if not callable(draw):
            raise ValueError('Paint hook must be callable')
        self.hooks[target] = (owner, draw)

    def _manifest_of(self, path):
        raw = (path / 'manifest.json').read_bytes()
        if len(raw) > dev_extensions.MANIFEST_LIMIT:
            raise ValueError('Manifest exceeds the size limit')
        manifest = dev_extensions.validate(json.loads(raw))
        if manifest['main'] != 'extension.py':
            raise ValueError('Greeter extensions are Python for now '
                             "(extension.py, not %s)" % manifest['main'])
        return manifest

    def load(self, directories):
        import importlib.util
        for directory in directories:
            directory = Path(directory)
            if not directory.is_dir():
                continue
            for path in sorted(directory.iterdir()):
                if not path.is_dir() or path.name.startswith('.') \
                        or (path / '.disabled').is_file():
                    continue
                try:
                    manifest = self._manifest_of(path)
                    code = path / manifest['main']
                    if code.stat().st_size > dev_extensions.CODE_LIMIT:
                        raise ValueError('Extension code exceeds the size limit')
                    module_name = 'devos_greeter_' + manifest['id'].replace('.', '_')
                    spec = importlib.util.spec_from_file_location(module_name, code)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    if hasattr(module, 'activate'):
                        module.activate(GreeterApi(self, manifest))
                    self.loaded.append(manifest['id'])
                except Exception as error:         # a broken extension never
                    self.report.append({'id': path.name, 'error': str(error)})  # blocks login
        return self


def greeter_theme(settings):
    """The system theme for the login screen; built-in on any problem."""
    try:
        path = dev_settings.theme_path(settings['theme'])
        return dev_theme.load(path) if path else dev_gui.DEFAULT_THEME
    except (OSError, ValueError):
        return dev_gui.DEFAULT_THEME


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
    for library in ('libcrypt.so.2', 'libcrypt.so.1', 'libc.so.6'):
        try:
            lib = c.CDLL(library)
            crypt = lib.crypt
        except (OSError, AttributeError):   # no crypt(3) in this libc at all
            continue
        crypt.restype = c.c_char_p
        crypt.argtypes = [c.c_char_p, c.c_char_p]
        return crypt(password.encode(), hash_.encode()) == hash_.encode()
    return False


def spawn_session(name, command=('/usr/bin/devos-session',)):
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
            log = os.open('/tmp/devos-session.log',
                          os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
            os.dup2(log, 1)
            os.dup2(log, 2)
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


def run(shot=None, extension_dirs=None):
    settings = dev_settings.active()
    dev_gui.set_theme(greeter_theme(settings))
    dev_gui.set_font(settings['font.family'])
    host = GreeterHost().load(extension_dirs or GREETER_DIRS)
    for broken in host.report:
        print('greeter extension %s failed: %s' % (broken['id'], broken['error']),
              file=sys.stderr)
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
        # Cover the root first: without a window manager, unmap leaves the
        # card's stale pixels behind (Ubuntu clears to the session instead).
        root_surface = cairo.surface_create(display, root, visual,
                                            width, height)
        root_cr = cairo.create(root_surface)
        cairo.set_rgba(root_cr, *dev_gui.PALETTE['bg'], 1.0)
        cairo.paint(root_cr)
        cairo.surface_flush(root_surface)
        api['unmap'](display, window)
        api['flush'](display)
        pid, authority = spawn_session(name)
        wait_session(pid, authority)
        pass_entry.text = ''
        set_status('Signed out; sign in again', 'dim')
        api['map'](display, window)

    login_button.callback = attempt

    def paint_hook(target, x, y, w, h):
        """Run one extension paint hook inside its clipped area; never fatal."""
        hook = host.hooks.get(target)
        if hook is None:
            return False
        cairo.save(cr)
        cairo.rectangle(cr, x, y, w, h)
        cairo.clip(cr)
        painter = dev_extensions.Painter(cairo, cr, x, y, w, h,
                                         dev_gui.THEME_COLORS, tk._extents)
        try:
            hook[1](painter)
        except Exception as error:
            print('greeter extension %s failed to draw: %s' % (hook[0], error),
                  file=sys.stderr)
            cairo.set_rgba(cr, 1.0, 0.27, 0.27, 0.35)
            cairo.rounded(cr, x, y, w, h, 4)
            cairo.fill(cr)
        finally:
            cairo.restore(cr)
        return True

    def draw():
        cairo.set_rgba(cr, *dev_gui.PALETTE['bg'], 1.0)
        cairo.paint(cr)
        paint_hook('background', 0, 0, width, height)
        radius = dev_theme.corner_radius(dev_gui.CORNERS, 'window', CARD_WIDTH,
                                         CARD_HEIGHT)
        if not paint_hook('card', card_x, card_y, CARD_WIDTH, CARD_HEIGHT):
            cairo.set_rgba(cr, *dev_gui.PALETTE['chrome'], 1.0)
            cairo.rounded(cr, card_x, card_y, CARD_WIDTH, CARD_HEIGHT, radius)
            cairo.fill(cr)
            cairo.set_rgba(cr, *dev_gui.PALETTE['line'], 1.0)
            cairo.set_line_width(cr, 1)
            cairo.rounded(cr, card_x + 0.5, card_y + 0.5, CARD_WIDTH - 1,
                          CARD_HEIGHT - 1, radius)
            cairo.stroke(cr)
        dev_theme.draw_icon(cairo, cr, dev_gui.ICONS['mark'], card_x + 36, card_y + 26,
                            dev_gui.THEME_COLORS['accent'], dev_gui.THEME_COLORS, 1.5)
        tk.text(cr, 'DEV OS', card_x + 64, card_y + 48, dev_gui.PALETTE['text'], 18.0, True)
        tk.text(cr, host.subtitle or 'Sign in', card_x + 36, card_y + 78,
                dev_gui.PALETTE['dim'], 11.0)
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
                api['lookup_string'](c.byref(event.key), buffer, 16,
                                     c.byref(keysym), None)
                char = buffer.value.decode('ascii', 'ignore')[:1]
                symbol = keysym.value
                if symbol == 0xFF09:                           # Tab
                    user_entry.focused = not user_entry.focused
                    pass_entry.focused = not pass_entry.focused
                    continue
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
    return {'screen': [width, height], 'users': [name for name, _ in users],
            'greeter_extensions': host.loaded}


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
    parser.add_argument('--greeter-extensions', type=Path,
                        help='greeter extensions directory override (default: '
                             '/etc/devos/greeter-extensions then '
                             '/usr/share/devos/greeter-extensions)')
    args = parser.parse_args()
    result = run(shot=str(args.screenshot) if args.screenshot else None,
                 extension_dirs=[args.greeter_extensions]
                 if args.greeter_extensions else None)
    print(json.dumps(result))
    if args.screenshot:
        print('Screenshot: ' + str(args.screenshot))


if __name__ == '__main__':
    main()
