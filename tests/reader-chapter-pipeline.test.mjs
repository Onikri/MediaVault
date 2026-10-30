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
  c.request(0,null);const jobs=[...c.jobs.values()];for(const j of jobs)j.promise.then(()=>resolved.push(j.index));
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

test('a distant navigation finishes active packets, prioritizes four pages on one credential, then resumes and retains all stage totals',async()=>{
 const sent=[],release=[];const c=new DirectChapter({entries:Array.from({length:16},(_,i)=>({async:async()=>new Blob([String(i)])})),scope:'focus',config:translationConfig({engine:'vm',cache:false}),serverSlots:[0,1,2],service:()=>({}),pacer:{reserve:async()=>{}},cacheKey:async b=>b.text(),prepare:async(b,i)=>({id:'P'+(i+1),page:i+1,width:100,height:100,image:'x',mime:'image/png',regions:[{id:'P'+(i+1)+'_B1',bbox:[10,10,50,50]}]}),google:async(pages,o)=>{sent.push({pages:pages.map(p=>p.page),key:o.key});await new Promise(r=>release.push(r));return {pages:pages.map(p=>({page:p.page,width:100,height:100,regions:[]}))};}});
 c.canvasTask=async()=>({cleanedImage:new ArrayBuffer(0),regions:[]});
 try{c.request(0,null);const jobs=[...c.jobs.values()];for(let n=0;n<100&&sent.length<3;n++)await tick();assert.equal(sent.length,3);c.focus(10);await tick();assert.equal(sent.length,3,'active packets are allowed to finish');release.splice(0).forEach(r=>r());for(let n=0;n<100&&sent.length<6;n++)await tick();assert.deepEqual(sent[3].pages,[11,12]);
 for(let n=0;n<100&&c.translatedPages.size<16;n++){release.splice(0).forEach(r=>r());await tick();}await Promise.all(jobs.map(j=>j.promise));
 const priority=sent.filter(p=>p.pages.some(n=>[11,12,13,14].includes(n)));assert.deepEqual(priority.map(p=>p.pages),[[11,12],[13,14]]);assert.equal(priority[0].key,priority[1].key);assert.equal(new Set(sent.flatMap(p=>p.pages)).size,16);assert.equal(sent.flatMap(p=>p.pages).length,16);
 const snapshot=c.snapshot();assert.equal(snapshot.jobs.length,16);assert.equal(snapshot.preparation.translated,16);assert.equal(snapshot.preparation.cleaned,16);assert.equal(snapshot.credentialMode,'server');
 }finally{release.splice(0).forEach(r=>r());c.close();}
});

import {setDirectKey,keySlotScope} from '../src/manga-direct-key.js';
test('personal mode rotates device credentials through Oracle without loading or using VM slots',async()=>{
 const scope='personal-isolation',values=['fixture-device-one','fixture-device-two','fixture-device-three'],bodies=[];
 values.forEach((key,i)=>setDirectKey(keySlotScope(scope,i),key));
 const service={request:async(path,o)=>{assert.equal(path,'/reader/google/generate');bodies.push(o.body);return{};}};
 const c=new DirectChapter({entries:Array.from({length:6},(_,i)=>({async:async()=>new Blob([String(i)])})),scope,keyScope:scope,config:translationConfig({engine:'direct',directViaOracle:true,cache:false}),service:()=>service,pacer:{reserve:async()=>{}},cacheKey:async b=>b.text(),prepare:async(b,i)=>({page:i+1,id:'P'+(i+1),width:100,height:100,regions:[{id:'P'+(i+1)+'_B1',bbox:[1,1,20,20]}]}),google:async(pages,o)=>{await o.transport({json:'{}',signal:o.signal});return{pages:pages.map(p=>({page:p.page,width:100,height:100,regions:[]}))};}});
 c.canvasTask=async()=>({cleanedImage:new ArrayBuffer(0),regions:[]});
 try{c.request(0,null);await Promise.all([...c.jobs.values()].map(j=>j.promise));assert.equal(bodies.length,3);assert.deepEqual(bodies.map(b=>b.key),values);assert.ok(bodies.every(b=>b.slot===undefined));assert.equal(c.snapshot().credentialMode,'personal');}finally{c.close();values.forEach((key,i)=>setDirectKey(keySlotScope(scope,i),''));}
});

test('background cleanup follows a changed focus after its active page finishes, even if translation is already cached',async()=>{
 let release;const gate=new Promise(r=>release=r),cleaned=[];const c=new DirectChapter({entries:Array.from({length:16},(_,i)=>({async:async()=>new Blob([String(i)])})),scope:'cleanup-focus',config:translationConfig({engine:'direct',cache:false}),cacheKey:async b=>b.text(),prepare:async(b,i)=>({page:i+1,width:100,height:100,regions:[{id:'P'+(i+1)+'_B1',bbox:[1,1,20,20]}]})});
 c.canvasTask=async m=>{const n=Number(m.page.regions[0].uid.match(/P(\d+)/)[1])-1;cleaned.push(n);if(n===0)await gate;return{regions:[],cleanedImage:new ArrayBuffer(0)};};
 try{c.preparation.start();for(let n=0;n<100&&!cleaned.length;n++)await tick();c.focus(10);release();for(let n=0;n<100&&cleaned.length<16;n++)await tick();assert.deepEqual(cleaned.slice(0,5),[0,10,11,12,13]);assert.equal(c.preparation.cleanDone.size,16);}finally{release();c.close();}
});

