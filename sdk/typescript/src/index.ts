export type Runtime = 'native' | 'node' | 'bash' | 'sh' | 'python';
export type Permission = 'background' | 'window' | 'storage' | 'network' | 'notifications';
export interface EntryPoint { runtime?: Runtime; entry_point: string; args?: string[] }
export interface WindowEntry extends EntryPoint { type: 'desktop' }
export interface CliConfig { commands: Record<string, EntryPoint> }
export interface LauncherConfig { name?: string; comment?: string; icon?: string; categories?: string[] }
export interface ManifestBase {
  name: string; version: string; arch: 'all' | 'x86_64';
  display_name?: string; short_name?: string; description?: string;
  author?: string; homepage_url?: string; icons?: Record<string, string>;
  executables?: string[];
  cli?: CliConfig;
  dependencies?: Record<string, string>;
  runtime_versions?: Partial<Record<Exclude<Runtime, 'native'>, string>>;
}
export interface LegacyManifest extends ManifestBase {
  manifest_version?: 1; permissions?: never; background?: never; window?: never;
}
export interface AppManifest extends ManifestBase {
  manifest_version: 2; permissions: Permission[];
  background?: EntryPoint; window?: WindowEntry;
  launcher?: LauncherConfig;
}
/** Source manifest. validate() additionally checks paths, permissions and payload. */
export type Manifest = LegacyManifest | AppManifest;
export type PackageManifest = Manifest & {
  manifest_version: 1 | 2; format: 1 | 2;
  files: Record<string, { sha256: string; mode: 420 | 493 }>;
};
export interface InitOptions {
  name?: string; runtime?: Runtime; kind?: 'background' | 'window' | 'both';
  backgroundRuntime?: Runtime; windowRuntime?: Runtime;
  permissions?: Array<'network' | 'notifications' | 'storage'>;
}
export interface PackOptions { output?: string; force?: boolean }
export { DpkError } from './errors.js';
export { initProject } from './scaffold.js';
export { validate, pack, inspectPackage, verify } from './core.js';
import { initProject } from './scaffold.js';
import { validate, pack, inspectPackage, verify } from './core.js';
/** Pure Node.js SDK; does not launch Python or other build tools. */
export class DpkSdk {
  initProject = initProject;
  validate = validate;
  pack = pack;
  inspectPackage = inspectPackage;
  verify = verify;
}
