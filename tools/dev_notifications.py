#!/usr/bin/python3
"""Permission-scoped notification client and host-side D-Bus broker."""
import argparse
import html
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import time

MAX_REQUEST = 4096


def validate(request):
    if not isinstance(request, dict) or set(request) - {'title', 'body', 'urgency'}:
        raise ValueError('Only title, body and urgency are supported')
    for field, maximum in (('title', 80), ('body', 512)):
        value = request.get(field, '' if field == 'body' else None)
        if not isinstance(value, str) or len(value) > maximum or (field == 'title' and not value.strip()):
            raise ValueError('Invalid notification ' + field)
        if any(ord(char) < 32 and char not in ('\n', '\t') for char in value):
            raise ValueError('Control characters are not allowed')
        value.encode('utf-8')
    urgency = request.get('urgency', 'normal')
    if not isinstance(urgency, str) or urgency not in ('low', 'normal', 'critical'):
        raise ValueError('Invalid notification urgency')
    return request['title'], request.get('body', ''), urgency


def message(stream):
    data = bytearray()
    while b'\n' not in data:
        chunk = stream.recv(min(1024, MAX_REQUEST + 1 - len(data)))
        if not chunk:
            raise ValueError('Incomplete notification message')
        data.extend(chunk)
        if len(data) > MAX_REQUEST:
            raise ValueError('Notification message is too large')
    return json.loads(data.split(b'\n', 1)[0])


def send(title, body='', urgency='normal'):
    request = {'title': title, 'body': body, 'urgency': urgency}
    validate(request)
    endpoint = os.environ.get('DEVOS_NOTIFICATION_SOCKET')
    if not endpoint:
        raise ValueError('notifications permission is required; launch the app with dev')
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(5)
        client.connect(endpoint)
        client.sendall(json.dumps(request, ensure_ascii=False).encode('utf-8') + b'\n')
        answer = message(client)
    if not answer.get('ok'):
        raise ValueError(answer.get('error', 'Notification failed'))
    return answer


class DesktopBackend:
    def __init__(self):
        self.binary = os.environ.get('DEVOS_GDBUS') or shutil.which('gdbus')
        if not self.binary:
            raise ValueError('Desktop notifications require gdbus and a notification service')
        capabilities = self.call('GetCapabilities')
        self.markup = 'body-markup' in capabilities

    def call(self, method, *arguments):
        try:
            result = subprocess.run([self.binary, 'call', '--session', '--dest', 'org.freedesktop.Notifications',
                                     '--object-path', '/org/freedesktop/Notifications', '--method',
                                     'org.freedesktop.Notifications.' + method, *arguments],
                                    capture_output=True, text=True, timeout=3, check=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError('Desktop notification service unavailable in this login session') from exc
        return result.stdout

    def notify(self, app, request):
        title, body, urgency = validate(request)
        # No actions, remote icons, hyperlinks, or app-supplied shell commands.
        quote = lambda value: json.dumps(value, ensure_ascii=False)
        body = html.escape(body, quote=False) if self.markup else body
        title = html.escape(title, quote=False) if self.markup else title
        output = self.call('Notify', quote(app), '0', quote(''), quote(title), quote(body),
                           '[]', "{'urgency': <byte " + str({'low': 0, 'normal': 1, 'critical': 2}[urgency]) + '>}', '5000')
        match = re.fullmatch(r'\s*\(uint32 ([1-9][0-9]*),\)\s*', output)
        if not match:
            raise ValueError('Unexpected notification service response')
        return {'ok': True, 'id': int(match.group(1))}


def reserve(rate_file):
    import fcntl
    with Path(rate_file).open('a+') as state:
        try:
            fcntl.flock(state, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Notification rate limit: try again later') from None
        state.seek(0)
        stored = state.read(128)
        now = time.monotonic()
        previous = float(stored) if stored else None
        if previous is not None and 0 <= now - previous < 5:
            raise ValueError('Notification rate limit: one per app every 5 seconds')
        state.seek(0); state.truncate(); state.write(str(now)); state.flush()


def broker(endpoint, app, rate_file):
    backend = DesktopBackend()  # Fail before exposing a socket if the desktop service is absent.
    stopping = False

    def shutdown(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(endpoint); os.chmod(endpoint, 0o600)
            server.listen(4); server.settimeout(0.2)
            print('READY', flush=True)
            while not stopping:
                try:
                    client, _ = server.accept()
                except socket.timeout:
                    continue
                with client:
                    client.settimeout(1)
                    try:
                        request = message(client)
                        validate(request)
                        reserve(rate_file)
                        answer = backend.notify(app, request)
                    except (ValueError, OSError, UnicodeError) as exc:
                        answer = {'ok': False, 'error': str(exc)}
                    try:
                        client.sendall(json.dumps(answer).encode('utf-8') + b'\n')
                    except OSError:
                        pass
    finally:
        Path(endpoint).unlink(missing_ok=True)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--broker':
        if len(sys.argv) != 5:
            raise ValueError('Invalid broker invocation')
        broker(*sys.argv[2:])
        return
    parser = argparse.ArgumentParser(description='Send a desktop notification from a permitted DPK app')
    parser.add_argument('title')
    parser.add_argument('body', nargs='?', default='')
    parser.add_argument('--urgency', choices=('low', 'normal', 'critical'), default='normal')
    args = parser.parse_args()
    print(json.dumps(send(args.title, args.body, args.urgency)))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, UnicodeError) as exc:
        print('dev-notify: ' + str(exc), file=sys.stderr)
        sys.exit(1)
