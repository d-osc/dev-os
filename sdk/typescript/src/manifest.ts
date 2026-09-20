import { check } from './errors.js';
import type { PackageManifest } from './index.js';

export const LIMIT = 256 * 1024 * 1024;
export const MANIFEST_LIMIT = 2 * 1024 * 1024;
export const runtimes = ['native', 'node', 'bash', 'sh', 'python'];
export function object(value: unknown): value is Record<string, any> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
export function safePath(value: unknown): asserts value is string {
  check(typeof value === 'string' && !/[\\:\x00]/.test(value), 'Unsafe package path');
  const parts = value.split('/');
  check(parts.length > 1 && ['usr', 'opt'].includes(parts[0]) &&
    parts.every(p => p !== '' && p !== '.' && p !== '..'), 'Unsafe package path');
  check(value !== 'usr/bin/dev', 'The package manager is protected');
}
export function checkManifest(m: unknown): asserts m is PackageManifest {
  check(object(m), 'Invalid manifest');
  check(!('installed_commands' in m), 'installed_commands is reserved for the installer');
  check(!('installed_launchers' in m), 'installed_launchers is reserved for the installer');
  check(!('installed_trust' in m), 'installed_trust is reserved for the installer');
  check(!('installed_previous' in m), 'installed_previous is reserved for the installer');
  check(!('ui' in m), 'The ui field was renamed to window');
  check(!('depends' in m), 'Use dependencies instead of depends');
  for (const field of ['dependencies', 'runtime_versions']) {
    if (!(field in m)) continue;
    check(object(m[field]) && Object.keys(m[field]).length <= 128, 'Invalid ' + field);
    for (const [name, constraint] of Object.entries(m[field])) {
      check(/^[a-zA-Z0-9][a-zA-Z0-9._+-]{0,79}$/.test(name), 'Invalid requirement name');
      check(field === 'dependencies' ? name !== m.name : ['node', 'python', 'bash', 'sh'].includes(name), 'Invalid requirement name');
      check(typeof constraint === 'string' && constraint.length > 0 && constraint.length <= 256 &&
        (constraint === '*' || constraint.split(',').every(term => /^\s*(?:~=|==|!=|<=|>=|<|>)\s*[0-9A-Za-z!.*+_-]+\s*$/.test(term))), 'Invalid version requirement');
    }
  }
  check([1, 2].includes(m.format) && ('manifest_version' in m ? m.manifest_version : 1) === m.format, 'Unsupported DPK format');
  for (const field of ['name', 'version']) check(typeof m[field] === 'string' && /^[a-zA-Z0-9][a-zA-Z0-9._+-]{0,79}$/.test(m[field]), 'Invalid ' + field);
  check(['all', 'x86_64'].includes(m.arch), 'Unsupported architecture');
  for (const field of ['display_name', 'short_name', 'description', 'author', 'homepage_url']) {
    if (field in m) check(typeof m[field] === 'string' && m[field].length > 0 && [...m[field]].length <= 2048, 'Invalid ' + field);
  }
  for (const field of ['optional_permissions', 'host_permissions', 'optional_host_permissions', 'content_scripts', 'action']) {
    check(!(field in m), 'Chrome extension field is not supported by DPK: ' + field);
  }
  check(object(m.files) && Object.keys(m.files).length > 0 && Object.keys(m.files).length <= 10000, 'Invalid file inventory');
  for (const [name, spec] of Object.entries(m.files)) {
    safePath(name);
    check(object(spec) && [0o644, 0o755].includes(spec.mode) && typeof spec.sha256 === 'string' && /^[0-9a-f]{64}$/.test(spec.sha256), 'Invalid file inventory entry');
  }
  const executables = 'executables' in m ? m.executables : [];
  check(Array.isArray(executables), 'Invalid executables');
  for (const name of executables) {
    safePath(name); check(Object.hasOwn(m.files, name) && m.files[name].mode === 0o755, 'Executable is missing or not executable: ' + name);
  }
  if ('cli' in m) {
    check(object(m.cli) && Object.keys(m.cli).length === 1 && object(m.cli.commands), 'cli must contain commands');
    const commands = Object.entries(m.cli.commands);
    check(commands.length > 0 && commands.length <= 128, 'Invalid cli.commands');
    for (const [name, entry] of commands) {
      check(/^[a-zA-Z0-9][a-zA-Z0-9._+-]{0,79}$/.test(name), 'Invalid CLI command name');
      safePath('usr/bin/' + name);
      check(!Object.hasOwn(m.files, 'usr/bin/' + name), 'CLI launcher conflicts with payload');
      check(object(entry) && Object.keys(entry).every(key => ['runtime', 'entry_point', 'args'].includes(key)), 'Invalid CLI entry');
      const runtime = 'runtime' in entry ? entry.runtime : 'native';
      check(runtimes.includes(runtime), 'Unsupported CLI runtime');
      check(typeof entry.entry_point === 'string' && Object.hasOwn(m.files, entry.entry_point), 'CLI entry point must be a packaged file');
      if (runtime === 'native') check(executables.includes(entry.entry_point), 'Native CLI entry point must be in executables');
      const args = 'args' in entry ? entry.args : [];
      check(Array.isArray(args) && args.length <= 64 && args.every(a => typeof a === 'string' && !a.includes('\0') && [...a].length <= 4096), 'Invalid CLI args');
    }
  }
  const icons = 'icons' in m ? m.icons : {};
  if ('launcher' in m) {
    const config = m.launcher;
    check(m.format === 2 && object(m.window), 'launcher requires a format 2 window');
    check(object(config), 'Invalid launcher config');
    check(!['runtime', 'entry_point', 'args'].some(k => k in config), 'Configure runtime, entry_point and args under window, not launcher');
    check(Object.keys(config).every(k => ['name', 'comment', 'icon', 'categories'].includes(k)), 'Invalid launcher config');
    const name = 'name' in config ? config.name : m.display_name ?? m.name;
    const comment = 'comment' in config ? config.comment : '';
    check(typeof name === 'string' && name.trim().length > 0 && [...name].length <= 128 && !/[\x00-\x1f\x7f]/.test(name), 'Invalid launcher.name');
    check(typeof comment === 'string' && [...comment].length <= 512 && !/[\x00-\x1f\x7f]/.test(comment), 'Invalid launcher.comment');
    const categories = 'categories' in config ? config.categories : ['Utility'];
    check(Array.isArray(categories) && categories.length > 0 && categories.length <= 16 && new Set(categories).size === categories.length && categories.every(c => typeof c === 'string' && /^[A-Za-z][A-Za-z0-9-]{0,63}$/.test(c)), 'Invalid launcher.categories');
    if ('icon' in config) {
      safePath(config.icon);
      check(!/[\x00-\x1f\x7f]/.test(config.icon) && Object.hasOwn(m.files, config.icon), 'Launcher icon must be a packaged file');
    }
    check(!Object.hasOwn(m.files, `usr/share/applications/devos-${m.name}.desktop`), 'Launcher conflicts with payload');
  }
  check(object(icons), 'Invalid icons');
  for (const [size, name] of Object.entries(icons)) {
    check(/^[1-9][0-9]{0,3}$/.test(size), 'Invalid icon size'); safePath(name);
    check(Object.hasOwn(m.files, name), 'Icon is missing from payload');
  }
  if (m.format === 1) {
    check(!['permissions', 'background', 'window'].some(field => field in m), 'Runtime features require manifest_version 2');
    return;
  }
  const permissions = m.permissions;
  check(Array.isArray(permissions) && new Set(permissions).size === permissions.length && permissions.every(p => ['background', 'window', 'storage', 'network', 'notifications'].includes(p)), 'Unknown or duplicate permission');
  check(Object.keys(m.files).every(name => name.startsWith(`opt/apps/${m.name}/`)), 'Format 2 payload must be beneath opt/apps/' + m.name + '/');
  check('background' in m || 'window' in m || 'cli' in m, 'No background, window or CLI entry point');
  for (const kind of ['background', 'window']) {
    if (!(kind in m)) { check(!permissions.includes(kind), 'Permission has no entry point: ' + kind); continue; }
    check(permissions.includes(kind), 'Missing permission: ' + kind);
    const entry = m[kind];
    check(object(entry) && Object.keys(entry).every(key => ['entry_point', 'runtime', 'args', 'type'].includes(key)), 'Invalid ' + kind + ' declaration');
    const runtime = 'runtime' in entry ? entry.runtime : 'native';
    check(runtimes.includes(runtime), 'Unsupported runtime');
    check(kind === 'window' ? entry.type === 'desktop' : !('type' in entry), 'Invalid entry point type');
    check(typeof entry.entry_point === 'string' && Object.hasOwn(m.files, entry.entry_point), 'Entry point must be a packaged file');
    if (runtime === 'native') check(executables.includes(entry.entry_point), 'Native entry point must be in executables');
    const args = 'args' in entry ? entry.args : [];
    check(Array.isArray(args) && args.length <= 64 && args.every(a => typeof a === 'string' && !a.includes('\0') && [...a].length <= 4096), 'Invalid entry point args');
  }
}
