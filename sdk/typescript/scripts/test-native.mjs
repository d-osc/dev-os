import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import assert from 'node:assert/strict';
import { DpkSdk } from '../dist/index.js';
if (process.platform !== 'linux') throw new Error('Run on Linux with a C compiler and X11 development files');
const root = await mkdtemp(join(tmpdir(), 'dpk-native-ts-'));
try {
  const sdk = new DpkSdk();
  for (const runtime of ['node', 'bash', 'sh', 'native']) {
    const source = join(root, 'window-' + runtime);
    await sdk.initProject(source, {kind: 'both', backgroundRuntime: runtime, windowRuntime: runtime});
    execFileSync(process.execPath, [join(source, 'build.mjs')], {stdio: 'inherit'});
    const manifest = await sdk.verify(await sdk.pack(source));
    assert.equal(manifest.window.runtime, runtime);
    assert.equal(manifest.arch, 'x86_64');
    for (const path of manifest.executables) {
      const bytes = await readFile(join(source, 'payload', path));
      assert.deepEqual([...bytes.subarray(0, 4)], [127, 69, 76, 70]);
      assert.equal(bytes.readUInt16LE(18), 62); // EM_X86_64
    }
    assert.ok(Object.keys(manifest.files).every(path => !path.endsWith('.py')));
  }
  console.log('Node/Bash/sh/native desktop scaffolds compile and pack with no Python.');
} finally { await rm(root, {recursive: true, force: true}); }
