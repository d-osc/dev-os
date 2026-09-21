#!/usr/bin/python3
"""System Info window for Dev OS, drawn with the shared ctypes+Cairo toolkit."""
import os
from pathlib import Path
import sys

sys.path.insert(0, '/usr/lib/devos')
base = Path(os.environ.get('DEVOS_APP_DIR') or Path(__file__).resolve().parents[6])
sys.path.append(str(base / 'tools'))
import dev_gui  # noqa: E402


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
