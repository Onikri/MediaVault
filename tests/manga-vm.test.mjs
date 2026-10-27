import test from 'node:test';import assert from 'node:assert/strict';
import {parseSse,chapterFingerprint,VmChapter} from '../src/manga-vm.js';
import {fitComicText} from '../src/manga-typeset.js';
import {translationConfig,migrateTranslationSettings,resultConfig} from '../src/manga-translation.js';
test('UTF-8 SSE handles every byte boundary and multiple data lines',async()=>{const bytes=new TextEncoder().encode('event: page_translated\r\ndata: {"ru":\r\ndata: "Привет"}\r\n\r\nevent: complete\ndata: {}\n\n'),response=new Response(new ReadableStream({start(c){for(const b of bytes)c.enqueue(Uint8Array.of(b));c.close();}})),events=[];await parseSse(response,(type,value)=>events.push([type,value]),new AbortController().signal);assert.deepEqual(events,[['page_translated',{ru:'Привет'}],['complete',{}]]);});
test('manifest binds encrypted chunk IDs, nonces and numeric reader order',async()=>{const item={id:'a',size:42,chunks:[{fileId:'f',iv:'n'}]},names=['2.png','10.png'];const hash=await chapterFingerprint(item,names);assert.equal(hash.length,64);assert.notEqual(hash,await chapterFingerprint(item,[...names].reverse()));assert.notEqual(hash,await chapterFingerprint({...item,chunks:[{fileId:'f',iv:'changed'}]},names));});
test('fitting respects available area and refuses overflow without erasing original',()=>{const measure=(text,size)=>[...text].length*size*.48,box=[0,0,200,160],fit=fitComicText('Привет, друг! Как твои дела?',box,measure);assert.ok(fit.fits);assert.ok(fit.fontSize>=10&&fit.fontSize<=42);assert.ok(fit.blockH<=128);assert.ok(fit.lines.every(l=>measure(l,fit.fontSize)<=160));assert.equal(fitComicText('Несокращаемоеслово'.repeat(30),[0,0,30,20],measure).fits,false);});
test('fully local cannot retain a text/vision server mode and VM caches use policy',()=>{assert.equal(translationConfig({engine:'lmt',mode:'api'}).mode,'gpu');assert.equal(translationConfig().engine,'vm');assert.equal(migrateTranslationSettings({version:6,engine:'backend'}).engine,'vm');assert.equal(migrateTranslationSettings({version:7,engine:'backend'}).engine,'backend');const a=resultConfig({engine:'vm',vmPolicy:'a',apiKey:'secret'}),b=resultConfig({engine:'vm',vmPolicy:'b'});assert.notDeepEqual(a,b);assert.equal(a.apiKey,undefined);assert.equal(a.ocr,undefined);});

test('a failed chapter open can retry after the server key is configured',async()=>{const item={id:'a',size:42,chunks:[{fileId:'f',iv:'n'}]},names=['1.png'],manifest=await chapterFingerprint(item,names);let calls=0;const service={request:async()=>({}),openReaderChapter:async()=>{calls++;if(calls===1)throw Object.assign(Error('API key missing'),{status:409});return{id:'new',manifest,policy:'p'};}};const chapter=new VmChapter({item,names,direction:'rtl',scope:'owner',service:()=>service,policy:'p'});await assert.rejects(chapter.open(),/API key/);await chapter.open();assert.equal(calls,2);assert.equal(chapter.id,'new');chapter.close();});

