import { DpkSdk, type Manifest } from '@devos/dpk-sdk';

const sdk = new DpkSdk();
await sdk.initProject('my-app', {
  backgroundRuntime: 'node', permissions: ['notifications'],
});
const manifest: Manifest = await sdk.validate('my-app');
console.log(manifest.name);
const output = await sdk.pack('my-app');
await sdk.verify(output);
console.log(output);
