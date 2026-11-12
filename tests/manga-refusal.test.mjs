// MOCKED API/contract tests: Google answers and the VM fallback are fixtures.
// Real OCR + Hy-MT2 inference is measured separately by
// scripts/benchmarks/refusal-fallback-vm.py (docs/manga-refusal-fallback.md).
import test from 'node:test';
import assert from 'node:assert/strict';
import {validateDirectResponse,callDirectGoogle,googleRefusal} from '../src/manga-direct-api.js';
import {DirectChapter} from '../src/manga-direct.js';
import {translationConfig} from '../src/manga-translation.js';
import {needsEmptyReview} from '../src/manga-empty-review.js';
import {SPLIT_BUDGET} from '../src/manga-refusal.js';
import {cropRegions} from '../src/manga-fallback.js';

const reply=rows=>({candidates:[{finishReason:'STOP',content:{parts:[{text:JSON.stringify(rows)}]}}]});
const blocked={promptFeedback:{blockReason:'PROHIBITED_CONTENT'},usageMetadata:{promptTokenCount:1900}};
const tick=()=>new Promise(r=>setTimeout(r,0));

// Canvas stand-ins for Node: record the crop rectangle, return a PNG-like blob.
const drawn=[];
globalThis.createImageBitmap??=async()=>({width:600,height:850,close(){}});
globalThis.OffscreenCanvas??=class{constructor(w,h){this.width=w;this.height=h;}getContext(){return {drawImage:(...a)=>drawn.push(a.slice(1,5))};}async convertToBlob(){return new Blob(['png']);}};

const page=(n,count)=>({id:'P'+n,page:n,width:600,height:850,mime:'image/png',image:'marked-page-'+n,detectionMs:2,regions:Array.from({length:count},(_,i)=>({id:'P'+n+'_B'+(i+1),bbox:[40+i*60,100,90+i*60,200],layout_bbox:[30+i*60,90,100+i*60,210]}))});

// Google refuses every full image of a "bad" page and any crop sheet that
// contains a "bad" bubble; everything else is translated.
function googleFixture({badPages=new Set(),badBubbles=new Set(),calls=[]}){
 return async(pages,options)=>{
  const mode=pages[0].inputMode||'annotated',ids=pages.flatMap(p=>p.regions.map(r=>r.id));
  calls.push({mode,ids,review:!!options.reviewEmptyIds?.length,key:options.key});
  const refused=mode==='blocks'?ids.some(id=>badBubbles.has(id)):pages.some(p=>badPages.has(p.page));
  if(refused)return {pages:validateDirectResponse(blocked,pages)};
  return {pages:validateDirectResponse(reply(ids.map(id=>({id,ru:'Гугл '+id}))),pages)};
 };
}
function chapter({count=[2,3],language='Japanese',google,service,config={}}){
 const pages=count.map((n,i)=>page(i+1,n));
 const c=new DirectChapter({entries:pages.map((_,i)=>({async:async()=>new Blob(['source-'+i])})),scope:'fixture',config:{...translationConfig({engine:'vm',language,cache:false}),...config},serverSlots:[0,1],service,pacer:{reserve:async()=>{}},cacheKey:async blob=>blob.text(),
  prepare:async(blob,i)=>structuredClone(pages[i]),google,renderPage:async(blob,p)=>({regions:p.regions,timings:{}})});
 c.canvasTask=async message=>{
  if(message.operation==='blocks-pack')return message.sheets.map(s=>({...s,image:'sheet',mime:'image/png'}));
  if(message.operation==='clean-prepare')return {cleanedImage:new Uint8Array([1]).buffer,regions:[]};
  throw Error('unexpected canvas task '+message.operation);
 };
 return c;
}
const run=async c=>{c.request(0,null);const jobs=[...c.jobs.values()];return Promise.all(jobs.map(j=>j.promise));};