test('diagnostics preserve the original personal slot when only slot three is configured',()=>{
 const scope='sparse-slots';setDirectKey(keySlotScope(scope,2),'fixture-third');const c=new DirectChapter({entries:[],scope,keyScope:scope,config:translationConfig({engine:'direct'})});try{assert.equal(c.personalSlot('fixture-third'),2);}finally{c.close();setDirectKey(keySlotScope(scope,2),'');}
});

test('a cached foreground image still starts independent preparation and translation for the rest of the chapter',async()=>{
 const sent=[],c=new DirectChapter({entries:Array.from({length:4},(_,i)=>({async:async()=>new Blob([String(i)])})),scope:'render-cache-background',keyScope:'fixture',config:translationConfig({engine:'direct',cache:true}),getKey:()=> 'fixture-key',pacer:{reserve:async()=>{}},cacheKey:async b=>b.text(),readCache:async key=>key.includes(':render-v10:')?{renderedImage:new Uint8Array([1,2]).buffer}:null,writeCache:async()=>{},prepare:async(b,i)=>({page:i+1,id:'P'+(i+1),width:100,height:100,image:'fixture',mime:'image/png',regions:[{id:'P'+(i+1)+'_B1',bbox:[1,1,20,20]}]}),google:async pages=>{sent.push(pages.map(p=>p.page));return{pages:pages.map(p=>({page:p.page,width:100,height:100,regions:[]}))};},renderPage:async()=>{throw Error('Foreground must use the cached image');}});
 c.canvasTask=async()=>({cleanedImage:new ArrayBuffer(0),regions:[]});
 try{const result=await c.render(new Blob(['0']),0,'auto');assert.ok(result.cacheHit);await Promise.all([...c.jobs.values()].map(j=>j.promise));assert.deepEqual(sent,[[1,2],[3,4]]);assert.equal(c.snapshot().preparation.translated,4);}finally{c.close();}
});

test('background cleanup cannot replace an API failure or hide its retry state',()=>{
 const c=new DirectChapter({entries:[],scope:'status',config:translationConfig({engine:'direct'})});try{c.notify(0,{phase:'error',message:'Google HTTP 429'});c.notify(0,{phase:'cleaning',message:'Background ready'});assert.equal(c.progress.get(0).phase,'error');assert.equal(c.progress.get(0).message,'Google HTTP 429');assert.equal(c.progress.get(0).backgroundCleanup.message,'Background ready');}finally{c.close();}
});


function missingChapter({reviewFails=false,cached=false,nonText=false}={}){
 const sent=[],leases=[],writes=[];
 const initial=p=>({page:p.page,width:300,height:400,regions:[{uid:'P'+p.page+'_B1',text_bbox:[30,40,130,190],layout_bbox:[20,30,145,210],font_style:'standard_comic',ru_translation:p.page===1?'':'Уже переведено',...(nonText&&p.page===1?{empty_reason:'non_text'}:{})}]});
 const c=new DirectChapter({entries:[1,2].map(n=>({async:async()=>new Blob(['page'+n])})),scope:'missing-fixture',config:translationConfig({engine:'direct',cache:cached}),getKey:()=> 'personal-fixture',cacheKey:async b=>b.text(),pacer:{reserve:async key=>leases.push(key)},prepare:async(b,i)=>({id:'P'+(i+1),page:i+1,width:300,height:400,mime:'image/png',image:'original',regions:[{id:'P'+(i+1)+'_B1',bbox:[30,40,130,190],layout_bbox:[20,30,145,210]}]}),readCache:async id=>cached?{kind:'manga-json',page:initial({page:id.includes('page=0')?1:2})}:null,writeCache:async(...v)=>writes.push(v),google:async(pages,o)=>{
  sent.push({pages,options:o});
  if(o.reviewEmptyIds){if(reviewFails)throw Error('Google HTTP 429');return{pages:[{page:1,regions:[{uid:'P1_B1',text_bbox:[0,0,999,999],ru_translation:'Восстановленная реплика',font_style:'bold_scream',text_category:'dialogue'}]}]};}
  return{pages:pages.map(initial)};
 }});
 c.canvasTask=async message=>message.operation==='blocks-pack'?message.sheets.map(s=>({...s,image:'enlarged-crops',mime:'image/png'})):{regions:[],cleanedImage:new ArrayBuffer(0)};
 return{c,sent,leases,writes};
}

