// The site has three widths (src/blossom/breakpoints.css). Stylesheets use the
// named queries; LEGACY lists the files still waiting for their section's
// cleanup and only ever shrinks.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

const ROOT=path.resolve(import.meta.dirname,'..');
const LEGACY=new Set(`art-wall blossom/collection blossom/components/morph-search blossom/composition blossom/home-shelves
blossom/integration blossom/reference  catalog-filter-dock chapter-scrub control/content-panel
control/control-center device-shelf discovery-polish  export-sheet guest-access guest-activity history-page
import-layout import-queue import-workspace interface-refinement library-calendar library-online local-title manga-desk
manga-export manga-reader merged-catalog-toolbar music-dock music-import online  privacy reader-chrome
reader-debug reader-morph reader-rail reader-save reader-settings-grid reader-shell reader-surface reader-view-settings
retained-media room-chat-next room-conversation room-lobby shortcut-sheet site-layout site-mobile  
 styles       touch-comfort 
watch-room world-library`.split(/\s+/).map(name=>'src/'+name+'.css'));
const css=dir=>fs.readdirSync(dir,{withFileTypes:true}).flatMap(e=>e.isDirectory()?css(path.join(dir,e.name)):e.name.endsWith('.css')?[path.join(dir,e.name)]:[]);
const files=css(path.join(ROOT,'src')).map(f=>path.relative(ROOT,f).split(path.sep).join('/'));
const tokens=new Set([...fs.readFileSync(path.join(ROOT,'src/blossom/breakpoints.css'),'utf8').matchAll(/@custom-media\s+(--[\w-]+)/g)].map(m=>m[1]));
const media=file=>[...fs.readFileSync(path.join(ROOT,file),'utf8').matchAll(/@media([^{]*)\{/g)].map(m=>m[1].trim());

test('breakpoints are the phone, tablet and desktop widths',()=>{
 const text=fs.readFileSync(path.join(ROOT,'src/blossom/breakpoints.css'),'utf8');
 const widths=new Set([...text.matchAll(/(\d+)px/g)].map(m=>Number(m[1])));
 assert.deepEqual([...widths].sort((a,b)=>a-b),[640,641,1024,1025]);
 assert.ok(['--phone','--tablet','--desktop'].every(t=>tokens.has(t)));
});

test('cleaned stylesheets query widths only through the named breakpoints',()=>{
 const raw=[];
 for(const file of files){
  if(LEGACY.has(file))continue;
  for(const query of media(file))if(/(min|max)-width\s*:/.test(query))raw.push(file+': @media '+query);
 }
 assert.deepEqual(raw,[]);
});

test('every named breakpoint in use is defined',()=>{
 const unknown=[];
 for(const file of files)for(const query of media(file))for(const m of query.matchAll(/\((--[\w-]+)\)/g))if(!tokens.has(m[1]))unknown.push(file+': '+m[1]);
 assert.deepEqual(unknown,[]);
});

test('the legacy list only names files that still need cleaning',()=>{
 const done=[...LEGACY].filter(file=>!files.includes(file)||!media(file).some(q=>/(min|max)-width\s*:/.test(q)));
 assert.deepEqual(done,[],'remove these from LEGACY');
});
