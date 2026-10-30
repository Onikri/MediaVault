import test from 'node:test';
import assert from 'node:assert/strict';
import {serializePipeline} from '../lmt/pipeline-queue.js';

test('parallel detector requests wait for the shared neural engine and keep page progress/results isolated',async()=>{
 let release;const gate=new Promise(r=>release=r),started=[],progress=[];let busy=0,maxBusy=0;
 const run=serializePipeline(async(page,status)=>{started.push(page);maxBusy=Math.max(maxBusy,++busy);try{status(page);if(page===1)await gate;return {page};}finally{busy--;}});
 const tasks=[1,2,3].map(page=>run(page,value=>progress.push([page,value])));
 await Promise.resolve();assert.deepEqual(started,[1]);release();
 assert.deepEqual(await Promise.all(tasks),[{page:1},{page:2},{page:3}]);
 assert.deepEqual(started,[1,2,3]);assert.deepEqual(progress,[[1,1],[2,2],[3,3]]);assert.equal(maxBusy,1);
});
test('a rejected inference does not discard or block later queued pages',async()=>{
 const run=serializePipeline(async(page)=>{if(page===1)throw Error('Invalid source');return page;});
 const results=await Promise.allSettled([run(1),run(2),run(3)]);
 assert.equal(results[0].status,'rejected');assert.equal(results[0].reason.message,'Invalid source');
 assert.deepEqual(results.slice(1),[{status:'fulfilled',value:2},{status:'fulfilled',value:3}]);
});
