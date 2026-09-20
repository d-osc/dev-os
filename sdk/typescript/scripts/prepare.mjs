import { copyFile, mkdir } from 'node:fs/promises';
const assets = new URL('../assets/', import.meta.url);
await mkdir(assets, { recursive: true });
for (const name of ['background.c', 'window.c', 'label.c']) {
  await copyFile(new URL('../../../examples/native-counter/' + name, import.meta.url), new URL(name, assets));
}
