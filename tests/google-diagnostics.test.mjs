import test from 'node:test';import assert from 'node:assert/strict';
import {directRequest,callDirectGoogle} from '../src/manga-direct-api.js';
import {requestDiagnostics,redactGoogle,xhrGoogle,INLINE_REQUEST_LIMIT} from '../src/google-request-diagnostics.js';
import {translationConfig} from '../src/manga-translation.js';
const page={id:'P1',page:1,width:600,height:850,mime:'image/webp',image:'YWJjZA==',regions:[{id:'P1_B1',bbox:[10,20,80,100]}]};
test('Flash Lite models use correct minimal thinking controls; old two-page preferences migrate to one',()=>{
 for(const model of ['gemini-3.5-flash-lite','gemini-3.1-flash-lite']){const b=directRequest([page],{model});assert.deepEqual(b.generationConfig.thinkingConfig,{thinkingLevel:'MINIMAL'});assert.equal(b.generationConfig.temperature,undefined);assert.equal(translationConfig({engine:'direct',directModel:model,directPair:true}).directPair,false);}
 assert.deepEqual(directRequest([page],{model:'gemini-2.5-flash-lite'}).generationConfig.thinkingConfig,{thinkingBudget:0});assert.equal(translationConfig().directPrefetch,false);
});
test('diagnostics include actual UTF-8 JSON/image byte counts and original local coordinates',()=>{
 const body=directRequest([page]),d=requestDiagnostics([page],body,'gemma-4-31b-it');assert.equal(d.requestBytes,Buffer.byteLength(JSON.stringify(body)));assert.equal(d.images[0].bytes,4);assert.equal(d.limitBytes,INLINE_REQUEST_LIMIT);assert.deepEqual(d.coordinates[0].regions[0].text_bbox,page.regions[0].bbox);assert.match(d.requestPreview.contents[0].parts[2].inlineData.data,/base64: 8/);assert.equal(d.requestBody,body);
});
test('Google errors preserve quota/parameter details while excluding the exact personal key',async()=>{
 const key='fixture-KEY-private',seen=[],fetcher=async()=>({status:400,text:async()=>JSON.stringify({error:{status:'INVALID_ARGUMENT',message:'Unsupported thinkingLevel; key='+key,details:[{field:'generationConfig.thinkingConfig'}]}})});
 await assert.rejects(callDirectGoogle([page],{key,fetcher,onDiagnostic:d=>seen.push(d)}),error=>{assert.match(error.message,/HTTP 400/);assert.match(error.message,/thinkingLevel/);assert.ok(!JSON.stringify(error.diagnostics).includes(key));return true;});
 const last=seen.at(-1);assert.equal(last.stage,'error');assert.equal(last.httpStatus,400);assert.equal(last.googleError.status,'INVALID_ARGUMENT');assert.equal(last.googleError.details[0].field,'generationConfig.thinkingConfig');
 assert.equal(redactGoogle({apiKey:key,text:key},key).apiKey,undefined);
});
test('XHR exposes upload, headers, first response bytes and completion as separate events',async()=>{
 const sent=[],events=[];const xhr={upload:{},readyState:0,status:0,responseText:'',open:(method,url)=>sent.push({method,url}),setRequestHeader:(name,value)=>sent.push({name,value}),getResponseHeader:()=>null,send(json){queueMicrotask(()=>{this.upload.onprogress({loaded:5,total:10,lengthComputable:true});this.upload.onload();this.readyState=2;this.status=200;this.onreadystatechange();this.onprogress({loaded:10,total:0,lengthComputable:false});this.responseText='{"ok":true}';this.onload();});},abort(){this.onabort?.();}};
 const result=await xhrGoogle({url:'https://google.fixture',key:'private',json:'{"test":1}',timeoutMs:30000,onEvent:e=>events.push(e),xhrFactory:()=>xhr});
 assert.equal(result.status,200);assert.deepEqual(events.map(e=>e.phase),['sending','uploading','waiting','headers','receiving','receiving','received']);assert.equal(events.find(e=>e.phase==='headers').httpStatus,200);assert.equal(events.find(e=>e.phase==='waiting').uploadLoaded,10);assert.ok(events.find(e=>e.phase==='received').responseBytes>0);assert.ok(!JSON.stringify(events).includes('private'));
});
test('XHR abort/timeout release caller and cannot turn into an unbounded wait',async()=>{
 const controller=new AbortController();let xhr;
 const factory=()=>xhr={upload:{},open(){},setRequestHeader(){},send(){},abort(){this.onabort();}};
 const task=xhrGoogle({url:'https://google.fixture',key:'private',json:'{}',signal:controller.signal,timeoutMs:10,xhrFactory:factory});controller.abort();await assert.rejects(task,{name:'AbortError'});
 const seen=[];const timeout=xhrGoogle({url:'https://google.fixture',key:'private',json:'{}',timeoutMs:10,onEvent:e=>seen.push(e),xhrFactory:factory});xhr.readyState=4;xhr.status=0;xhr.onreadystatechange();assert.ok(!seen.some(e=>e.phase==='headers'));xhr.ontimeout();await assert.rejects(timeout,{name:'TimeoutError'});
});
