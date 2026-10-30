import {copyFileSync, mkdirSync, cpSync} from 'node:fs';
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
  cacheDir: resolve(projectRoot,'.codex-local/cache/vite'),
  base: './',
  publicDir: false,
  // Test output can be a junction into the private D: task cache. Keep HTML
  // proxy module IDs consistent with the URL used to load that harness.
  resolve: {preserveSymlinks: true},
  // The standalone AGPL engine is built separately; don't eagerly prebundle
  // its multi-megabyte ONNX/WebLLM graph when starting the main React app.
  optimizeDeps: {entries: ['index.html']},
  server: {port: 8080, strictPort: true,watch:{ignored:path=>path.replaceAll('\\','/').startsWith(resolve(projectRoot,'.codex-local').replaceAll('\\','/')+'/')}},
  preview: {port: 8080, strictPort: true},
  esbuild: {jsx: 'automatic'},
  worker: {format: 'es'},
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
    name: 'mediavault-runtime-files',
    apply: 'build',
    closeBundle() {
      const output = resolve(projectRoot, 'dist');
      mkdirSync(output, {recursive: true});
      cpSync(resolve(projectRoot,'reader-fonts'),resolve(output,'reader-fonts'),{recursive:true});
      for (const file of runtimeFiles) {
        copyFileSync(resolve(projectRoot, file), resolve(output, file));
      }
    }
  }]
});
