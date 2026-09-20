#!/usr/bin/env python3
"""Configure/build one isolated candidate, keeping verbose output out of chat."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--buildroot', type=Path, required=True)
parser.add_argument('--jobs', type=int, default=4)
parser.add_argument('--configure', action='store_true')
parser.add_argument('--clean', action='store_true', help='Rebuild the isolated candidate after toolchain changes')
args = parser.parse_args()
project = Path(__file__).resolve().parents[1]
out = project / 'out'
out.mkdir(exist_ok=True)
log_path = out / 'candidate-build.log'
status_path = out / 'candidate-build.json'
env = dict(os.environ, PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
           DEVOS_WITH_NODE='1', DEVOS_TEST_VM='1', DEVOS_BUILD_JOBS=str(args.jobs),
           BR2_DL_DIR=str(args.buildroot.resolve() / 'dl'))
commands = []
if args.clean:
    build_output = (out / 'buildroot').resolve()
    if not (project / '.devos-build-checkout.json').is_file() or build_output != project.resolve() / 'out/buildroot':
        raise SystemExit('Clean requires a verified isolated candidate build directory')
    commands.append(['make', '-C', str(build_output), 'clean'])
if args.configure:
    commands.append(['sh', str(project / 'scripts/configure.sh'), str(args.buildroot.resolve())])
commands.append(['sh', str(project / 'scripts/build.sh')])
record = {'passed': False, 'phase': 'starting', 'started': time.time(), 'log': str(log_path)}
with log_path.open('a') as log:
    for command in commands:
        phase = 'clean' if command[0] == 'make' else ('configure' if 'configure.sh' in command[1] else 'build')
        process = subprocess.Popen(command, cwd=project, env=env, stdout=log, stderr=subprocess.STDOUT)
        record.update(phase=phase, pid=process.pid)
        status_path.write_text(json.dumps(record, indent=2) + '\n')
        print('Candidate ' + phase + ' started (PID ' + str(process.pid) + ')', flush=True)
        result = process.wait()
        if result:
            record.update(phase='failed', exit_code=result, finished=time.time())
            status_path.write_text(json.dumps(record, indent=2) + '\n')
            raise SystemExit(result)
record.update(phase='complete', passed=True, exit_code=0, finished=time.time())
status_path.write_text(json.dumps(record, indent=2) + '\n')
print('Candidate build complete', flush=True)
