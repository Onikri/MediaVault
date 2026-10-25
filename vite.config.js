import {copyFileSync, mkdirSync,readFileSync,existsSync,statSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {defineConfig} from 'vite';

const projectRoot = dirname(fileURLToPath(import.meta.url));
const runtimeFiles = [
  'config.js',
  'spotify-callback.html',
  'translation-demo.html',
  'sw.js',
  'crypto.js',
  'drive.js',
  'selftest.html',
  'icon.svg',
  'manifest.webmanifest'
];

export default defineConfig({
  base: './',
  publicDir: false,
  // The standalone AGPL engine is built separately; don't eagerly prebundle
  // its multi-megabyte ONNX/WebLLM graph when starting the main React app.
  optimizeDeps: {entries: ['index.html']},
  server: {port: 8080, strictPort: true,
    watch: {ignored: ['**/.codex-local/**', '**/.venv/**']},
    fs: {deny: ['.env', '.env.*', '*.{crt,pem,key}', '**/.git/**', '**/.codex-local/**', '**/.codex/**', '**/.venv/**', '**/deploy/oracle/data/**']}
  },
  preview: {port: 8080, strictPort: true},
  esbuild: {jsx: 'automatic'},
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    target: 'es2022',
    rollupOptions: {
      onwarn(warning, warn) {
        if(warning.code==='MODULE_LEVEL_DIRECTIVE'&&warning.message.includes('use client'))return;
        warn(warning);
      },
      output: {
        assetFileNames(asset) {
          const names = asset.names || [asset.name];
          return names.includes('manifest.webmanifest')
            ? 'manifest.webmanifest'
            : 'assets/[name]-[hash][extname]';
        }
      }
    }
  },
  plugins: [{
    name:'mediavault-local-lmt',
    configureServer(server){
      server.middlewares.use((request,response,next)=>{
        const path=new URL(request.url,'http://localhost').pathname;
        if(!path.startsWith('/lmt/'))return next();
        const root=resolve(projectRoot,'dist/lmt'),file=resolve(root,decodeURIComponent(path.slice(5)));
        if(!file.startsWith(root+'/')&&!file.startsWith(root+'\\'))return next();
        if(!existsSync(file)||!statSync(file).isFile())return next();
        const extension=file.split('.').pop();
        const types={html:'text/html',js:'application/javascript',mjs:'application/javascript',css:'text/css',wasm:'application/wasm',json:'application/json',ttf:'font/ttf',txt:'text/plain'};
        response.setHeader('Content-Type',types[extension]||'application/octet-stream');
        response.end(readFileSync(file));
      });
    }
  },{
    name: 'mediavault-runtime-files',
    apply: 'build',
    closeBundle() {
      const output = resolve(projectRoot, 'dist');
      mkdirSync(output, {recursive: true});
      for (const file of runtimeFiles) {
        copyFileSync(resolve(projectRoot, file), resolve(output, file));
      }
    }
  }]
});
