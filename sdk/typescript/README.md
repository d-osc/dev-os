# Dev OS TypeScript SDK 0.5

`LauncherConfig` มีเฉพาะ `name?`, `comment?`, `icon?`, `categories?` สำหรับ format 2 ที่มี window ตัวติดตั้งสร้าง Application Menu entry และใช้ `window.runtime`, `window.entry_point`, `window.args` เมื่อเปิดแอป ย้าย execution fields จาก launcher ไป window ก่อนใช้รุ่นนี้ ดู [ตัวอย่างและการยืนยัน permissions](../../DPK-RUNTIME.md) SDK ใช้ Node.js โดยตรงเช่นเดิม

รองรับ type `CliConfig` และ `manifest.cli.commands` สำหรับกำหนดคำสั่งแล้ว เช่น `cli: { commands: { "my-app": { runtime: "node", entry_point: "opt/apps/my-app/cli.js", args: ["--color=auto"] } } }` ใช้ได้ทั้ง format 1/2 และ CLI-only format 2 ที่มี `permissions: []`

SDK ตรวจ/pack manifest ส่วนตัวจัดการ `dev` รุ่นใหม่สร้าง `/usr/bin/<command>` ตอน install และถอนพร้อมแพ็กเกจ CLI เป็นคำสั่ง Unix ปกติด้วยสิทธิ์ผู้เรียก ไม่ใช้ sandbox/permissions ของ background/window ดู [รายละเอียด CLI](../../DPK-FORMAT.md) รุ่นนี้ยังใช้ Node.js โดยตรง ไม่เรียก Python

SDK เขียนด้วย TypeScript และทำงานบน Node.js 20+ แบบ ESM โดยตรง ไม่เรียก Python ไม่มี Python bridge หรือไฟล์ .pyz ใน npm package

## ติดตั้ง

จาก root ของ Dev OS checkout:

```sh
npm install ./out/sdk/devos-dpk-sdk-0.5.0.tgz
```

ยังไม่ได้ publish บน npm registry แพ็กเกจใช้ tar-stream เป็น dependency สำหรับอ่าน/เขียน TAR และใช้ Node.js สำหรับ gzip, SHA-256 และ filesystem

```ts
import { DpkSdk, type Manifest } from '@devos/dpk-sdk';

const sdk = new DpkSdk();
await sdk.initProject('my-app', {
  backgroundRuntime: 'node', permissions: ['notifications'],
});
const manifest: Manifest = await sdk.validate('my-app');
const archive = await sdk.pack('my-app');
console.log(manifest.name, archive, await sdk.verify(archive));
```

Compile TypeScript เป็น JavaScript ด้วย configuration ของโปรเจกต์ก่อนรัน หรือใช้ JavaScript ESM โดยเอา type annotation ออก

## API

ทุกเมธอดคืน Promise และใช้เป็น standalone exports ได้ เช่น `import { pack } from '@devos/dpk-sdk'`

- `initProject(directory, options?)`: สร้าง source ใหม่ ไม่เขียนทับ directory เดิม
- `validate(source = '.')`: ตรวจ manifest, payload, permission และ hash; คืน `PackageManifest`
- `pack(source = '.', { output?, force? }?)`: คืน absolute path ของ `.dpk` ค่าเริ่มต้น `SOURCE/dist/name-version-arch.dpk`
- `inspectPackage(path)` / `verify(path)`: ตรวจ archive ทุกไฟล์และ SHA-256 โดยไม่แตกไฟล์ลงดิสก์
- `DpkError`: มี `message` และ `code`

`InitOptions`: `name`, `runtime`, `kind`, `backgroundRuntime`, `windowRuntime`, `permissions`

ค่าเริ่มต้นรุ่น 0.2 เป็น **Node background** (`kind: 'background'`, `runtime: 'node'`) จึงสร้างและ pack ได้ด้วย Node.js อย่างเดียว ไม่รับ `SdkOptions.python` หรือ `DPK_PYTHON` อีกต่อไป

Type `Manifest` ใช้ชื่อ field เดียวกับ `manifest.json` เช่น `entry_point`, `manifest_version`, `window.type: 'desktop'` รองรับ format 1 และ 2 ชนิดข้อมูลช่วยตรวจ syntax ตอน compile แต่ต้องเรียก `validate` เพื่อตรวจไฟล์จริงด้วย

## Window และ native Linux binary

```ts
await sdk.initProject('desktop-app', {
  kind: 'both', backgroundRuntime: 'node', windowRuntime: 'bash',
});
```

Starter หน้าต่างใช้ native X11 binary; Node/Bash/sh launcher เรียก binary นี้โดยตรง ไม่เรียก Python ต้อง compile บน Linux ก่อน validate/pack:

```sh
node desktop-app/build.mjs
```

ต้องมี C compiler, X11 headers และ libX11 ใช้ `CC` และ `DEVOS_X11_INCLUDE` กำหนด compiler/include path ได้ Build script สร้าง x86_64 payload จึงต้องใช้ x86_64 toolchain ส่วน native background ใช้ static libc development files

SDK ไม่ compile หรือรัน source โดยอัตโนมัติ ถ้ามี binary อยู่แล้ว ให้วางใน payload และกำหนด manifest/executables ได้โดยตรง

Runtime ใน manifest ยังรองรับ `native`, `node`, `bash`, `sh`, `python` เพื่อ pack แอปเดิมได้ หากผู้พัฒนาเลือก runtime `python` เอง แอปนั้นต้องมี Python บนเครื่องปลายทาง แต่เครื่อง pack ไม่ต้องมี Python ส่วนแอป TypeScript ให้ compile เป็น JavaScript และใช้ runtime `node`

## การตรวจสอบและขอบเขต

- ส่งออก gzip TAR ที่ manifest.json อยู่ก่อน payload และอ่านได้ด้วย Dev OS package manager
- ตรวจ SHA-256, path traversal, symlink, ไฟล์ซ้ำ/หาย, permissions, entry points, executable modes
- จำกัด payload 256 MiB / 10,000 ไฟล์, manifest 2 MiB และจำกัดขนาด stream รวม overhead
- ประมวลผล payload ผ่าน stream ไม่โหลดทั้ง archive เข้า memory
- ไม่เขียนทับ output เว้นแต่ `force: true`; ตรวจ archive ที่สร้างก่อน publish แบบ atomic
- input เดิมและ Node/zlib toolchain เดิมให้ bytes ซ้ำได้ แต่ไม่รับประกันว่า bytes ตรงกับ Python packer
- ไม่มี install, launch, dependency resolver หรือ signature verification ใน SDK

## พัฒนาและทดสอบ

```sh
cd sdk/typescript
npm ci
npm test
npm pack --pack-destination ../../out/sdk
npm run test:release
```

ไม่ต้อง build Python SDK ก่อน `npm run build` คัดลอก C starter assets และ compile TypeScript เท่านั้น Test ครอบคลุมการ pack ขณะ PATH ว่าง, invalid manifests, traversal, symlink (Linux), archive corruption, PAX/Unicode paths, no-overwrite, deterministic output และการติดตั้ง npm tarball แยกจาก checkout

Compatibility test กับตัวจัดการ Dev OS เดิมแยกอยู่ใน `scripts/test-compat.mjs`; Python ถูกใช้เฉพาะฝั่งตัวจัดการเดิมใน test นี้ ไม่ใช่ dependency ของ SDK
