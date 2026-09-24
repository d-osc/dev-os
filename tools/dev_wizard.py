#!/usr/bin/python3
"""First-boot wizard: create your user, set the clock, pick the language.

Runs once on the first login (devos-session launches it when
~/.config/devos/wizard-done is absent). Steps advance with Return, fields
move with Tab, choices pick with digits — everything works from the
keyboard alone. User creation and timezone changes go through sudo -S
(the wizard asks for the current user's password); the language choice
writes the Thai input setting to the user's settings.json.
"""
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.append('/usr/lib/devos')
import dev_admin  # noqa: E402
import dev_gui  # noqa: E402
import dev_settings  # noqa: E402

WIDTH, HEIGHT = 460, 420
STEPS = ('welcome', 'user', 'timezone', 'language', 'done')
TIMEZONES = ('UTC', 'Asia/Bangkok', 'Asia/Tokyo', 'Europe/London',
             'America/New_York')
LANGUAGES = (('English', False), ('Thai - Kedmanee input', True))
DONE_FLAG = '.config/devos/wizard-done'


def validate_username(name):
    """An error string for a bad username, or None when it is usable."""
    if not name or not (1 <= len(name) <= 24):
        return 'username must be 1..24 characters'
    if not all(character in 'abcdefghijklmnopqrstuvwxyz0123456789_-'
               for character in name):
        return 'username: lowercase letters, digits, - and _ only'
    if name == 'root':
        return 'that username is taken'
    return None


def password_error(first, second):
    """None when the pair is usable, an explanation otherwise."""
    if len(first) < 6:
        return 'password must be at least 6 characters'
    if first != second:
        return 'the two passwords do not match'
    return None


