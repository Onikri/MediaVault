import test from 'node:test';
import assert from 'node:assert/strict';
import {readWatch,saveWatch,orderedVoices,variantsFor,onlineEpisodeId} from '../src/watch-session.js';
test('online resume keeps logical episode and voice across changing source tokens, isolated by account',()=>{
 const entries=new Map(),storage={getItem:k=>entries.get(k),setItem:(k,v)=>entries.set(k,v)};
 saveWatch('one','57334',{voiceId:'anidub',episode:7,season:1},storage);
 saveWatch('one','57334',{audioId:'libria'},storage);
 assert.equal(readWatch('one','57334',storage).episode,7);assert.equal(readWatch('one','57334',storage).voiceId,'anidub');
 assert.deepEqual(readWatch('two','57334',storage),{});
 assert.equal(onlineEpisodeId('57334',1,7),'online:57334:s1:e7');assert.ok(![...entries.values()].some(s=>s.includes('http')));
});
test('preference ordering uses observed personal choices without invented public popularity',()=>{
 const voices=[{id:'a',name:'AniDub',language:'ru'},{id:'b',name:'Libria',language:'ru'},{id:'en',name:'English',language:'en'}];
 assert.deepEqual(orderedVoices(voices,{usage:{b:3}}).map(v=>v.id),['b','a']);
 assert.deepEqual(orderedVoices(voices,{voiceId:'a',usage:{b:3}}).map(v=>v.id),['a','b']);
});
test('source fallback keeps the chosen studio and exact episode',()=>{
 const voice={variants:[{id:'x',player:'Kodik',episodes:[{number:1}]},{id:'y',player:'Alloha',episodes:[{number:7}]},{id:'z',player:'Kodik',episodes:[{number:7}]}]};
 assert.deepEqual(variantsFor(voice,7,new Set(['y'])).map(v=>v.id),['z','x']);
});
