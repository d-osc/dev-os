// The legacy Dev OS manager uses Python; only this compatibility test invokes it.
import { mkdtemp, mkdir, writeFile, rm, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import assert from 'node:assert/strict';
import { DpkSdk } from '../dist/index.js';
const sdk = new DpkSdk();
const root = await mkdtemp(join(tmpdir(), 'dpk-compat-'));
const manager = fileURLToPath(new URL('../../../tools/dev.py', import.meta.url));
const python = process.platform === 'win32' ? 'python' : 'python3';
try {
  const source = join(root, 'compat-app');
  await sdk.initProject(source);
  const manifestPath = join(source, 'manifest.json');
  const manifest = JSON.parse(await readFile(manifestPath, 'utf8'));
  manifest.cli = {commands: {'compat-tool': {runtime: 'node', entry_point: manifest.background.entry_point}}};
  manifest.window = {...manifest.background, type: 'desktop'};
  manifest.launcher = {name: 'Compatibility app', categories: ['Utility']};
  delete manifest.background; manifest.permissions = ['window'];
  await writeFile(manifestPath, JSON.stringify(manifest));
  const long = 'opt/apps/compat-app/' + 'nested/'.repeat(25) + 'ภาษาไทย.txt';
  await mkdir(join(source, 'payload', long, '..'), {recursive: true});
  await writeFile(join(source, 'payload', long), 'Unicode payload');
  const archive = await sdk.pack(source);
  const target = join(root, 'target');
  execFileSync(python, [manager, '--root', target, 'install', archive], {stdio: 'inherit'});
  assert.equal(await readFile(join(target, long), 'utf8'), 'Unicode payload');
  assert.match(await readFile(join(target, 'usr/bin/compat-tool'), 'utf8'), /exec \/usr\/bin\/node --/);
  assert.match(await readFile(join(target, 'usr/share/applications/devos-compat-app.desktop'), 'utf8'), /Exec=\/usr\/bin\/dev launch compat-app/);
  execFileSync(python, [manager, '--root', target, 'remove', 'compat-app'], {stdio: 'inherit'});
  const legacy = join(root, 'python-built.dpk');
  execFileSync(python, [manager, 'build', source, legacy], {stdio: 'inherit'});
  assert.deepEqual(await sdk.verify(legacy), await sdk.validate(source));
  console.log('Both directions passed, including PAX/Unicode paths and install/remove.');
} finally { await rm(root, {recursive: true, force: true}); }