test('a blocked prompt and a safety stop are refusals, not broken JSON',async()=>{
 const p=page(1,1);
 assert.deepEqual(googleRefusal(blocked),{blockReason:'PROHIBITED_CONTENT'});
 assert.throws(()=>validateDirectResponse(blocked,[p]),e=>e.name==='GoogleRefusal'&&e.refusal.blockReason==='PROHIBITED_CONTENT');
 for(const finishReason of ['SAFETY','PROHIBITED_CONTENT','BLOCKLIST','IMAGE_SAFETY'])assert.throws(()=>validateDirectResponse({candidates:[{finishReason,content:{parts:[]}}]},[p]),e=>e.refusal?.finishReason===finishReason);
 assert.equal(googleRefusal(reply([{id:'P1_B1',ru:'Привет'}])),null);
 assert.throws(()=>validateDirectResponse({candidates:[{finishReason:'STOP',content:{parts:[{text:'{'}]}}]},[p]),e=>!e.refusal&&/JSON/.test(e.message));
 // Through the Oracle gateway the refusal keeps its reason and a refused stage.
 const error=await callDirectGoogle([p],{key:'oracle-slot:0',gemmaProfile:'compat',transport:async()=>({status:200,text:JSON.stringify(blocked)})}).catch(e=>e);
 assert.equal(error.refusal.blockReason,'PROHIBITED_CONTENT');assert.equal(error.diagnostics.stage,'refused');
});

test('a refused packet is split on Google first; only the bubble still refused goes to the VM model',async()=>{
 const calls=[],fallback=[];let keysDuringFallback;
 const c=chapter({google:googleFixture({badPages:new Set([2]),badBubbles:new Set(['P2_B2']),calls}),service:()=>({request:async(path,options)=>{
  assert.equal(path,'/reader/lmt/fallback');keysDuringFallback=c.keyBusy.size;fallback.push(options.body);
  return {model:'Hy-MT2-1.8B-Q8_0',ocr:'manga-ocr',rows:options.body.crops.map(x=>({id:x.id,source:'やめて…',ru:'Перестань…',status:'translated'}))};
 }})});
 try{
  const [first,second]=await run(c);
  assert.deepEqual(first.regions.map(r=>r.ru_translation),['Гугл P1_B1','Гугл P1_B2']);
  assert.deepEqual(second.regions.map(r=>r.ru_translation),['Гугл P2_B1','Перестань…','Гугл P2_B3']);
  const bubble=second.regions[1];
  assert.equal(bubble.fallback.status,'translated');assert.equal(bubble.fallback.reason,'refused');assert.equal(bubble.fallback.model,'Hy-MT2-1.8B-Q8_0');assert.equal(bubble.empty_reason,undefined);
  assert.deepEqual(bubble.text_bbox,[100,100,150,200]);assert.deepEqual(bubble.layout_bbox,[90,90,160,210]);
  assert.deepEqual(second.detectionReport.refused,['P2_B2']);assert.deepEqual(second.detectionReport.fallback,['P2_B2']);assert.deepEqual(second.detectionReport.unresolved,[]);
  // Split order: packet → each page → page-2 crops (right-to-left reading
  // order) → halves → single bubble.
  assert.deepEqual(calls.map(x=>x.mode+':'+x.ids.join(',')),['annotated:P1_B1,P1_B2,P2_B1,P2_B2,P2_B3','annotated:P1_B1,P1_B2','annotated:P2_B1,P2_B2,P2_B3','blocks:P2_B3,P2_B2,P2_B1','blocks:P2_B3,P2_B2','blocks:P2_B3','blocks:P2_B2','blocks:P2_B1']);
  assert.ok(!calls.some(x=>x.review),'a refused bubble is not re-sent by the blank review');
  // Only the refused crop and the source language reach the VM; the key was free.
  assert.equal(fallback.length,1);assert.equal(fallback[0].language,'Japanese');assert.deepEqual(fallback[0].crops.map(x=>x.id),['P2_B2']);assert.equal(keysDuringFallback,0);
  assert.equal(c.partialPages.size,0);const q=c.snapshot().preparation;assert.equal(q.partial,0);assert.deepEqual(q.fallback,{pending:0,pages:1,regions:1});
  assert.equal(c.snapshot().jobs[1].fallback,1);
 }finally{c.close();}
});

test('crop requests send native text boxes with padding, clamped to the page',async()=>{
 drawn.length=0;
 const crops=await cropRegions(new Blob(['x']),[{uid:'A',text_bbox:[2,3,50,60]},{uid:'B',text_bbox:[580,800,600,850]}]);
 assert.deepEqual(crops.map(c=>c.id),['A','B']);assert.ok(crops.every(c=>typeof c.image==='string'&&c.image.length));
 assert.deepEqual(drawn,[[0,0,56,66],[574,794,26,56]]);
});

