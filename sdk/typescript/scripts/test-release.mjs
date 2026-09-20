import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const archive = resolve(process.argv[2] ?? '../../out/sdk/devos-dpk-sdk-0.5.0.tgz');
const root = await mkdtemp(join(tmpdir(), 'dpk installed ts '));
try {
  await writeFile(join(root, 'package.json'), JSON.stringify({ private: true, type: 'module' }));
  execFileSync(process.execPath, [process.env.npm_execpath, 'install', '--prefer-offline', '--ignore-scripts',
    '--no-audit', '--no-fund', archive], { cwd: root, stdio: 'inherit' });
  const tests = (await readFile(new URL('../test/sdk.test.mjs', import.meta.url), 'utf8'))
    .replace('../dist/index.js', '@devos/dpk-sdk');
  await writeFile(join(root, 'sdk.test.mjs'), tests);
  execFileSync(process.execPath, ['--test', 'sdk.test.mjs'], { cwd: root, stdio: 'inherit' });
  const types = (await readFile(new URL('../test/types.ts', import.meta.url), 'utf8'))
    .replace('../src/index.js', '@devos/dpk-sdk');
  await writeFile(join(root, 'types.ts'), types);
  execFileSync(process.execPath, [fileURLToPath(new URL('../node_modules/typescript/bin/tsc', import.meta.url)),
    '--strict', '--noEmit', '--target', 'ES2022', '--module', 'NodeNext', 'types.ts'],
    { cwd: root, stdio: 'inherit' });
  console.log('Installed tarball: runtime and public TypeScript declarations passed.');
} finally {
  await rm(root, { recursive: true, force: true });
}
