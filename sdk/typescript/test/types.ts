import { DpkSdk, type Manifest, type Runtime, type Permission, type LauncherConfig } from '../src/index.js';
const manifest = {
  manifest_version: 2, name: 'typed-app', version: '1.0.0', arch: 'all',
  permissions: ['background', 'window', 'notifications'],
  background: { runtime: 'node', entry_point: 'opt/apps/typed-app/background.js' },
  window: { type: 'desktop', runtime: 'bash', entry_point: 'opt/apps/typed-app/window.sh' },
  cli: { commands: { 'typed-tool': { runtime: 'node', entry_point: 'opt/apps/typed-app/cli.js', args: ['--default'] } } },
  launcher: { name: 'Typed app', categories: ['Development'] },
} satisfies Manifest;
// @ts-expect-error Unsupported runtime must fail at compile time.
const runtime: Runtime = 'typescript';
// @ts-expect-error Unknown permissions must fail at compile time.
const permission: Permission = 'root';
const sdk = new DpkSdk();
// @ts-expect-error Execution settings belong to window, not launcher.
const badLauncher: LauncherConfig = { runtime: 'node' };
// @ts-expect-error Entry points belong to window, not launcher.
const badEntry: LauncherConfig = { entry_point: 'opt/apps/typed-app/main.js' };
const result: Promise<string> = sdk.pack('.', { force: true });
void [manifest, runtime, permission, result];