import {normalizeTranslationProgress,translationProgressDetails} from '../src/translation-progress.js';
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const wire=(type,value)=>new TextEncoder().encode('event: '+type+'\ndata: '+JSON.stringify(value)+'\n\n');
async function liveChapter(){
 const item={id:'progress',size:42,chunks:[{fileId:'f',iv:'n'}]},names=['1.png','2.png'],manifest=await chapterFingerprint(item,names),controllers=[];
 const service={openReaderChapter:async()=>({id:'session',manifest,policy:'p'}),request:async(path,options)=>options?.raw?new Response(new ReadableStream({start(c){controllers.push(c);}})):({})};
 const chapter=new VmChapter({item,names,direction:'rtl',scope:'owner',cache:false,service:()=>service,policy:'p'});
 return{chapter,controllers,manifest};
}
test('live legacy status and per-page progress arrive before translation; retry ignores an older stream error',async()=>{
 const{chapter,controllers,manifest}=await liveChapter(),seen1=[],seen2=[];
 try{
  const first=chapter.json(1,value=>seen1.push(value));const firstError=assert.rejects(first,/temporary/);
  const second=chapter.json(2,value=>seen2.push(value));await tick();await tick();assert.equal(controllers.length,1);
  controllers[0].enqueue(wire('status',{message:'Google is processing'}));await tick();assert.equal(seen1.at(-1).message,'Google is processing');
  controllers[0].enqueue(wire('progress',{page:2,phase:'google',message:'Background page',totalRegions:10,completedRegions:3}));await tick();assert.equal(seen2.at(-1).message,'Background page');assert.notEqual(seen1.at(-1).message,'Background page');
  controllers[0].enqueue(wire('page_error',{page:1,message:'temporary'}));await firstError;
  const retry=chapter.json(1,value=>seen1.push(value));await tick();await tick();assert.equal(controllers.length,2);
  controllers[0].enqueue(wire('page_error',{page:1,message:'old failure must not reject retry'}));await tick();
  const result={page:1,manifest,policy:'p',regions:[]};controllers[1].enqueue(wire('page_translated',result));assert.deepEqual(await retry,result);
  controllers[0].enqueue(wire('page_translated',{...result,page:2}));assert.equal((await second).page,2);
  controllers.forEach(c=>c.close());
 }finally{chapter.close();}
});
test('an idle SSE connection cancels its reader and returns a visible retryable error',async()=>{
 let cancelled=false;const response=new Response(new ReadableStream({cancel(){cancelled=true;}}));
 await assert.rejects(parseSse(response,()=>{},new AbortController().signal,{idleTimeoutMs:10,initialTimeoutMs:10}),error=>error.name==='StreamIdleError');assert.equal(cancelled,true);
});
test('leaving a page removes its live listener without cancelling a shared server job',async()=>{
 const{chapter,controllers,manifest}=await liveChapter(),abort=new AbortController(),seen=[];
 try{
  const pending=chapter.json(1,value=>seen.push(value),abort.signal);const rejected=assert.rejects(pending,error=>error.name==='AbortError');await tick();await tick();abort.abort();await rejected;const count=seen.length;
  const again=chapter.json(1,()=>{});await tick();assert.equal(controllers.length,1);
  controllers[0].enqueue(wire('progress',{page:1,message:'still working'}));await tick();assert.equal(seen.length,count);
  controllers[0].enqueue(wire('page_translated',{page:1,manifest,policy:'p',regions:[]}));assert.equal((await again).page,1);controllers[0].close();
 }finally{chapter.close();}
});
test('progress uses observed region counts and elapsed time, with clock-skew-safe retry countdowns',()=>{
 assert.equal(normalizeTranslationProgress({message:'Wait',serverTimeMs:1000,retryAtMs:11000,clientReceivedAt:50000}).retryAtMs,60000);
 const before=Date.now(),p=normalizeTranslationProgress({message:'Wait',serverTimeMs:1000,retryAtMs:11000});assert.ok(p.retryAtMs>=before+10000&&p.retryAtMs<=Date.now()+10000);
 const details=translationProgressDetails({page:3,model:'gemma-4-31b-it',running:true,startedAt:1000,retryAtMs:8000,completedRegions:3,totalRegions:15,attempt:2},6000);
 assert.ok(details.includes('Прошло 5 с'));assert.ok(details.includes('Повтор через 2 с'));assert.ok(details.includes('Обработано 3 / 15'));assert.ok(details.includes('Запрос 2'));
});
