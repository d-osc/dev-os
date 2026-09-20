import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile, rm, mkdir, symlink } from 'node:fs/promises';
import { createWriteStream } from 'node:fs';
import { createHash } from 'node:crypto';
import { createGzip } from 'node:zlib';
import { pipeline } from 'node:stream/promises';
import tar from 'tar-stream';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { DpkSdk, DpkError } from '../dist/index.js';

test('round trip, Unicode/spaces, deterministic packing, no overwrite and corrupt archive', async () => {
  const root = await mkdtemp(join(tmpdir(), 'dpk ts ภาษาไทย '));
  const sdk = new DpkSdk();
  try {
    const source = join(root, 'source with spaces');
    await sdk.initProject(source, { name: 'ts-app', backgroundRuntime: 'node', permissions: ['notifications'] });
    const before = await readFile(join(source, 'manifest.json'));
    const manifest = await sdk.validate(source);
    assert.equal(manifest.background.runtime, 'node');
    assert.equal(manifest.window, undefined);
    assert.ok(manifest.permissions.includes('notifications'));
    const first = await sdk.pack(source);
    const second = await sdk.pack(source, { output: join(root, 'second.dpk') });
    assert.deepEqual(await readFile(first), await readFile(second));
    assert.deepEqual(await sdk.verify(first), manifest);
    assert.deepEqual(await sdk.inspectPackage(first), manifest);
    await assert.rejects(sdk.pack(source), e => e instanceof DpkError && e.code === 'FileExistsError');
    await sdk.pack(source, { force: true });
    assert.deepEqual(await readFile(join(source, 'manifest.json')), before);
    await assert.rejects(sdk.pack(source, { output: join(source, 'payload', 'bad.dpk') }), /outside payload/);
    await assert.rejects(sdk.initProject(source, { name: 'ts-app' }), e => e.code === 'FileExistsError');
    await writeFile(second, 'invalid archive');
    await assert.rejects(sdk.verify(second), DpkError);
    const bad = JSON.parse(before); bad.background.entry_point = '../escape';
    await writeFile(join(source, 'manifest.json'), JSON.stringify(bad));
    await assert.rejects(sdk.validate(source), /packaged file/);
    const preserved = await readFile(first);
    await assert.rejects(sdk.pack(source, { force: true }), DpkError);
    assert.deepEqual(await readFile(first), preserved);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('reject malformed manifests, symlinks and missing native builds', async () => {
  const root = await mkdtemp(join(tmpdir(), 'dpk-ts-invalid-'));
  const sdk = new DpkSdk();
  try {
    const source = join(root, 'source'); await sdk.initProject(source);
    const manifestPath = join(source, 'manifest.json');
    const good = JSON.parse(await readFile(manifestPath, 'utf8'));
    for (const mutate of [m => m.manifest_version = null, m => m.executables = null,
      m => m.permissions.push('root'), m => m.background.runtime = null,
      m => m.background.args = ['bad\0arg'], m => m.permissions.push('background'),
      m => m.ui = {}, m => m.icons = {32: '../escape'}]) {
      const m = structuredClone(good); mutate(m); await writeFile(manifestPath, JSON.stringify(m));
      await assert.rejects(sdk.validate(source), DpkError);
    }
    await writeFile(manifestPath, JSON.stringify(good));
    if (process.platform !== 'win32') {
      await symlink(manifestPath, join(source, 'payload', 'link'));
      await assert.rejects(sdk.validate(source), /Symlinks/);
    }
    for (const runtime of ['node', 'bash', 'sh', 'native']) {
      const window = join(root, 'window-' + runtime);
      await sdk.initProject(window, { kind: 'both', backgroundRuntime: 'node', windowRuntime: runtime });
      await assert.rejects(sdk.validate(window), /Executable is missing/);
      const m = JSON.parse(await readFile(join(window, 'manifest.json')));
      assert.equal(m.window.runtime, runtime);
      assert.equal(m.window.type, 'desktop');
      assert.ok(!(await readFile(join(window, 'build.mjs'), 'utf8')).includes('python'));
    }
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('archive verification rejects traversal, links, duplicates, missing and corrupt data', async () => {
  const root = await mkdtemp(join(tmpdir(), 'dpk-ts-archive-'));
  const name = 'opt/test/data';
  const hash = createHash('sha256').update('ok').digest('hex');
  const manifest = {format: 1, manifest_version: 1, name: 'legacy', version: '1.0', arch: 'all', files: {[name]: {mode: 420, sha256: hash}}};
  async function archive(filename, entries, m = manifest) {
    const stream = tar.pack(); const path = join(root, filename + '.dpk');
    const pumping = pipeline(stream, createGzip(), createWriteStream(path));
    stream.entry({name: 'manifest.json'}, JSON.stringify(m));
    for (const [header, data] of entries) stream.entry(header, data);
    stream.finalize(); await pumping; return path;
  }
  const regular = [{name: 'payload/' + name}, 'ok'];
  try {
    assert.equal((await new DpkSdk().verify(await archive('valid', [regular]))).name, 'legacy');
    for (const [label, entries] of [
      ['missing', []], ['duplicate', [regular, regular]],
      ['traversal', [[{name: 'payload/opt/../escape'}, 'ok']]],
      ['link', [[{name: 'payload/' + name, type: 'symlink', linkname: '/etc/passwd'}, '']]],
      ['corrupt', [[{name: 'payload/' + name}, 'no']]],
    ]) await assert.rejects(new DpkSdk().verify(await archive(label, entries)), DpkError);
    const valid = await readFile(await archive('truncated', [regular]));
    const short = join(root, 'short.dpk'); await writeFile(short, valid.subarray(0, valid.length - 12));
    await assert.rejects(new DpkSdk().verify(short), DpkError);
    const longName = 'opt/' + 'long/'.repeat(30) + 'ภาษาไทย.txt';
    const pax = {...manifest, files: {[longName]: {mode: 493, sha256: hash}}};
    assert.equal((await new DpkSdk().verify(await archive('pax', [[{name: 'payload/' + longName}, 'ok']], pax))).files[longName].mode, 493);
  } finally { await rm(root, { recursive: true, force: true }); }
});
test('default scaffold packs with no Python or executables on PATH', async () => {
  const root = await mkdtemp(join(tmpdir(), 'dpk-ts-default-'));
  try {
    const source = join(root, 'default-app');
    const sdk = new DpkSdk();
    await sdk.initProject(source);
    assert.equal((await sdk.validate(source)).background.runtime, 'node');
    const previous = process.env.PATH;
    try {
      process.env.PATH = '';
      assert.equal((await sdk.verify(await sdk.pack(source))).name, 'default-app');
    } finally { process.env.PATH = previous; }
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('CLI-only manifests pack and reject invalid commands', async () => {
  const root = await mkdtemp(join(tmpdir(), 'dpk-ts-cli-'));
  const sdk = new DpkSdk();
  try {
    const source = join(root, 'cli-app'); await sdk.initProject(source);
    const path = join(source, 'manifest.json');
    const m = JSON.parse(await readFile(path, 'utf8'));
    const entry = m.background;
    delete m.background; m.permissions = [];
    m.cli = {commands: {'my-tool': {...entry, args: ['two words']}}};
    await writeFile(path, JSON.stringify(m));
    assert.deepEqual((await sdk.verify(await sdk.pack(source))).cli, m.cli);
    for (const cli of [{commands: {}}, {commands: {dev: entry}},
      {commands: {'../bad': entry}}, {commands: {tool: {...entry, runtime: 'invalid'}}},
      {commands: {tool: {...entry, entry_point: 'opt/missing'}}},
      {commands: {tool: {...entry, args: ['\0']}}},
      {commands: {tool: {...entry, runtime: 'native'}}}]) {
      await writeFile(path, JSON.stringify({...m, cli}));
      await assert.rejects(sdk.validate(source), DpkError);
    }
    await writeFile(path, JSON.stringify({...m, installed_commands: {}}));
    await assert.rejects(sdk.validate(source), /reserved/);
  } finally { await rm(root, {recursive: true, force: true}); }
});

test('launcher config validates packaged icons and rejects desktop injection', async () => {
  const root = await mkdtemp(join(tmpdir(), 'dpk-ts-launcher-'));
  const sdk = new DpkSdk();
  try {
    const source = join(root, 'launcher-app'); await sdk.initProject(source);
    const path = join(source, 'manifest.json');
    const m = JSON.parse(await readFile(path, 'utf8'));
    m.window = {...m.background, type: 'desktop'}; delete m.background;
    m.permissions = ['window'];
    const icon = 'opt/apps/launcher-app/icon.svg';
    await writeFile(join(source, 'payload', icon), '<svg xmlns="http://www.w3.org/2000/svg"/>');
    m.launcher = {name: 'App ไทย', icon, categories: ['Utility']};
    await writeFile(path, JSON.stringify(m));
    assert.deepEqual((await sdk.verify(await sdk.pack(source))).launcher, m.launcher);
    for (const launcher of [{name: 'App\nExec=bad'}, {icon: 'opt/missing'}, {categories: ['Utility;System']},
      {exec: '/bin/sh'}, {terminal: false}, {name: ''},
      {entry_point: 'opt/missing'}, {entry_point: '../escape'}, {entry_point: null},
      {runtime: 'node'}, {runtime: null}, {args: []}, {entry_point: m.window.entry_point}]) {
      await writeFile(path, JSON.stringify({...m, launcher}));
      await assert.rejects(sdk.validate(source), DpkError);
    }
    await writeFile(path, JSON.stringify({...m, installed_launchers: {}}));
    await assert.rejects(sdk.validate(source), /reserved/);
    await writeFile(path, JSON.stringify({...m, window: {...m.window, runtime: 'native'}}));
    await assert.rejects(sdk.validate(source), /Native entry point/);
    delete m.window;
    await writeFile(path, JSON.stringify(m));
    await assert.rejects(sdk.validate(source), /requires a format 2 window/);
  } finally { await rm(root, {recursive: true, force: true}); }
});
