import test from 'node:test';
import assert from 'node:assert/strict';
import {directRequest,validateDirectResponse,callDirectGoogle} from '../src/manga-direct-api.js';
import {DirectChapter} from '../src/manga-direct.js';
import {translationConfig,resultConfig} from '../src/manga-translation.js';
import {directKey,setDirectKey,keySlotScope} from '../src/manga-direct-key.js';
import {englishTextBoxes} from '../src/manga-fast-detect.js';
import {compareDirectInputs} from '../src/manga-direct-comparison.js';
import {geometryAgreement} from '../src/manga-vision-geometry.js';
const page=n=>({id:'P'+n,page:n,width:600,height:850,mime:'image/webp',image:'fixture',detectionMs:3,regions:[{id:'P'+n+'_B1',bbox:[100,100,300,250]}]});
const reply=rows=>({candidates:[{finishReason:'STOP',content:{parts:[{text:JSON.stringify(rows)}]}}]});

test('three personal credentials lease three concurrent pages without exporting secrets',async()=>{
 const scope='parallel-fixture';for(let i=0;i<3;i++)setDirectKey(keySlotScope(scope,i),'fixture-key-'+i);
 let release;const held=new Promise(resolve=>release=resolve),seen=[];const {c}=chapter({keyScope:scope,getKey:directKey,google:async(pages,options)=>{seen.push(options.key);if(seen.length===3)release();await held;return {pages:validateDirectResponse(reply(pages.map(p=>({id:p.regions[0].id,ru:'Привет!'}))),pages)};}});
 try{await Promise.all([0,1,2].map(index=>c.render(new Blob(['page-'+index]),index,'auto',null,{},new AbortController().signal)));assert.equal(new Set(seen).size,3);assert.equal(c.keyBusy.size,0);}finally{c.close();for(let i=0;i<3;i++)setDirectKey(keySlotScope(scope,i),'');}
});

test('personal mode sends its page to the fixed Oracle gateway',async()=>{
 let sent;const {c}=chapter({entries:[{async:async()=>new Blob(['last page'])}],config:translationConfig({engine:'direct',directViaOracle:true,directBatchPages:2}),google:callDirectGoogle,service:()=>({request:async(path,options)=>{sent={path,options};return reply([{id:'P1_B1',ru:'Привет!'}]);}})});
 try{await c.render(new Blob(['page']),0,'auto',null,{},new AbortController().signal);assert.equal(sent.path,'/reader/google/generate');assert.equal(sent.options.body.model,'gemini-3.5-flash-lite');assert.ok(sent.options.body.key);assert.ok(!JSON.stringify(sent.options.body.request).includes(sent.options.body.key));}finally{c.close();}
});

