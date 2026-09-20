import { createReadStream, createWriteStream } from 'node:fs';
import { lstat, readdir, readFile, realpath, mkdir, mkdtemp, rm, link, rename, open } from 'node:fs/promises';
import { resolve, join, dirname, basename, relative, isAbsolute, extname } from 'node:path';
import { createHash } from 'node:crypto';
import { createGzip, createGunzip } from 'node:zlib';
import { Transform } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import tar from 'tar-stream';
import { check, guarded } from './errors.js';
import { checkManifest, object, safePath, LIMIT, MANIFEST_LIMIT } from './manifest.js';
import type { PackageManifest, PackOptions } from './index.js';

function byteLimit(max: number) {
  let total = 0;
  return new Transform({ transform(chunk: Buffer, _encoding, callback) {
    total += chunk.length;
    callback(total > max ? new Error('Package exceeds size limit') : null, chunk);
  } });
}
async function hash(path: string) {
  const digest = createHash('sha256');
  await pipeline(createReadStream(path), byteLimit(LIMIT), digest);
  return digest.digest('hex');
}
async function regular(path: string) {
  const stat = await lstat(path);
  check(stat.isFile() && !stat.isSymbolicLink(), 'Only regular files are supported (no symlinks)');
  return stat;
}
/** Check each component again before reading to reject symlinks in parents. */
async function payloadFile(root: string, name: string) {
  let path = root;
  check((await lstat(path)).isDirectory() && !(await lstat(path)).isSymbolicLink(), 'payload must be a regular directory');
  const parts = name.split('/');
  for (const part of parts.slice(0, -1)) {
    path = join(path, part); const stat = await lstat(path);
    check(stat.isDirectory() && !stat.isSymbolicLink(), 'Symlinks are not supported');
  }
  return regular(join(root, name));
}
export async function validate(source = '.'): Promise<PackageManifest> {
  return guarded(async () => {
    const path = join(source, 'manifest.json');
    check((await regular(path)).size <= MANIFEST_LIMIT, 'Manifest exceeds 2 MiB limit');
    const m: unknown = JSON.parse(await readFile(path, 'utf8'));
    check(object(m), 'Invalid manifest');
    if (!('manifest_version' in m)) m.manifest_version = 1;
    m.format = m.manifest_version;
    m.files = {};
    const files = m.files;
    const executables = 'executables' in m ? m.executables : [];
    check(Array.isArray(executables), 'Invalid executables');
    const payload = join(source, 'payload');
    const root = await lstat(payload);
    check(root.isDirectory() && !root.isSymbolicLink(), 'payload must be a regular directory');
    let total = 0, count = 0;
    async function walk(directory: string, prefix = '') {
      for (const name of (await readdir(directory)).sort()) {
        const path = join(directory, name), key = prefix + name;
        const stat = await lstat(path);
        check(!stat.isSymbolicLink(), 'Symlinks are not supported');
        if (stat.isDirectory()) { await walk(path, key + '/'); continue; }
        check(stat.isFile(), 'Only regular files are supported'); safePath(key);
        total += stat.size; count++;
        check(total <= LIMIT && count <= 10000, 'Package exceeds size or file count limit');
        files[key] = { sha256: await hash(path), mode: executables.includes(key) ? 0o755 : 0o644 };
      }
    }
    await walk(payload); checkManifest(m);
    check(Buffer.byteLength(JSON.stringify(m)) <= MANIFEST_LIMIT, 'Manifest exceeds 2 MiB limit');
    return m;
  });
}
export async function inspectPackage(path: string): Promise<PackageManifest> {
  return guarded(async () => {
    check(extname(path) === '.dpk', 'Only .dpk packages are accepted');
    const extract = tar.extract();
    // Includes tar/PAX overhead, bounded separately from the 256 MiB payload.
    const pumping = pipeline(createReadStream(path), byteLimit(LIMIT + 32 * 1024 * 1024),
      createGunzip(), byteLimit(LIMIT + 32 * 1024 * 1024), extract);
    // Attach a rejection handler immediately while the async iterator consumes entries.
    void pumping.catch(() => {});
    let manifest: PackageManifest | undefined, total = 0;
    const seen = new Set<string>();
    try {
      for await (const entry of extract) {
        const h = entry.header;
        check(h.type === 'file' && Number.isSafeInteger(h.size) && h.size! >= 0, 'Only regular payload files are supported');
        if (!manifest) {
          check(h.name === 'manifest.json' && h.size! <= MANIFEST_LIMIT, 'Invalid manifest');
          const chunks: Buffer[] = [];
          for await (const chunk of entry) chunks.push(chunk as Buffer);
          const m: unknown = JSON.parse(Buffer.concat(chunks).toString('utf8'));
          checkManifest(m); manifest = m; continue;
        }
        check(h.name.startsWith('payload/'), 'Only regular payload files are supported');
        const name = h.name.slice(8); safePath(name);
        check(Object.hasOwn(manifest.files, name) && !seen.has(name), 'Unexpected or duplicate file');
        total += h.size!; check(total <= LIMIT, 'Package exceeds 256 MiB limit');
        const digest = createHash('sha256');
        for await (const chunk of entry) digest.update(chunk as Buffer);
        check(digest.digest('hex') === manifest.files[name].sha256, 'Checksum mismatch: ' + name);
        seen.add(name);
      }
      await pumping;
      check(manifest && seen.size === Object.keys(manifest.files).length, 'Missing payload files');
      return manifest;
    } catch (error) {
      extract.destroy(error as Error); await pumping.catch(() => {}); throw error;
    }
  });
}
export const verify = inspectPackage;
function inside(root: string, path: string) {
  const rel = relative(root, path);
  return rel === '' || (!rel.startsWith('..' + (process.platform === 'win32' ? '\\' : '/')) && rel !== '..' && !isAbsolute(rel));
}
async function resolvedFuture(path: string): Promise<string> {
  try { return await realpath(path); }
  catch (e) { if ((e as NodeJS.ErrnoException).code !== 'ENOENT') throw e; }
  return join(await resolvedFuture(dirname(path)), basename(path));
}
export async function pack(source = '.', options: PackOptions = {}): Promise<string> {
  return guarded(async () => {
    source = resolve(source);
    const manifest = await validate(source);
    const output = resolve(options.output ?? join(source, 'dist', `${manifest.name}-${manifest.version}-${manifest.arch}.dpk`));
    check(extname(output) === '.dpk', 'Output must end with .dpk');
    const existing = await lstat(output).catch(e => { if (e.code !== 'ENOENT') throw e; return undefined; });
    check(!existing?.isSymbolicLink(), 'Refusing a symlink output');
    if (existing && !options.force) throw Object.assign(new Error('Output exists; use force to replace it'), { code: 'EEXIST' });
    const payload = await realpath(join(source, 'payload'));
    check(!inside(payload, await resolvedFuture(output)), 'Output must be outside payload/');
    await mkdir(dirname(output), { recursive: true });
    const temporary = await mkdtemp(join(dirname(output), '.dpk-pack-'));
    const archive = join(temporary, 'finished.dpk');
    try {
      const stream = tar.pack();
      const pumping = pipeline(stream, createGzip({ level: 9 }), createWriteStream(archive, { flags: 'wx' }));
      void pumping.catch(() => {});
      const header = { type: 'file' as const, uid: 0, gid: 0, mtime: new Date(0) };
      try {
        await new Promise<void>((done, fail) => stream.entry({ ...header, name: 'manifest.json', mode: 0o644 },
          Buffer.from(JSON.stringify(manifest)), e => e ? fail(e) : done()));
        let total = 0;
        for (const [name, spec] of Object.entries(manifest.files)) {
          const stat = await payloadFile(payload, name); total += stat.size;
          check(total <= LIMIT, 'Package exceeds 256 MiB limit');
          await pipeline(createReadStream(join(payload, name)), stream.entry({ ...header, name: 'payload/' + name, size: stat.size, mode: spec.mode }));
        }
        stream.finalize(); await pumping;
      } catch (error) { stream.destroy(error as Error); await pumping.catch(() => {}); throw error; }
      await verify(archive);
      const fd = await open(archive, 'r+'); try { await fd.sync(); } finally { await fd.close(); }
      if (options.force) await rename(archive, output); else await link(archive, output);
      return output;
    } finally { await rm(temporary, { recursive: true, force: true }); }
  });
}