test('blank detected dialogue gets one paced crop-packet review with original coordinates preserved',async()=>{
 const {c,sent,leases}=missingChapter();
 try{c.request(0,null);const pages=await Promise.all([...c.jobs.values()].map(j=>j.promise));
  assert.equal(sent.length,2);assert.deepEqual(sent[0].pages.map(p=>p.page),[1,2]);
  assert.deepEqual(sent[1].options.reviewEmptyIds,['P1_B1']);assert.equal(sent[1].pages.length,1);
  assert.equal(sent[1].pages[0].placements[0].group.scale,2);assert.equal(leases.length,2);
  assert.equal(pages[0].regions[0].ru_translation,'Восстановленная реплика');
  assert.deepEqual(pages[0].regions[0].text_bbox,[30,40,130,190]);assert.deepEqual(pages[0].regions[0].layout_bbox,[20,30,145,210]);
  assert.equal(pages[1].regions[0].ru_translation,'Уже переведено');assert.equal(c.snapshot().preparation.translated,2);assert.equal(c.snapshot().preparation.partial,0);
 }finally{c.close();}
});

test('failed crop review retains successful translations and exposes a partial page without retry storms',async()=>{
 const {c,sent}=missingChapter({reviewFails:true});
 try{c.request(0,null);const pages=await Promise.all([...c.jobs.values()].map(j=>j.promise));
  assert.equal(sent.length,2);assert.equal(pages[1].regions[0].ru_translation,'Уже переведено');
  assert.deepEqual(pages[0].detectionReport.unresolved,['P1_B1']);assert.match(pages[0].emptyReview.error,/429/);
  const {needsEmptyReview}=await import('../src/manga-empty-review.js');assert.equal(needsEmptyReview(pages[0]),false);
  assert.equal(c.snapshot().preparation.translated,1);assert.equal(c.snapshot().preparation.partial,1);assert.equal(c.snapshot().jobs[0].state,'partial');
 }finally{c.close();}
});

test('old partial JSON is repaired from crops without resending already translated full pages',async()=>{
 const {c,sent,writes}=missingChapter({cached:true});
 try{c.request(0,null);const pages=await Promise.all([...c.jobs.values()].map(j=>j.promise));
  assert.equal(sent.length,1);assert.deepEqual(sent[0].options.reviewEmptyIds,['P1_B1']);
  assert.equal(pages[0].regions[0].ru_translation,'Восстановленная реплика');assert.equal(writes.length,2);
 }finally{c.close();}
});

test('confirmed non-text is not retried or counted as a missing translation',async()=>{
 const {c,sent}=missingChapter({nonText:true});
 try{c.request(0,null);await Promise.all([...c.jobs.values()].map(j=>j.promise));assert.equal(sent.length,1);assert.equal(c.snapshot().preparation.translated,2);assert.equal(c.snapshot().preparation.partial,0);}finally{c.close();}
});


test('one crop review restores both parts of a joined webtoon sentence without changing their layout',async()=>{
 const {reviewEmptyTranslations}=await import('../src/manga-empty-review.js');
 const sources=[{page:1,width:300,height:400,regions:[{id:'P1_B1',bbox:[100,360,180,400]}]},{page:2,width:300,height:400,regions:[{id:'P2_B1',bbox:[100,0,180,45]}]}],pages=sources.map(p=>({page:p.page,width:p.width,height:p.height,regions:p.regions.map(r=>({uid:r.id,text_bbox:r.bbox,layout_bbox:r.bbox,ru_translation:'',flow:{id:'P1_B1',width:80,height:85,offsetY:p.page===1?0:40}}))}));
 let calls=0;const c={direction:'ltr',config:{webtoon:true},controller:new AbortController(),canvasTask:async m=>{assert.equal(m.sheets.length,1);assert.equal(m.sheets[0].regions.length,1);return m.sheets;},callGoogle:async()=>{calls++;return{pages:[{page:1,regions:[{uid:'P1_B1',ru_translation:'Одна связанная реплика',font_style:'standard_comic'}]}]};}};
 await reviewEmptyTranslations(c,pages,sources,{});assert.equal(calls,1);
 assert.equal(pages[0].regions[0].ru_translation,pages[1].regions[0].ru_translation);assert.equal(pages[1].regions[0].flow.offsetY,40);assert.deepEqual(pages[1].regions[0].text_bbox,[100,0,180,45]);
});


test('old partial JSON stays readable without keys instead of failing its whole packet',async()=>{
 const {c,sent}=missingChapter({cached:true});c.getKey=()=>'';
 try{c.request(0,null);const pages=await Promise.all([...c.jobs.values()].map(j=>j.promise));assert.equal(sent.length,0);assert.equal(pages[1].regions[0].ru_translation,'Уже переведено');assert.match(pages[0].emptyReview.error,/Нет ключа/);assert.equal(pages[0].emptyReview.attempted,false);assert.equal(c.snapshot().preparation.partial,1);}finally{c.close();}
});