test('online reader uses an Oracle credential slot without receiving the server key',async()=>{
 const sent=[];const {c}=chapter({entries:[{async:async()=>new Blob(['last page'])}],config:translationConfig({engine:'vm',directViaOracle:true,directBatchPages:2}),serverSlots:[0],getKey:()=>'',google:callDirectGoogle,service:()=>({request:async(path,options)=>{sent.push({path,body:options.body});return reply([{id:'P1_B1',ru:'Привет!'}]);}})});
 try{await c.render(new Blob(['page']),0,'auto',null,{},new AbortController().signal);assert.equal(sent[0].path,'/reader/google/generate');assert.equal(sent[0].body.slot,0);assert.equal(sent[0].body.key,undefined);assert.equal(sent[0].body.model,'gemini-3.5-flash-lite');}finally{c.close();}
});
test('direct mode is a separate compact cache variant without personal secrets',()=>{
 const c=translationConfig({engine:'direct',apiKey:'private-fixture'});assert.equal(c.engine,'direct');assert.equal(c.directModel,'gemini-3.5-flash-lite');assert.equal(c.inpaint,'hybrid');assert.equal(c.font,'auto');
 const variant=resultConfig(c);assert.equal(variant.direction,'rtl');assert.ok(!JSON.stringify(variant).includes('private-fixture'));assert.notDeepEqual(variant,resultConfig({...c,engine:'vm'}));assert.notDeepEqual(variant,resultConfig({...c,directModel:'gemma-4-31b-it'}));
});
test('one compact single-image request, RTL context, no OCR transcription or expensive schema',()=>{
 const r=directRequest([page(1)],{context:'Старое имя'});assert.equal(r.contents[0].parts.filter(p=>p.inlineData).length,1);assert.match(r.contents[0].parts[0].text,/RIGHT TO LEFT/);assert.match(r.contents[0].parts[0].text,/Старое имя/);assert.equal(r.generationConfig.thinkingConfig.thinkingLevel,'MINIMAL');assert.equal(r.generationConfig.responseSchema,undefined);
 assert.equal(directRequest([page(1),page(2),page(3)]).contents[0].parts.filter(p=>p.inlineData).length,3);assert.throws(()=>directRequest([page(1),page(2),page(3),page(4)]),/трёх/);assert.throws(()=>directRequest([page(1)],{model:'unapproved-model'}),/модель/);
});
test('strict UID and Russian validation preserve exact local geometry and font styles',()=>{
 const rows=[{id:'P2_B1',ru:'Не открывай!',f:1,k:0},{id:'P1_B1',ru:'Привет, друг!',f:2,k:1}],out=validateDirectResponse(reply(rows),[page(1),page(2)]);
 assert.equal(out[0].regions[0].ru_translation,'Привет, друг!');assert.equal(out[1].regions[0].font_style,'bold_scream');assert.deepEqual(out[0].regions[0].text_bbox,[100,100,300,250]);
 assert.throws(()=>validateDirectResponse(reply(rows.slice(0,1)),[page(1),page(2)]),/пропустил/);
 assert.throws(()=>validateDirectResponse(reply([rows[0],rows[0]]),[page(1),page(2)]),/разметкой/);
 assert.throws(()=>validateDirectResponse(reply([{id:'P1_B1',ru:'HELLO'}]),[page(1)]),/непереведённая/);
 assert.equal(validateDirectResponse(reply([{id:'P1_B1',ru:'…?!'}]),[page(1)])[0].regions[0].ru_translation,'…?!');
 assert.throws(()=>validateDirectResponse({candidates:[{finishReason:'MAX_TOKENS'}]},[page(1)]),/обрезан/);
});
test('personal key travels only in Google header, quota errors do not retry or leak response',async()=>{
 const calls=[];const fetcher=async(url,request)=>{calls.push({url,request});return{ok:false,status:429,text:async()=>JSON.stringify({error:{message:'private-fixture'}})};};
 await assert.rejects(callDirectGoogle([page(1)],{key:'private-fixture',fetcher,gemmaProfile:'compat'}),e=>/Лимит/.test(e.message)&&!e.message.includes('private-fixture'));
 assert.equal(calls.length,1);assert.match(calls[0].url,/generativelanguage.googleapis.com\/v1beta\/models\/gemini-3.5-flash-lite:generateContent$/);assert.equal(calls[0].request.headers['x-goog-api-key'],'private-fixture');assert.ok(!calls[0].request.body.includes('private-fixture'));assert.equal(calls[0].request.credentials,'omit');
});
test('Google call has a bounded deadline and reports timeout without background retries',async()=>{
 const keepAlive=setTimeout(()=>{},80);
 try{await assert.rejects(callDirectGoogle([page(1)],{key:'fixture',gemmaProfile:'compat',timeoutMs:10,fetcher:async(_,r)=>new Promise((resolve,reject)=>r.signal.addEventListener('abort',()=>reject(r.signal.reason),{once:true}))}),/0\.01 с/);}finally{clearTimeout(keepAlive);}
});
function chapter(extra={}){
 const calls=[],cache=new Map();
 const c=new DirectChapter({entries:Array.from({length:8},()=>({async:async()=>new Blob(['fixture'])})),scope:'profile:library',keyScope:'profile',config:{...translationConfig({engine:'direct'}),directBatchPages:1,chapterPipeline:false},prepare:async(blob,i)=>page(i+1),google:async(pages)=>{calls.push(pages.map(p=>p.page));return {pages:validateDirectResponse(reply(pages.map(p=>({id:p.regions[0].id,ru:'Привет, друг!',f:0,k:0}))),pages)};},cacheKey:async(blob,c,scope)=>scope+':'+await blob.text(),readCache:async()=>null,writeCache:async(id,scope,value)=>cache.set(id,value),renderPage:async(blob,p)=>({regions:p.regions,timings:p.timings}),getKey:()=> 'fixture-personal',pacer:{reserve:async()=>{}},...extra});return {c,calls,cache};
}
test('debug capture reuses translated JSON, reports real detector geometry and never exposes a credential',async()=>{
 const{c,calls}=chapter();const signal=new AbortController().signal;
 try{
  await c.render(new Blob(['same-page']),0,'auto',null,{},signal);
  const debug=await c.render(new Blob(['same-page']),0,'auto',null,{captureDebug:true},signal);
  assert.equal(calls.length,1);assert.deepEqual(debug.detected.regions[0].bbox,[100,100,300,250]);
  assert.ok(!JSON.stringify(c.snapshot()).includes('fixture-personal'));
 }finally{c.close();}
});
test('each page has its own request and repeated reading avoids another Google call',async()=>{
 const {c,calls,cache}=chapter(),s=new AbortController().signal,status=[];
 const a=await c.render(new Blob(['first']),0,'auto',x=>status.push(x),{},s);
 const b=await c.render(new Blob(['second']),1,'auto',null,{},s);
 await c.render(new Blob(['first']),0,'auto',null,{},s);assert.deepEqual(calls,[[1],[2]]);assert.equal(a.regions.length,1);assert.equal(b.regions.length,1);assert.equal(cache.size,2);assert.ok(status.some(p=>p.phase==='translating'));assert.ok(status.some(p=>p.phase==='cleaning'));c.invalidate(0);await c.render(new Blob(['first']),0,'auto',null,{},s);assert.deepEqual(calls,[[1],[2],[1]]);c.close();
});
test('slow adjacent source does not delay current page; explicit single-page mode stays single',async()=>{
 const {c,calls}=chapter({entries:[{async:async()=>new Blob(['first'])},{async:()=>new Promise(()=>{})}]});
 await c.render(new Blob(['first']),0,'auto',null,{},new AbortController().signal);assert.deepEqual(calls,[[1]]);c.close();
 const b=chapter({config:{...translationConfig({engine:'direct'}),directBatchPages:1,chapterPipeline:false}});await b.c.render(new Blob(['first']),0,'auto',null,{},new AbortController().signal);assert.deepEqual(b.calls,[[1]]);b.c.close();
});
test('cache is reusable before asking for a key; bad model result can be manually retried',async()=>{
 const hit={kind:'manga-json',page:{...page(1),regions:[]}};const {c,calls}=chapter({getKey:()=>'',readCache:async()=>hit});await c.render(new Blob(['first']),0,'auto',null,{},new AbortController().signal);assert.equal(calls.length,0);c.close();
 let n=0;const other=chapter({google:async pages=>{if(!n++)throw Error('Google unavailable');return {pages:pages.map(p=>({...p,regions:[]}))};}});
 await assert.rejects(other.c.render(new Blob(['first']),0,'auto',null,{},new AbortController().signal),/unavailable/);
 await other.c.render(new Blob(['first']),0,'auto',null,{},new AbortController().signal);assert.equal(n,2);other.c.close();
});
test('retrying a failed renderer reuses translated JSON and does not call Google again',async()=>{
 let renders=0;const {c,calls}=chapter({renderPage:async(blob,page)=>{if(!renders++)throw Error('renderer fixture');return {regions:page.regions,timings:{}};}}),signal=new AbortController().signal;
 await assert.rejects(c.render(new Blob(['first']),0,'auto',null,{},signal),error=>error.stage==='render');await c.render(new Blob(['first']),0,'auto',null,{},signal);assert.equal(calls.length,1);c.close();
});
test('personal keys are separated by user and never stored in localStorage',()=>{
 setDirectKey('one','fixture-one');setDirectKey('two','fixture-two');assert.equal(directKey('one'),'fixture-one');assert.equal(directKey('two'),'fixture-two');setDirectKey('one','');assert.equal(directKey('one'),'');assert.throws(()=>setDirectKey('x','bad\nkey'),/Проверь/);setDirectKey('two','');
});
test('weight-free English detection joins letters and lines while keeping neighbouring bubbles separate',()=>{
 const width=600,height=500,data=new Uint8ClampedArray(width*height*4).fill(255);
 assert.deepEqual(englishTextBoxes({width,height,data}),[]);
 for(const [x0,y0]of[[50,70],[320,70],[50,100],[320,100]])for(let g=0;g<8;g++)for(let y=y0;y<y0+18;y++)for(let x=x0+g*15;x<x0+g*15+8;x++){const n=(y*width+x)*4;data[n]=data[n+1]=data[n+2]=0;}
 assert.deepEqual(englishTextBoxes({width,height,data}),[{x1:47,y1:67,x2:166,y2:121},{x1:317,y1:67,x2:436,y2:121}]);
});
test('three Google input contracts separate labels, pixel coordinates and self detection',()=>{
 const marked=page(10),coordinate={...marked,inputMode:'coordinates'},raw={...marked,inputMode:'vision',regions:[]};
 const a=directRequest([marked]),b=directRequest([coordinate]),c=directRequest([raw]);
 assert.match(a.contents[0].parts[1].text,/P10_B1/);assert.ok(!a.contents[0].parts[1].text.includes('originalWidth'));
 assert.deepEqual(JSON.parse(b.contents[0].parts[1].text).regions[0],{id:'P10_B1',box:[100,100,300,250]});
 assert.match(c.contents[0].parts[0].text,/Y FIRST/);assert.match(c.contents[0].parts[0].text,/RIGHT TO LEFT/);assert.ok(!JSON.stringify(c).includes('P10_B1'));assert.equal(c.generationConfig.maxOutputTokens,8192);
 const variants=['annotated','coordinates','vision'].map(directInput=>JSON.stringify(resultConfig({engine:'direct',directInput})));assert.equal(new Set(variants).size,3);
 assert.notDeepEqual(resultConfig({engine:'direct',directDetector:'ctd'}),resultConfig({engine:'direct',directDetector:'rtdetr'}));
});
test('raw reading sends the real source language and avoids the EN-only detector for CJK',()=>{
 for(const language of ['Japanese','Korean']){
  const c=translationConfig({engine:'direct',language,directDetector:'en-fast'});assert.equal(c.directDetector,'rtdetr');
  const body=directRequest([{...page(1),inputMode:'vision',regions:[]}],{language});assert.match(body.contents[0].parts[0].text,new RegExp('readable '+language+' text'));
 }
 assert.throws(()=>directRequest([page(1)],{language:'untrusted prompt'}),/исходный язык/);
});
test('Google self detection maps Y-first normalized coordinates to ORIGINAL pixels, preserving layout',()=>{
 const p={...page(10),width:800,height:1600,sentWidth:640,sentHeight:1280,inputMode:'vision',regions:[]};
 const result=validateDirectResponse(reply([{box:[100,200,200,400],layout:[90,190,220,420],ru:'Не открывай дверь!',f:1,k:0}]),[p])[0];
 assert.deepEqual(result.regions[0].text_bbox,[160,160,320,320]);assert.deepEqual(result.regions[0].layout_bbox,[152,144,336,352]);assert.equal(result.regions[0].uid,'P10_B1');assert.equal(result.regions[0].font_style,'bold_scream');
 assert.deepEqual(validateDirectResponse(reply([]),[p])[0].regions,[]);
});
test('unsafe Google geometry fails closed before any eraser receives it',()=>{
 const p={...page(1),inputMode:'vision',regions:[]},valid={box:[100,100,200,300],ru:'Стой!'};
 for(const box of [[-1,100,200,300],[100,100,100,300],[0,0,1000,1000],[100,100,101,101],['100',100,200,300]])assert.throws(()=>validateDirectResponse(reply([{...valid,box}]),[p]));
 assert.throws(()=>validateDirectResponse(reply([valid,valid]),[p]),/продублировал/);
 assert.throws(()=>validateDirectResponse(reply([{...valid,layout:[150,100,200,300]}]),[p]),/не вмещает/);
 assert.throws(()=>validateDirectResponse(reply([{...valid,ru:'English'}]),[p]),/непереведённая/);
 assert.equal(geometryAgreement([[0,0,10,10]],[[0,0,10,10],[50,50,60,60]]).matched,1);
});
test('vision pages with zero local regions still reach Google and can be rendered',async()=>{
 let prepares=0;const {c,calls}=chapter({entries:[{async:async()=>new Blob(['last page'])}],config:translationConfig({engine:'direct',directInput:'vision',directBatchPages:2}),prepare:async()=>{prepares++;return {...page(1),inputMode:'vision',regions:[]};},google:async pages=>{calls.push(pages);return {pages:validateDirectResponse(reply([{box:[100,100,200,300],ru:'Привет!'}]),pages)};}});
 const result=await c.render(new Blob(['image']),0,'auto',null,{},new AbortController().signal);assert.equal(prepares,1);assert.equal(calls.length,1);assert.equal(result.regions[0].ru_translation,'Привет!');c.close();
});
test('comparison shares source and local geometry, makes three explicit requests without touching reader cache',async()=>{
 const seen=[],base=page(1);const result=await compareDirectInputs({blob:new Blob(['image']),index:0,key:'fixture',config:{...translationConfig({engine:'direct'}),directBatchPages:1,chapterPipeline:false},prepare:async(blob,i,status,inputMode)=>({...base,inputMode,detector:inputMode==='vision'?'google':'en-fast',regions:inputMode==='vision'?[]:base.regions,image:inputMode==='vision'?'raw-image':'marked-image'}),google:async(pages,options)=>{seen.push({pages,context:options.context});return {pages:validateDirectResponse(reply(pages[0].inputMode==='vision'?[{box:[100,100,200,300],ru:'Привет!'}]:[{id:'P1_B1',ru:'Привет!'}]),pages),diagnostics:{requestBytes:1000,metrics:{uploadMs:1}},usage:{promptTokenCount:400}};}});
 assert.deepEqual(seen.map(r=>r.pages[0].inputMode),['annotated','coordinates','vision']);assert.deepEqual(seen[0].pages[0].regions,seen[1].pages[0].regions);assert.equal(seen[1].pages[0].image,seen[2].pages[0].image);assert.ok(seen.every(r=>r.context===''));assert.equal(result.results.length,3);assert.ok(result.results.every(r=>r.state==='done'));assert.ok(!JSON.stringify(result).includes('fixture'));assert.ok(!JSON.stringify(result).includes('raw-image'));
});


