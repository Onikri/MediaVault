import {build} from 'vite';import{cp,mkdir,readdir}from'node:fs/promises';import{resolve}from'node:path';
import {svelte} from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';
await build({configFile:false,root:resolve('lmt'),base:'./',publicDir:false,
 resolve:{alias:{'@/entrypoints/content/translation-registry':resolve('lmt/editor-registry.js'),'@':resolve('lmt/upstream')}},
 plugins:[svelte({configFile:false}),tailwindcss()],
 build:{outDir:resolve('dist/lmt'),emptyOutDir:true,target:'es2022',chunkSizeWarningLimit:20000,
 rollupOptions:{input:{engine:resolve('lmt/index.html'),editor:resolve('lmt/editor.html')}}}});
await cp('src/vendor/fsr1/LICENSE','dist/FSR1-LICENSE.txt');
await cp('lmt/upstream/dicts','dist/lmt/dicts',{recursive:true});await cp('lmt/upstream/LICENSE','dist/lmt/LICENSE');await mkdir('dist/lmt/upstream',{recursive:true});await cp('lmt/upstream/LICENSE','dist/lmt/upstream/LICENSE');
await cp('lmt/upstream/assets/fonts','dist/lmt/font-licenses',{recursive:true,filter:source=>!source.endsWith('.ttf')});
for(const name of await readdir('node_modules/onnxruntime-web/dist'))if(/^ort-wasm-simd-threaded(?:\.jsep)?\.(?:mjs|wasm)$/.test(name))await cp('node_modules/onnxruntime-web/dist/'+name,'dist/lmt/'+name);