def language_patch(choice):
    """The settings patch for one language choice index."""
    if not 0 <= choice < len(LANGUAGES):
        raise ValueError('no such language choice')
    return {'input.thai': LANGUAGES[choice][1]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='store_true',
                        help='run headless: apply nothing, print JSON, exit')
    args = parser.parse_args()
    home = Path.home()
    state = {'step': 'welcome', 'error': '', 'created': '', 'zone': '',
             'language': ''}

    toolkit = dev_gui.Toolkit()
    window = dev_gui.Window(toolkit, WIDTH, HEIGHT, title='Welcome to Dev OS',
                            x=180, y=140)
    user_entry = window.add_entry(20, 96, WIDTH - 60, 30, label='Username')
    name_entry = window.add_entry(20, 166, WIDTH - 60, 30, label='Your name')
    pass_entry = window.add_entry(20, 236, WIDTH - 60, 30,
                                  label='Password', masked=True)
    again_entry = window.add_entry(20, 300, WIDTH - 60, 30,
                                   label='Password again', masked=True)
    admin_entry = window.add_entry(20, 364, WIDTH - 60, 30,
                                   label='Current user password (sudo)',
                                   masked=True)
    entries = {'user': user_entry, 'name': name_entry, 'pass': pass_entry,
               'again': again_entry, 'admin': admin_entry}

    def begin_step(step):
        state['step'] = step
        state['error'] = ''
        for item in entries.values():
            item.focused = False
        if step == 'user':
            user_entry.focused = True
        window._dirty = True

    def apply_user():
        problem = validate_username(user_entry.text)
        if not problem:
            problem = password_error(pass_entry.text, again_entry.text)
        if problem:
            state['error'] = problem
            window._dirty = True
            return False
        admin = admin_entry.text
        if args.test:
            state['created'] = user_entry.text
            return True
        if not dev_admin.password_ok(admin):
            state['error'] = 'sudo password rejected'
            window._dirty = True
            return False
        if not dev_admin.run_as_root(dev_admin.adduser_command(user_entry.text),
                                     admin):
            state['error'] = 'adduser failed (name taken?)'
            window._dirty = True
            return False
        if not dev_admin.run_as_root(
                dev_admin.chpasswd_command(user_entry.text, pass_entry.text),
                admin):
            state['error'] = 'setting the password failed'
            window._dirty = True
            return False
        state['created'] = user_entry.text
        return True

    zone_choice = [1]                  # Asia/Bangkok by default
    language_choice = [0]

    def apply_timezone():
        zone = TIMEZONES[zone_choice[0]]
        state['zone'] = zone
        if args.test:
            return True
        return dev_admin.run_as_root(dev_admin.timezone_command(zone),
                                     admin_entry.text)

    def apply_language():
        state['language'] = LANGUAGES[language_choice[0]][0]
        if args.test:
            return True
        try:
            dev_settings.update_user(language_patch(language_choice[0]))
        except (OSError, ValueError) as error:
            state['error'] = str(error)[:60]
            window._dirty = True
            return False
        return True

    def finish():
        if not args.test:
            flag = home / DONE_FLAG
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.write_text('done\n')
        window.open_ = False

    def advance():
        step = state['step']
        if step == 'welcome':
            begin_step('user')
        elif step == 'user':
            if apply_user():
                begin_step('timezone')
        elif step == 'timezone':
            if apply_timezone():
                begin_step('language')
        elif step == 'language':
            if apply_language():
                begin_step('done')
        elif step == 'done':
            finish()

    window.add_button('Next', WIDTH - 100, HEIGHT - 58, 80, 32,
                      lambda _x, _y: advance())

    def draw(win):
        cr, tk = win.cr, toolkit
        tk.text(cr, 'DEV OS SETUP', 20, 52, dev_gui.PALETTE['accent'], 15.0, True)
        step = state['step']
        if step == 'welcome':
            tk.text(cr, 'Welcome!', 20, 100, dev_gui.PALETTE['text'], 14.0, True)
            for row, line in enumerate((
                    'This little wizard finishes the install:',
                    '  1  create your user account',
                    '  2  set the system clock',
                    '  3  choose the keyboard language',
                    '',
                    'Press Return (or click Next) to start.')):
                tk.text(cr, line, 20, 130 + row * 22, dev_gui.PALETTE['text'], 11.5)
        elif step == 'user':
            tk.text(cr, 'Create your user', 20, 88, dev_gui.PALETTE['text'], 12.5, True)
            tk.text(cr, 'Tab moves between fields; Return applies.',
                    20, HEIGHT - 20, dev_gui.PALETTE['dim'], 10)
        elif step == 'timezone':
            tk.text(cr, 'System timezone', 20, 100, dev_gui.PALETTE['text'],
                    12.5, True)
            for index, zone in enumerate(TIMEZONES):
                mark = '>' if index == zone_choice[0] else ' '
                color = (dev_gui.PALETTE['accent'] if index == zone_choice[0]
                         else dev_gui.PALETTE['text'])
                tk.text(cr, '%s %d  %s' % (mark, index + 1, zone), 28,
                        134 + index * 26, color, 12.0, index == zone_choice[0])
            tk.text(cr, 'Press the number, then Return.', 20, HEIGHT - 20,
                    dev_gui.PALETTE['dim'], 10)
        elif step == 'language':
            tk.text(cr, 'Language and keyboard', 20, 100, dev_gui.PALETTE['text'],
                    12.5, True)
            for index, (label, _thai) in enumerate(LANGUAGES):
                mark = '>' if index == language_choice[0] else ' '
                color = (dev_gui.PALETTE['accent'] if index == language_choice[0]
                         else dev_gui.PALETTE['text'])
                tk.text(cr, '%s %d  %s' % (mark, index + 1, label), 28,
                        140 + index * 28, color, 12.0, index == language_choice[0])
            tk.text(cr, 'Thai enables the Kedmanee layout in desktop apps.',
                    20, HEIGHT - 20, dev_gui.PALETTE['dim'], 10)
        else:
            tk.text(cr, 'All set', 20, 100, dev_gui.PALETTE['text'], 14.0, True)
            rows = ('User created: %s' % (state['created'] or '-'),
                    'Timezone: %s' % (state['zone'] or '-'),
                    'Language: %s' % (state['language'] or '-'),
                    '', 'Press Return to finish.')
            for row, line in enumerate(rows):
                tk.text(cr, line, 20, 132 + row * 24, dev_gui.PALETTE['text'], 12.0)
        if state['error']:
            tk.text(cr, state['error'][:60], 20, HEIGHT - 40,
                    dev_gui.PALETTE['red'], 11.0, True)

    window.draw_callback = draw

    def on_key(keysym, character, _state):
        step = state['step']
        if step in ('welcome', 'done') and keysym == 0xFF0D:
            advance()
            return True
        if step == 'user' and keysym == 0xFF0D:
            advance()
            return True
        if step == 'timezone' and character in '12345':
            index = int(character) - 1
            if index < len(TIMEZONES):
                zone_choice[0] = index
                window._dirty = True
            return True
        if step == 'timezone' and keysym == 0xFF0D:
            advance()
            return True
        if step == 'language' and character in '12':
            index = int(character) - 1
            if index < len(LANGUAGES):
                language_choice[0] = index
                window._dirty = True
            return True
        if step == 'language' and keysym == 0xFF0D:
            advance()
            return True
        return False

    window.on_key = on_key
    begin_step('welcome')
    window.show()
    if args.test:
        import json as _json
        # Pre-fill the form so one headless pass walks every step.
        user_entry.text = 'tester'
        name_entry.text = 'Test User'
        pass_entry.text = again_entry.text = 'secret1'
        admin_entry.text = 'unused'
        for _ in range(4):
            advance()
        data = Path(os.environ.get('DEVOS_DATA_DIR', '/tmp')) / 'wizard.png'
        window.run(on_tick_capture=(1.0, data))
        print(_json.dumps({'created': state['created'], 'zone': state['zone'],
                           'language': state['language'],
                           'step': state['step']}))
    else:
        window.run()


if __name__ == '__main__':
    main()
