import { mkdir, writeFile, readFile } from 'node:fs/promises';
import { resolve, join, basename } from 'node:path';
import { check, guarded } from './errors.js';
import { runtimes } from './manifest.js';
import type { AppManifest, InitOptions } from './index.js';

const nodeBackground = `const fs = require('node:fs');
const path = require('node:path');
const data = process.env.DEVOS_DATA_DIR;
if (!data) throw new Error('DEVOS_DATA_DIR is required');
let ticks = 0;
function tick() {
  fs.writeFileSync(path.join(data, 'counter.new'), JSON.stringify({ticks: ++ticks, updated: Math.floor(Date.now()/1000)}));
  fs.renameSync(path.join(data, 'counter.new'), path.join(data, 'counter.json'));
}
tick(); setInterval(tick, 1000);
`;
const shellBackground = `set -eu
cd "$DEVOS_DATA_DIR"
ticks=0
while :; do
  ticks=$((ticks + 1))
  printf '{"ticks": %s}\\n' "$ticks" > counter.new
  mv counter.new counter.json
  sleep 1
done
`;
const buildScript = `import { readFileSync, mkdirSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { join, dirname } from 'node:path';
const root = dirname(fileURLToPath(import.meta.url));
const manifest = JSON.parse(readFileSync(join(root, 'manifest.json'), 'utf8'));
const prefix = join(root, 'payload/opt/apps', manifest.name, 'bin');
mkdirSync(prefix, {recursive: true});
for (const kind of ['background', 'window']) {
  if (!manifest[kind] || (kind === 'background' && manifest[kind].runtime !== 'native')) continue;
  const flags = kind === 'window' ? [join(root, 'src/label.c'), '-l:libX11.so.6'] : ['-static'];
  if (process.env.DEVOS_X11_INCLUDE && kind === 'window') flags.unshift('-I', process.env.DEVOS_X11_INCLUDE);
  const result = spawnSync(process.env.CC || 'cc', [join(root, 'src', kind + '.c'), '-O2', '-Wall', '-Wextra', '-Werror', ...flags, '-o', join(prefix, kind)], {stdio: 'inherit'});
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}
`;
export async function initProject(directory: string, options: InitOptions = {}): Promise<string> {
  return guarded(async () => {
    directory = resolve(directory);
    const name = options.name ?? basename(directory);
    check(/^[a-z][a-z0-9-]{0,63}$/.test(name), 'Use a lowercase package name (max 64 characters)');
    const kind = options.kind ?? 'background';
    check(['background', 'window', 'both'].includes(kind), 'Invalid kind');
    const selected = { background: options.backgroundRuntime ?? options.runtime ?? 'node', window: options.windowRuntime ?? options.runtime ?? 'node' };
    check(Object.values(selected).every(r => runtimes.includes(r)), 'Unsupported runtime');
    check(Array.isArray(options.permissions ?? []) && (options.permissions ?? []).every(p => ['storage', 'network', 'notifications'].includes(p)), 'Invalid additional permissions');
    await mkdir(resolve(directory, '..'), { recursive: true });
    await mkdir(directory);
    const prefix = 'opt/apps/' + name;
    const kinds = kind === 'both' ? ['background', 'window'] as const : [kind];
    const m: AppManifest = { manifest_version: 2, name, version: '0.1.0', arch: 'all',
      permissions: [...new Set([...kinds, 'storage' as const, ...(options.permissions ?? [])])], executables: [] };
    const write = async (name: string, content: string) => {
      const path = join(directory, name); await mkdir(resolve(path, '..'), { recursive: true }); await writeFile(path, content);
    };
    let compile = false;
    for (const entryKind of kinds) {
      const runtime = selected[entryKind];
      let filename: string;
      if (entryKind === 'window' || runtime === 'native') {
        compile = true; m.arch = 'x86_64';
        await write('src/' + entryKind + '.c', await readFile(new URL('../assets/' + entryKind + '.c', import.meta.url), 'utf8'));
        m.executables!.push(prefix + '/bin/' + entryKind);
        await mkdir(join(directory, 'payload', prefix, 'bin'), { recursive: true });
        if (entryKind === 'window') await write('src/label.c', await readFile(new URL('../assets/label.c', import.meta.url), 'utf8'));
        if (runtime === 'native') filename = 'bin/' + entryKind;
        else if (runtime === 'node') {
          filename = 'window.cjs';
          await write('payload/' + prefix + '/' + filename, `const {spawnSync} = require('node:child_process');\nconst result = spawnSync(process.env.DEVOS_APP_DIR + '/bin/window', process.argv.slice(2), {stdio:'inherit'});\nif (result.error) throw result.error;\nprocess.exit(result.status ?? 1);\n`);
        } else if (runtime === 'python') {
          filename = 'window.py';
          await write('payload/' + prefix + '/' + filename, 'import os, sys\nos.execv(os.environ["DEVOS_APP_DIR"] + "/bin/window", ["window", *sys.argv[1:]])\n');
        } else {
          filename = 'window.sh';
          await write('payload/' + prefix + '/' + filename, 'set -eu\nexec "$DEVOS_APP_DIR/bin/window" "$@"\n');
        }
      } else {
        filename = runtime === 'node' ? 'background.cjs' : runtime === 'python' ? 'background.py' : 'background.sh';
        const python = 'import json, os, time\nfrom pathlib import Path\np = Path(os.environ["DEVOS_DATA_DIR"])\nticks = 0\nwhile True:\n    ticks += 1\n    (p / "counter.new").write_text(json.dumps({"ticks": ticks}))\n    (p / "counter.new").replace(p / "counter.json")\n    time.sleep(1)\n';
        await write('payload/' + prefix + '/' + filename, runtime === 'node' ? nodeBackground : runtime === 'python' ? python : shellBackground);
      }
      const entry = { runtime, entry_point: prefix + '/' + filename };
      if (entryKind === 'window') m.window = { ...entry, type: 'desktop' }; else m.background = entry;
    }
    await write('manifest.json', JSON.stringify(m, null, 2) + '\n');
    if (compile) await write('build.mjs', buildScript);
    await write('.gitignore', 'dist/\n');
    await write('README.md', '# ' + name + '\n\n' + (compile ? 'Compile on Linux first: `node build.mjs` (C compiler; X11 headers/library for window).\n\n' : '') +
      'Use @devos/dpk-sdk to validate and pack this source. SDK packaging needs Node.js only.\n' +
      'Install on Dev OS: sudo dev install <archive.dpk>\n' +
      'Launch: dev start ' + name + ' --allow ' + m.permissions.join(',') + '\n' +
      'For windows: dev open ' + name + ' --allow ' + m.permissions.join(',') + '\n');
    return directory;
  });
}
