#!/usr/bin/python3
"""System Info window for Dev OS, drawn with the shared ctypes+Cairo toolkit."""
import os
from pathlib import Path
import sys

sys.path.insert(0, '/usr/lib/devos')
base = Path(os.environ.get('DEVOS_APP_DIR') or Path(__file__).resolve().parents[6])
sys.path.append(str(base / 'tools'))
import dev_gui  # noqa: E402
import dev_theme  # noqa: E402


def active_theme(argv):
    """--theme <file> > $DEVOS_THEME > the built-in default."""
    if '--theme' in argv:
        return dev_theme.load(argv[argv.index('--theme') + 1])
    source = os.environ.get('DEVOS_THEME')
    return dev_theme.load(source) if source else dev_gui.DEFAULT_THEME


def parse_meminfo(text):
    """Human-readable main memory size from /proc/meminfo content."""
    for line in text.splitlines():
        if line.startswith('MemTotal:'):
            kib = int(line.split()[1])
            return f'{kib // 1024} MiB'
    return 'unknown'


def uptime_text(seconds):
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    if days:
        return f'{days}d {hours}h {minutes}m'
    if hours:
        return f'{hours}h {minutes}m'
    return f'{minutes}m'


def os_release(text, key):
    for line in text.splitlines():
        if line.startswith(key + '='):
            return line.split('=', 1)[1].strip('"')
    return 'unknown'


def collect(platform=None, meminfo=None, release=None, uptime=None):
    import platform as host
    kernel = platform or ' '.join(host.uname()[0:3])
    memory = parse_meminfo(meminfo if meminfo is not None
                           else Path('/proc/meminfo').read_text())
    version = os_release(release if release is not None
                         else Path('/usr/lib/os-release').read_text(), 'PRETTY_NAME')
    seconds = uptime if uptime is not None else float(Path('/proc/uptime').read_text().split()[0])
    return [('Version', version), ('Kernel', kernel), ('Memory', memory),
            ('Uptime', uptime_text(seconds))]


def main():
    try:
        theme = active_theme(sys.argv)
    except (OSError, ValueError, IndexError) as error:
        raise SystemExit('Could not load theme: %s' % error)
    dev_gui.set_theme(theme)
    font = os.environ.get('DEVOS_FONT')
    if font:
        dev_gui.set_font(font)
    rows = collect()
    toolkit = dev_gui.Toolkit()
    window = dev_gui.Window(toolkit, 380, 230, title='Dev OS — System Info', x=140, y=120)
    top = window.client_top() + 26
    for heading, value in rows:
        window.add_label(heading, 20, top, 10.5, 'dim')
        window.add_label(value, 110, top, 12.5, 'text', bold=True)
        top += 30

    def close():
        window.open_ = False

    window.add_button('Close', 380 - 110, 230 - 44, 90, 26, close, primary=True)
    window.show()
    if '--test' in sys.argv:
        data = Path(os.environ.get('DEVOS_DATA_DIR', '/tmp'))
        window.run(on_tick_capture=(1.2, data / 'window.png'))
    else:
        window.run()


if __name__ == '__main__':
    main()