test('three Oracle slots process nine pages as three concurrent packs, keeping every UID',async()=>{
 let release;const barrier=new Promise(resolve=>release=resolve),seen=[];
 const {c}=chapter({entries:Array.from({length:9},()=>({async:async()=>new Blob(['fixture'])})),pacer:{reserve:async()=>{}},config:translationConfig({engine:'direct',directBatchPages:3}),serverSlots:[0,1,2],service:()=>({}),google:async(pages,options)=>{seen.push({pages:pages.map(p=>p.page),key:options.key});if(seen.length===3)release();await barrier;return {pages:validateDirectResponse(reply(pages.flatMap(p=>p.regions.map(r=>({id:r.id,ru:'Страница '+p.page})))),pages)};}});
 try{const jobs=Array.from({length:9},(_,i)=>c.request(i,null,i!==0));const result=await Promise.all(jobs.map(j=>j.promise));assert.deepEqual(seen.map(s=>s.pages).sort((a,b)=>a[0]-b[0]),[[1,2,3],[4,5,6],[7,8,9]]);assert.equal(new Set(seen.map(s=>s.key)).size,3);assert.deepEqual(result.map(p=>p.regions[0].uid),Array.from({length:9},(_,i)=>'P'+(i+1)+'_B1'));assert.equal(c.keyBusy.size,0);}finally{c.close();}
});

test('multi-page response rejects ambiguous ordinal tuples and unlabelled vision regions',()=>{
 assert.throws(()=>validateDirectResponse(reply([[1,'Привет'],[1,'Стой']]),[page(1),page(2)]),/номер/);
 const pages=[1,2,3].map(n=>({...page(n),inputMode:'vision',regions:[]}));
 assert.throws(()=>validateDirectResponse(reply([{box:[0,0,100,100],ru:'Привет'}]),pages),/страницы/);
 const rows=pages.map(p=>({page:p.id,box:[100,100,200,300],ru:'Привет'}));assert.equal(validateDirectResponse(reply(rows),pages).length,3);
 assert.throws(()=>validateDirectResponse(reply(rows.slice(0,2)),pages),/пропустил страницу/);
});
