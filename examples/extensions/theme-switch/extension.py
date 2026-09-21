"""Cycle the desktop theme from the Dev OS menu."""
import dev_settings

THEMES = ['dev-dark', 'terminal-amber']


def activate(api):
    state = {'index': 0}

    def next_theme():
        state['index'] = (state['index'] + 1) % len(THEMES)
        name = THEMES[state['index']]
        path = dev_settings.theme_path(name)
        if path is None:
            return
        api.set_theme(path)
        api.notify('Theme', 'Switched to ' + name)

    api.register_command('devos.theme.next', 'Next theme', next_theme,
                         'Cycle the desktop theme')


def deactivate():
    pass
