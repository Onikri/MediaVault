import test from 'node:test';
import assert from 'node:assert/strict';
import {createRetainedMediaStore} from '../src/retained-media-store.js';
test('only the active tree survives navigation; history excludes private capabilities and is account scoped',()=>{
 const data=new Map();globalThis.localStorage={getItem:k=>data.get(k),setItem:(k,v)=>data.set(k,v)};
 const store=createRetainedMediaStore(),anchor={isConnected:true};let pauses=0;
 store.scope('alice');store.attach('a',{userId:'alice',label:'Episode A',kind:'video',route:'#title=a',source:'signed-secret',token:'secret'},anchor,{});
 store.rows.get('a').host={querySelector:s=>s==='video.mv-player-media'?{pause(){pauses++;}}:null};
 store.activate('a');store.detach('a',anchor);assert.equal(store.rows.size,1);assert.equal(pauses,1);
 store.attach('idle',{userId:'alice',label:'Not opened',route:'#title=b'},anchor,{});store.detach('idle',anchor);assert.equal(store.rows.size,1);
 const serialized=data.get('mv_viewing_history_v1:alice');assert.ok(serialized.includes('Episode A'));assert.ok(!serialized.includes('secret'));assert.ok(!serialized.includes('source'));
 store.attach('b',{userId:'alice',label:'Episode B',route:'#title=b'},anchor,{});store.activate('b');assert.equal(store.rows.has('a'),false);assert.equal(store.getSnapshot().active,'b');
 store.scope('bob');assert.equal(store.rows.size,0);assert.equal(store.getSnapshot().history.length,0);
 store.scope('alice');assert.equal(store.getSnapshot().history.length,2);
});
