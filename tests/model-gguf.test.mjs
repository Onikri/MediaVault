import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {cachedGguf} from '../src/model-gguf.js';
const bytes=new TextEncoder().encode('model fixture bytes'),model={bytes:bytes.length,sha:createHash('sha256').update(bytes).digest('hex')};
test('verified GGUF in selected folder loads without any download or browser-cache quota',async()=>{
 const blob=new Blob([bytes]);const source=await cachedGguf('https://fixture/model.gguf',model,{downloadModel:()=>assert.fail('offline file must not download')},()=>{},{read:async()=>blob,remove:async()=>{}});
 assert.equal(source.size,bytes.length);assert.equal((await source.open())[0],blob);
});
test('first download copies blobs to the selected disk and the next launch is offline',async()=>{
 let disk=null,downloads=0,writes=0;const options={read:async()=>disk,writable:async()=>true,write:async(url,blob)=>{writes++;disk=blob;},remove:async()=>{disk=null;}},manager={downloadModel:async()=>{downloads++;return{size:bytes.length,open:async()=>[new Blob([bytes])],remove:async()=>{}};}};
 await cachedGguf('https://fixture/model.gguf',model,manager,()=>{},options);await cachedGguf('https://fixture/model.gguf',model,manager,()=>{},options);assert.equal(downloads,1);assert.equal(writes,1);assert.ok(disk instanceof Blob);
});
test('modified disk model is rejected and removed before inference',async()=>{
 let removed=0;await assert.rejects(cachedGguf('https://fixture/model.gguf',{...model,sha:'0'.repeat(64)},{},()=>{},{read:async()=>new Blob([bytes]),remove:async()=>removed++}),/SHA-256/);assert.equal(removed,1);
});
