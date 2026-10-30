import test from 'node:test';import assert from 'node:assert/strict';
import {DirectChapter} from '../src/manga-direct.js';
import {translationConfig} from '../src/manga-translation.js';
import {RequestPacer,labelPackets} from '../src/reader-chapter-pipeline.js';
import {cachedChapterEntries,encodeCleanPage,decodeCleanPage} from '../src/reader-chapter-cache.js';
const tick=()=>new Promise(r=>setTimeout(r,0));

test('chapter downloads/detects ahead independently, sends ordered pairs on rotating keys, and cleans before API completion',async()=>{
 let firstReady,cloudReady;const first=new Promise(r=>firstReady=r),cloud=new Promise(r=>cloudReady=r),downloads=[],detected=[],cleaned=[],sent=[],resolved=[];
 const c=new DirectChapter({entries:Array.from({length:10},(_,i)=>({async:async()=>{downloads.push(i);return new Blob(['page'+i]);}})),scope:'fixture',config:translationConfig({engine:'direct',cache:false}),serverSlots:[0,1,2],service:()=>({}),pacer:{reserve:async()=>{}},cacheKey:async blob=>blob.text(),
  prepare:async(blob,i)=>{if(i===0)await first;detected.push(i);return{id:'P'+(i+1),page:i+1,width:100,height:100,image:'fixture',mime:'image/png',regions:[{id:'P'+(i+1)+'_B1',bbox:[10,10,60,60],layout_bbox:[5,5,75,75]}]};},
  google:async(pages,options)=>{sent.push({pages:pages.map(p=>p.page),key:options.key});await cloud;return{pages:pages.map(p=>({page:p.page,width:100,height:100,regions:p.regions.map(r=>({uid:r.id,text_bbox:r.bbox,layout_bbox:r.layout_bbox,ru_translation:'Привет'}))}))};},renderPage:async(blob,page)=>({regions:page.regions,timings:{}})});
 c.canvasTask=async message=>{assert.equal(message.operation,'clean-prepare');cleaned.push(message.page.regions[0].uid);return{cleanedImage:new Uint8Array([1,2,3]).buffer,regions:[]};};
 try{
  c.request(9,null);const jobs=[...c.jobs.values()];for(const j of jobs)j.promise.then(()=>resolved.push(j.index));
  for(let n=0;n<30&&detected.length<9;n++)await tick();assert.equal(downloads.length,10);assert.equal(detected.length,9);assert.equal(sent.length,0);
  firstReady();for(let n=0;n<30&&sent.length<3;n++)await tick();assert.deepEqual(sent.map(p=>p.pages),[[1,2],[3,4],[5,6]]);assert.equal(cleaned.length,10);assert.equal(resolved.length,0);assert.ok(c.activePages<=9);
  cloudReady();await Promise.all(jobs.map(j=>j.promise));assert.deepEqual(sent.map(p=>p.pages),[[1,2],[3,4],[5,6],[7,8],[9,10]]);assert.deepEqual(sent.map(p=>p.key),['oracle-slot:0','oracle-slot:1','oracle-slot:2','oracle-slot:0','oracle-slot:1']);assert.equal(c.keyBusy.size,0);
 }finally{firstReady();cloudReady();c.close();}
});

test('credential pacer enforces 15 requests per rolling minute per key without retrying',async()=>{
 let now=0;const starts=[],p=new RequestPacer({now:()=>now,wait:async ms=>{now+=ms;}});
 await p.reserve('a');await p.reserve('b');assert.equal(now,0);
 for(let n=0;n<20;n++){await p.reserve('a');starts.push(now);}
 for(const t of starts)assert.ok(starts.filter(v=>v>=t&&v<t+60000).length<=15);assert.ok(starts.every((t,i)=>!i||t-starts[i-1]>=4000));
});

test('chapter source cache deduplicates reads and reuses disk pages after nine-page RAM eviction',async()=>{
 const stored=new Map();let fetched=0;const entries=cachedChapterEntries(Array.from({length:12},(_,i)=>({async:async()=>{fetched++;return new Blob(['page'+i]);}})),'account:library','chapter',{read:async(s,c,i)=>stored.get(s+c+i)||null,write:async(s,c,i,k,b)=>{stored.set(s+c+i,b);return true;}});
 const [a,b]=await Promise.all([entries[0].async(),entries[0].async()]);assert.equal(a,b);assert.equal(fetched,1);
 for(const e of entries)await e.async();assert.equal(fetched,12);assert.equal(await(await entries[0].async()).text(),'page0');assert.equal(fetched,12);
 const encoded=await encodeCleanPage({width:100,regions:[{uid:'P1_B1',runs:[1,3]}],cleanedImage:new Uint8Array([2,4,8]).buffer}),decoded=await decodeCleanPage(encoded);assert.deepEqual([...new Uint8Array(decoded.cleanedImage)],[2,4,8]);assert.deepEqual(decoded.regions[0].runs,[1,3]);
});

test('legacy one-page preferences migrate to two-page packets; three-page packets remain available',()=>{
 assert.equal(translationConfig({version:9,directBatchPages:1}).directBatchPages,2);assert.equal(translationConfig({directBatchPages:3}).directBatchPages,3);assert.equal(translationConfig().prefetch,9);
});

test('dense two-page input retains two images in each label-budget shard',()=>{
 const pages=[1,2].map(n=>({page:n,image:'image'+n,regions:Array.from({length:80},(_,i)=>({id:'P'+n+'_B'+i}))})),packets=labelPackets(pages);
 assert.equal(packets.length,2);assert.ok(packets.every(p=>p.length===2&&p[0].image==='image1'&&p[1].image==='image2'));
 assert.deepEqual(packets.map(p=>p.reduce((n,v)=>n+v.regions.length,0)),[100,60]);assert.equal(new Set(packets.flatMap(p=>p.flatMap(v=>v.regions.map(r=>r.id)))).size,160);
});

test('concurrent reservations for one credential are serialized',async()=>{
 let now=0;const p=new RequestPacer({now:()=>now,wait:async ms=>{now+=ms;}});await Promise.all(Array.from({length:4},()=>p.reserve('one')));assert.deepEqual(p.starts.get('one'),[0,4000,8000,12000]);
});
