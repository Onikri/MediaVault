import test from 'node:test';
import assert from 'node:assert/strict';
import {GemmaQueue} from '../src/gemma-queue.js';
import {translationConfig,resultConfig} from '../src/manga-translation.js';
test('Gemma cache profile excludes OCR, client credentials and translation weights',()=>{
 const config=translationConfig({engine:'gemma',apiKey:'do-not-store',serverModel:'irrelevant'});
 assert.equal(config.engine,'vm');assert.equal(config.font,'auto');
 const key=resultConfig(config);assert.equal(key.ocr,undefined);assert.equal(key.engine,'vm');
 assert.equal(key.translator,undefined);assert.equal(key.apiKey,undefined);assert.equal(key.host,undefined);
 assert.notDeepEqual(key,resultConfig({...config,vmPolicy:'new-prompt'}));
});
test('up to four queued pages share a batch; visible work stays first',async()=>{
 const calls=[],q=new GemmaQueue(async inputs=>{calls.push(inputs);return inputs;});
 const work=[q.request('a','prefetch',{background:true}),q.request('b','visible'),q.request('c','next',{background:true}),q.request('d','last',{background:true}),q.request('e','fifth',{background:true})];
 assert.equal(q.request('b','duplicate'),work[1]);await Promise.all(work);
 assert.deepEqual(calls,[['visible','prefetch','next','last'],['fifth']]);q.close();
});
test('one page failure does not destroy successfully rendered neighbours',async()=>{
 const q=new GemmaQueue(async()=>['good',Error('bad')]);
 const a=q.request('a',1),b=q.request('b',2);await assert.rejects(b,/bad/);assert.equal(await a,'good');q.close();
});
test('closing aborts a live batch and rejects queued work',async()=>{
 let finish;const q=new GemmaQueue(()=>new Promise(r=>finish=r));
 const tasks=Array.from({length:5},(_,i)=>q.request(''+i,i).then(()=>false,e=>e.name==='AbortError'));
 await new Promise(r=>setTimeout(r,0));q.close();finish([1,2,3,4]);assert.ok((await Promise.all(tasks)).every(Boolean));
});
