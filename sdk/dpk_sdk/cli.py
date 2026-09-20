import argparse
import json
import sys
import tarfile

from . import __version__
from .api import RUNTIMES, init_project, inspect_package, pack, validate, verify
from ._core import core


def main(argv=None):
    parser = argparse.ArgumentParser(prog='dpk', description='Dev OS Developer Package Kit SDK')
    parser.add_argument('--version', action='version', version=__version__)
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init', help='create a starter app without running any code')
    init.add_argument('directory'); init.add_argument('--name')
    init.add_argument('--runtime', choices=RUNTIMES, default='python')
    init.add_argument('--kind', choices=('background', 'window', 'both'), default='both')
    init.add_argument('--background-runtime', choices=RUNTIMES)
    init.add_argument('--window-runtime', choices=RUNTIMES)
    init.add_argument('--permissions', default='', help='extra permissions: notifications,network,storage')
    check = commands.add_parser('validate', help='validate source manifest and payload')
    check.add_argument('source', nargs='?', default='.')
    check.add_argument('--json', action='store_true')
    build = commands.add_parser('pack', help='build a verified .dpk without installing it')
    build.add_argument('source', nargs='?', default='.')
    build.add_argument('-o', '--output'); build.add_argument('--force', action='store_true')
    for name in ('inspect', 'verify'):
        command = commands.add_parser(name, help='check the full archive and its payload hashes')
        command.add_argument('package')
    args = parser.parse_args(argv)
    try:
        if args.command == 'init':
            print(init_project(args.directory, name=args.name, runtime=args.runtime, kind=args.kind,
                               background_runtime=args.background_runtime, window_runtime=args.window_runtime,
                               permissions=tuple(filter(None, args.permissions.split(',')))))
        elif args.command == 'validate':
            manifest = validate(args.source)
            print(json.dumps(manifest, ensure_ascii=False, indent=2) if args.json else
                  f"Valid: {manifest['name']} {manifest['version']} ({len(manifest['files'])} files)")
        elif args.command == 'pack':
            path = pack(args.source, args.output, force=args.force)
            print(path); print('SHA256: ' + core.digest(path))
        elif args.command == 'inspect':
            print(json.dumps(inspect_package(args.package), ensure_ascii=False, indent=2))
        else:
            manifest = verify(args.package)
            print(f"Verified: {manifest['name']} {manifest['version']} ({len(manifest['files'])} files)")
    except (ValueError, OSError, tarfile.TarError, KeyError, TypeError, AttributeError, EOFError) as exc:
        print('dpk: ' + str(exc), file=sys.stderr)
        return 1
    return 0
