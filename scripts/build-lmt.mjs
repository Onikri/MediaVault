import {build} from 'vite';import{cp,mkdir,readdir,readFile,writeFile}from'node:fs/promises';import{resolve}from'node:path';
await build({configFile:false,root:resolve('lmt'),cacheDir:resolve('.codex-local/cache/vite-lmt'),base:'./',publicDir:false,build:{outDir:resolve('dist/lmt'),emptyOutDir:true,target:'es2022',chunkSizeWarningLimit:20000}});
await cp('lmt/licenses','dist/lmt/licenses',{recursive:true});
await cp('src/vendor/fsr1/LICENSE','dist/FSR1-LICENSE.txt');
await cp('lmt/upstream/dicts','dist/lmt/dicts',{recursive:true});await cp('lmt/upstream/LICENSE','dist/lmt/LICENSE');await mkdir('dist/lmt/upstream',{recursive:true});await cp('lmt/upstream/LICENSE','dist/lmt/upstream/LICENSE');
for(const name of await readdir('node_modules/onnxruntime-web/dist'))if(/^ort-wasm-simd-threaded(?:\.(?:jsep|asyncify))?\.(?:mjs|wasm)$/.test(name))await cp('node_modules/onnxruntime-web/dist/'+name,'dist/lmt/'+name);
await mkdir('dist/lmt/moebius-ort',{recursive:true});
await cp('lmt/licenses/onnxruntime-moebius-MIT.txt','dist/lmt/moebius-ort/LICENSE');
for(const name of await readdir('node_modules/onnxruntime-web-moebius/dist'))if(/^ort-wasm-simd-threaded(?:\.(?:jsep|asyncify))?\.(?:mjs|wasm)$/.test(name))await cp('node_modules/onnxruntime-web-moebius/dist/'+name,'dist/lmt/moebius-ort/'+name);

const nativeHashes=await readFile("lmt/upstream/lib/manifests/hashes.ts","utf8");await writeFile("dist/lmt/native-models.json",JSON.stringify(Object.fromEntries([...nativeHashes.matchAll(/"([^"]+\.onnx)":\s*"([a-f0-9]{64})"/g)].map(m=>[m[1],m[2]])),null,2));
