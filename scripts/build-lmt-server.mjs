import {build} from 'vite';
import {resolve} from 'node:path';
import {cp,mkdir,readdir,readFile,writeFile} from 'node:fs/promises';
const out=resolve(process.argv[2]||'/assets');
await build({configFile:false,root:resolve('lmt'),base:'./',publicDir:false,build:{outDir:out,emptyOutDir:true,target:'es2022',chunkSizeWarningLimit:20000}});
await cp('lmt/upstream/dicts',out+'/dicts',{recursive:true});await cp('lmt/upstream/LICENSE',out+'/LICENSE');
for(const name of await readdir('node_modules/onnxruntime-web/dist'))if(/^ort-wasm-simd-threaded(?:\.jsep)?\.(?:mjs|wasm)$/.test(name))await cp('node_modules/onnxruntime-web/dist/'+name,out+'/'+name);
const hashes=await readFile('lmt/upstream/lib/manifests/hashes.ts','utf8');await writeFile(out+'/native-models.json',JSON.stringify(Object.fromEntries([...hashes.matchAll(/"([^"]+\.onnx)":\s*"([a-f0-9]{64})"/g)].map(m=>[m[1],m[2]]))));
