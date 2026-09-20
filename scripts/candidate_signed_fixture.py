"""Ephemeral public TUF fixture; private signing keys never enter the guest."""
import json
from pathlib import Path
import secrets
import sys
import tarfile


def create(directory, project):
    sys.path.insert(0, str(project / 'tools'))
    import dev
    import dev_publish
    public = directory / 'public'
    private = directory / 'private'
    password = secrets.token_bytes(32)
    dev_publish.initialize(public, private, password)
    generations = {}
    for version in ('1', '2'):
        archives = []
        for name in ('qa-lib', 'qa-app'):
            source = directory / (name + version)
            payload = source / 'payload'
            manifest = {'name': name, 'version': version, 'arch': 'all'}
            if name == 'qa-lib':
                file = payload / 'usr/share/qa-lib/version'
                content = version
            else:
                file = payload / 'usr/bin/qa-app'
                content = '#!/bin/sh\n# app version ' + version + '\ncat /usr/share/qa-lib/version\n'
                manifest.update(dependencies={'qa-lib': '==' + version}, executables=['usr/bin/qa-app'])
            file.parent.mkdir(parents=True)
            file.write_text(content)
            (source / 'manifest.json').write_text(json.dumps(manifest))
            archive = directory / (name + version + '.dpk')
            dev.build(source, archive)
            archives.append(archive)
        generations[version] = dev_publish.publish(private, archives, password)
    generations['revoked'] = dev_publish.publish(private, [], password, revoke=('qa-lib', '1'))
    (public / 'fixture.json').write_text(json.dumps(generations))
    archive = directory / 'repository.tar'
    with tarfile.open(archive, 'w') as tar:
        tar.add(public, arcname='repository')
    return archive


GUEST = r'''
import http.server, tarfile, tempfile, threading
with tempfile.TemporaryDirectory(prefix='devos-signed-qa-') as temporary:
    base = pathlib.Path(temporary)
    with tarfile.open('/opt/repository.tar') as archive:
        archive.extractall(base, filter='data')
    public = base / 'repository'
    generations = json.loads((public / 'fixture.json').read_text())
    serving = [public / 'generations' / str(generations['1'])]
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(serving[0]), **kwargs)
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    def command(*args, success=True):
        result = subprocess.run(['dev', *args], capture_output=True, text=True, timeout=30)
        assert (result.returncode == 0) == success, str(args) + ': ' + result.stdout + result.stderr
        return result
    def state(version):
        database = json.loads(pathlib.Path('/var/lib/dev/installed.json').read_text())
        for name in ('qa-app', 'qa-lib'):
            assert database[name]['version'] == version
            assert database[name]['installed_trust']['type'] == 'tuf'
        assert subprocess.check_output(['/usr/bin/qa-app'], text=True) == version
        assert not pathlib.Path('/var/lib/dev/transaction').exists()
        command('verify')
    try:
        anchor = public / 'bootstrap-root.json'
        url = 'http://127.0.0.1:' + str(server.server_port)
        command('trust', str(anchor), '--sha256', hashlib.sha256(anchor.read_bytes()).hexdigest(),
                '--metadata-url', url + '/metadata', '--targets-url', url + '/targets', '--allow-loopback-http')
        command('install', 'qa-app')
        state('1')
        serving[0] = public / 'generations' / str(generations['2'])
        command('upgrade', 'qa-lib')
        state('2')
        command('rollback', 'qa-app', success=False)
        state('2')
        command('rollback', 'qa-app', 'qa-lib')
        state('1')
        command('upgrade', 'qa-app')
        state('2')
        serving[0] = public / 'generations' / str(generations['revoked'])
        command('rollback', 'qa-app', 'qa-lib', success=False)
        state('2')
        command('remove', 'qa-lib', success=False)
        command('remove', 'qa-app')
        command('remove', 'qa-lib')
        assert not pathlib.Path('/usr/bin/qa-app').exists()
        print('SIGNED_RESULT=' + json.dumps({'passed': True, 'checks': [
            'fingerprint-pinned trust', 'signed dependency install',
            'signed library upgrade updates dependent app', 'conflicting single rollback refused',
            'signed set rollback', 'revoked member rejects whole rollback',
            'dependent removal refused', 'ordered removal and installed-file verification']}), flush=True)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
'''