test('splitting stops at its budget; every refused bubble is still translated',async()=>{
 const calls=[],bad=new Set(Array.from({length:8},(_,i)=>'P1_B'+(i+1)));let crops=[];
 const c=chapter({count:[8],google:googleFixture({badPages:new Set([1]),badBubbles:bad,calls}),service:()=>({request:async(path,{body})=>{crops=body.crops.map(x=>x.id);return {model:'Hy-MT2',ocr:'manga-ocr',rows:body.crops.map(x=>({id:x.id,source:'x',ru:'Запасной '+x.id,status:'translated'}))};}})});
 try{
  const [only]=await run(c);
  assert.ok(calls.length<=1+SPLIT_BUDGET,'Google calls: '+calls.length);
  assert.equal(crops.length,8);assert.ok(only.regions.every(r=>r.ru_translation.startsWith('Запасной ')));assert.equal(c.partialPages.size,0);
 }finally{c.close();}
});

test('the VM model also reads non-text and reports per-bubble errors; a failed VM call is retried at chapter end',async()=>{
 let attempt=0;
 const c=chapter({count:[3],language:'Korean',google:googleFixture({badPages:new Set([1]),badBubbles:new Set(['P1_B1','P1_B2','P1_B3'])}),service:()=>({request:async(path,{body})=>{
  attempt++;if(attempt===1)throw Object.assign(Error('Запасная модель ещё не настроена на ВМ.'),{status:422});
  return {model:'Hy-MT2',ocr:'ppocrv5-korean',rows:[{id:'P1_B1',source:'그만해',ru:'Хватит',status:'translated'},{id:'P1_B2',source:'',ru:'',status:'non_text',gate:'not-korean'},{id:'P1_B3',source:'...',ru:'',status:'error',error:'Модель вернула реплику без перевода.'}].filter(r=>body.crops.some(x=>x.id===r.id))};
 }})});
 try{
  const [first]=await run(c);
  assert.equal(first.detectionReport.fallbackError,'Запасная модель ещё не настроена на ВМ.');assert.equal(c.partialPages.size,1);
  await c.recoverChapter();
  const record=c.recovered.get(0);
  assert.equal(record.regions[0].ru_translation,'Хватит');assert.equal(record.regions[1].empty_reason,'non_text');assert.equal(record.regions[2].fallback.status,'error');
  assert.deepEqual(record.detectionReport.unresolved,['P1_B3']);assert.deepEqual(record.detectionReport.fallback,['P1_B1']);
 }finally{c.close();}
});

test('fallback runs only for Japanese, Korean and English sources',async()=>{
 let called=false;
 const c=chapter({count:[1],language:'Chinese (Simplified)',google:googleFixture({badPages:new Set([1]),badBubbles:new Set(['P1_B1'])}),service:()=>({request:async()=>{called=true;return {rows:[]};}})});
 try{const [only]=await run(c);assert.equal(called,false);assert.equal(only.regions[0].empty_reason,'refused');assert.equal(c.partialPages.size,1);}finally{c.close();}
});

test('refused bubbles are not blank-review candidates; ordinary blanks still are',()=>{
 const refused={regions:[{uid:'A',ru_translation:'',empty_reason:'refused',refused:{blockReason:'PROHIBITED_CONTENT'}}]};
 const blank={regions:[{uid:'B',ru_translation:'',empty_reason:'unconfirmed'}]};
 assert.equal(needsEmptyReview(refused),false);assert.equal(needsEmptyReview(blank),true);
});

test('VM export (legacy queue) splits a refused packet and fills the gap through the same fallback route',async()=>{
 const paths=[];
 const c=chapter({count:[2,2],language:'English',config:{chapterPipeline:false},google:googleFixture({badPages:new Set([1]),badBubbles:new Set(['P1_B2'])}),service:()=>({request:async(path,{body})=>{paths.push(path);return {model:'Hy-MT2',ocr:'paddle',rows:body.crops.map(x=>({id:x.id,source:'Take it off.',ru:'Сними это.',status:'translated'}))};}})});
 try{
  c.request(0,null);c.request(1,null,true);const jobs=[...c.jobs.values()];const pages=await Promise.all(jobs.map(j=>j.promise));
  assert.deepEqual(paths,['/reader/lmt/fallback']);
  assert.deepEqual(pages[0].regions.map(r=>r.ru_translation),['Гугл P1_B1','Сними это.']);
  assert.deepEqual(pages[1].regions.map(r=>r.ru_translation),['Гугл P2_B1','Гугл P2_B2']);
  for(let n=0;n<5;n++)await tick();assert.equal(c.partialPages.size,0);
 }finally{c.close();}
});
