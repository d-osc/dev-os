"""Battery tray icon and status command for Dev OS."""
from pathlib import Path

BOLT = {'view': [16, 16], 'elements': [
    {'kind': 'poly', 'points': [[9, 1], [4, 9], [7.5, 9], [6, 15], [12, 7], [8.5, 7]],
     'fill': True},
]}


def read_batteries(base='/sys/class/power_supply'):
    """(name, capacity percent, status) for every supply the kernel reports."""
    root = Path(base)
    if not root.is_dir():
        return []
    found = []
    for supply in sorted(root.iterdir()):
        try:
            capacity = int((supply / 'capacity').read_text().strip())
            status = (supply / 'status').read_text().strip()
            found.append((supply.name, capacity, status))
        except (OSError, ValueError):
            continue
    return found


def summary():
    supplies = read_batteries()
    if not supplies:
        return 'No battery reported by the kernel'
    return ', '.join('%s %d%% (%s)' % row for row in supplies)


def activate(api):
    api.register_tray('battery', BOLT, command_id='devos.battery.status', color='accent')
    api.register_command('devos.battery.status', 'Battery status',
                         lambda: api.notify('Battery', summary()),
                         'Power supply summary')


def deactivate():
    pass
