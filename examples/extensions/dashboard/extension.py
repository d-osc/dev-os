"""Taskbar memory widget with a details panel for Dev OS."""
from pathlib import Path


def memory():
    """(used MiB, total MiB) from /proc/meminfo."""
    info = {}
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            key, value = line.split(':', 1)
            info[key] = int(value.split()[0])
    except (OSError, ValueError, IndexError):
        return 0, 1
    total = info.get('MemTotal', 1)
    free = info.get('MemFree', 0) + info.get('Buffers', 0) + info.get('Cached', 0)
    return max(0, total - free), max(total, 1)


def draw_widget(painter):
    used, total = memory()
    fraction = min(1.0, used / total)
    painter.text('%d%%' % round(fraction * 100), 2, 24, 'text', 12, True)
    painter.rect(34, 16, 60, 8, 'line', radius=4, fill=False)
    painter.rect(35, 17, max(1, round(58 * fraction)), 6, 'accent', radius=3)


def draw_panel(painter):
    used, total = memory()
    painter.rect(0, 0, painter.width, painter.height, 'chrome')
    painter.text('MEMORY', 14, 34, 'dim', 11, True)
    painter.text('%.0f MiB of %.0f MiB' % (used / 1024, total / 1024), 14, 58,
                 'text', 15, True)
    painter.rect(14, 74, painter.width - 28, 10, 'line', radius=5, fill=False)
    painter.rect(15, 75, max(1, round((painter.width - 30) * used / total)), 8,
                 'accent', radius=4)
    painter.text('click outside to close', 14, painter.height - 12, 'dim', 9)


def activate(api):
    panel = api.create_panel('devos.dashboard.panel', 260, 110, draw_panel, x=8)
    api.register_widget('right', 100, draw_widget, on_click=panel.toggle)
    api.register_command('devos.dashboard.toggle', 'Toggle memory panel',
                         panel.toggle, 'Show or hide the details panel')


def deactivate():
    pass
