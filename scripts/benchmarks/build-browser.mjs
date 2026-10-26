import{build}from'vite';import{mkdir,cp,readdir,writeFile}from'node:fs/promises';import{resolve}from'node:path';
const root=resolve('scripts/benchmarks'),out=resolve(process.argv[2]||'test-output/manga-quality/browser');
await build({configFile:false,root,base:'./',publicDir:false,build:{outDir:out,emptyOutDir:true,target:'es2022',chunkSizeWarningLimit:20000,rollupOptions:{input:root+'/benchmark.html'}}});
await cp('lmt/upstream/dicts',out+'/dicts',{recursive:true});await mkdir(out+'/ort',{recursive:true});for(const f of await readdir('node_modules/onnxruntime-web/dist'))if(/^ort-wasm-simd-threaded(?:\.jsep)?\.(?:mjs|wasm)$/.test(f))await cp('node_modules/onnxruntime-web/dist/'+f,out+'/ort/'+f);
const hashes=await(await import('node:fs/promises')).readFile('lmt/upstream/lib/manifests/hashes.ts','utf8');await writeFile(out+'/native-models.json',JSON.stringify(Object.fromEntries([...hashes.matchAll(/"([^"]+\.onnx)":\s*"([a-f0-9]{64})"/g)].map(m=>[m[1],m[2]]))));
