import test from 'node:test';
import assert from 'node:assert/strict';
import {PageResource} from '../src/reader-page-resource.js';
import {folderClient,modelFileName,readModelResponse} from '../src/model-folder.js';
import {safeDiagnosticExport} from '../src/google-request-diagnostics.js';
import {rendererPool} from '../src/reader-worker-pool.js';

test('one image URL survives overlapping visibility requests; closes exactly once',async()=>{
 let reads=0,created=0;const revoked=[],blob=new Blob(['page']),entry={async:async()=>{reads++;return blob;}};
 const lease=new PageResource({create:()=>{created++;return 'blob:stable';},revoke:url=>revoked.push(url)});
 const[a,b]=await Promise.all([lease.load(entry),lease.load(entry)]);
 assert.equal(a,b);assert.equal(a.blob,blob);assert.equal(reads,1);assert.equal(created,1);
 assert.equal((await lease.load(entry)).source,'blob:stable');assert.deepEqual(revoked,[]);
 lease.close();lease.close();assert.deepEqual(revoked,['blob:stable']);assert.equal(await lease.load(entry),null);
});
test('closing while page decoding cannot create an orphan URL',async()=>{
 let finish;const task=new Promise(resolve=>finish=resolve);let urls=0;
 const lease=new PageResource({create:()=>{urls++;return 'blob:late';},revoke:()=>assert.fail('no URL exists')});
 const load=lease.load({async:()=>task});lease.close();finish(new Blob(['page']));
 assert.equal(await load,null);assert.equal(urls,0);
});
test('page read failures can retry without mounting a new page',async()=>{
 let attempts=0;const entry={async:async()=>{if(!attempts++)throw Error('network');return new Blob(['ok']);}};
 const lease=new PageResource({create:()=> 'blob:retry',revoke(){}});
 await assert.rejects(lease.load(entry),/network/);assert.equal((await lease.load(entry)).source,'blob:retry');lease.close();
});
test('directory cache separates same-named weights by source and revision',async()=>{
 const a=await modelFileName('https://huggingface.co/a/resolve/old/model.onnx');
 const b=await modelFileName('https://huggingface.co/a/resolve/new/model.onnx');
 assert.notEqual(a,b);assert.match(a,/^[a-f0-9]{24}-model\.onnx$/);
 await assert.rejects(modelFileName('https://user:password@example.com/model.onnx'));
 await assert.rejects(modelFileName('https://example.com/model.onnx?token=private'));
});
test('folder models survive a fresh client and revoked permission never prompts in workers',async()=>{
 const files=new Map();let permission='granted',prompts=0;
 const handle={queryPermission:async()=>permission,requestPermission(){prompts++;},
  async getFileHandle(name,{create=false}={}){if(!files.has(name)&&!create)throw Error('NotFound');return {
   getFile:async()=>files.get(name),
   createWritable:async()=>{let bytes;return {write:async b=>bytes=b,close:async()=>files.set(name,new Blob([bytes])),abort:async()=>{}};},
  };},removeEntry:async name=>files.delete(name)};
 const url='https://huggingface.co/a/resolve/pinned/model.onnx',client=folderClient(async()=>handle);
 assert.equal(await client.read(url),null);assert.equal(await client.write(url,new Uint8Array([1,2,3])),true);
 const restarted=folderClient(async()=>handle);assert.deepEqual(new Uint8Array(await(await restarted.read(url)).arrayBuffer()),new Uint8Array([1,2,3]));
 permission='prompt';assert.equal(await restarted.read(url),null);assert.equal(await restarted.write(url,new Uint8Array([4])),false);assert.equal(prompts,0);
});
test('model download progress counts real bytes and rejects truncated bodies',async()=>{
 const progress=[];const response=new Response(new Uint8Array([1,2,3]),{headers:{'content-length':'3'}});
 assert.deepEqual(new Uint8Array(await readModelResponse(response,(a,b)=>progress.push([a,b]))),new Uint8Array([1,2,3]));assert.deepEqual(progress.at(-1),[3,3]);
 await assert.rejects(readModelResponse(new Response(new Uint8Array([1]),{headers:{'content-length':'3'}}),()=>{}),/неполный/);
});
test('debug exports omit complete image payload and remove auth fields recursively',()=>{
 const d={requestBody:{secret:'image'},transport:{keySlot:2,serverKey:true},response:{authorization:'secret',apiKey:'secret',message:'key=AQ.secretsecretsecretsecret'}};
 const text=JSON.stringify(safeDiagnosticExport(d));assert.ok(!text.includes('image'));assert.ok(!text.includes('"apiKey"'));assert.ok(!text.includes('"authorization"'));assert.ok(!text.includes('AQ.secret'));assert.match(text,/"keySlot":2/);
});
test('idle renderer keeps model sessions across readers; busy or expired renderers terminate',()=>{
 let created=0,expired;const workers=[],pool=rendererPool({create:()=>{const worker={terminated:0,terminate(){this.terminated++;}};workers.push(worker);created++;return worker;},schedule:fn=>{expired=fn;return 1;},cancel(){}});
 const a=pool.acquire();pool.release(a);const b=pool.acquire();assert.equal(a,b);assert.equal(created,1);
 pool.release(b,true);assert.equal(a.terminated,1);
 const c=pool.acquire();assert.notEqual(c,a);pool.release(c);expired();assert.equal(c.terminated,1);
 const d=pool.acquire();pool.release(d);pool.clear();assert.equal(d.terminated,1);
});
