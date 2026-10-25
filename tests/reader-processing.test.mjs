import test from 'node:test';
import assert from 'node:assert/strict';
import {encodeImage,decodeImage,processOnBackend,createPageProcessor} from '../src/reader-processing.js';

test('binary page transport preserves every byte',()=>{
 const input=Uint8Array.from({length:20491},(_,i)=>i%256);
 assert.deepEqual(new Uint8Array(decodeImage(encodeImage(input))),input);
});
test('backend polling returns neural image and progress without an LLM endpoint in client payload',async()=>{
 const calls=[],statuses=[];
 const service={status:'connected',request:async(path,request)=>{
  calls.push({path,request});
  if(path==='/reader/jobs')return {id:'task'};
  return calls.length===2?{state:'running',status:'tile 1/2'}:{state:'done',result:{regions:[],renderedImage:'AQID',upscale:{scale:2}}};
 }};
 const result=await processOnBackend(new Blob(['page']),{upscale:true},service,new AbortController().signal,s=>statuses.push(s),0);
 assert.deepEqual([...new Uint8Array(result.renderedImage)],[1,2,3]);
 assert.deepEqual(statuses.slice(0,1),['tile 1/2']);
 assert.deepEqual(calls[0].request.body.options,{upscale:true});
});
test('a submission that completes after cancellation is cancelled on backend',async()=>{
 const abort=new AbortController(),calls=[];let complete;
 const service={status:'connected',request:async(path)=>{
  calls.push(path);if(path==='/reader/jobs')return new Promise(resolve=>{complete=resolve;});return {};
 }};
 const task=processOnBackend(new Blob(['page']),{upscale:true},service,abort.signal);
 while(!complete)await new Promise(resolve=>setTimeout(resolve,0));
 abort.abort();complete({id:'late'});
 await assert.rejects(task,{name:'AbortError'});
 assert.deepEqual(calls,['/reader/jobs','/reader/jobs/late/cancel']);
});
test('reader serializes pages, skips cancelled work and invalidates cache when model changes',async()=>{
 let config={engine:'backend',translate:true,allowDownloads:true},submissions=0,active=0;
 const service={status:'connected',request:async(path)=>{
  if(path==='/reader/jobs'){assert.equal(active,0);active++;submissions++;return {id:String(submissions)};}
  active--;return {state:'done',result:{regions:[],renderedImage:'AQID'}};
 }};
 const process=createPageProcessor({getConfig:()=>config,getService:()=>service,getChapter:()=>({id:'chapter'})});
 const controller=new AbortController(),blob=new Blob(['page']);
 await Promise.all([process(blob,controller.signal,undefined,0),process(blob,controller.signal,undefined,0)]);
 assert.equal(submissions,1);
 config={...config,ocr:'manga-ocr'};await process(blob,controller.signal,undefined,0);assert.equal(submissions,2);
 const stopped=new AbortController();stopped.abort();await assert.rejects(process(blob,stopped.signal,undefined,1),{name:'AbortError'});assert.equal(submissions,2);
});
