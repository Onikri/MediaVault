import test from 'node:test';
import assert from 'node:assert/strict';
import {readProgress,writeProgress} from '../src/playback-progress.js';
import {buildTitles} from '../src/library-model.js';
import {matchesFilters} from '../src/catalog.js';
const storage=()=>{const values=new Map();return {getItem:key=>values.get(key)||null,setItem:(key,v)=>values.set(key,v),removeItem:key=>values.delete(key)}};
test('resume positions belong to one user, library and title; completed playback clears the continuation',()=>{
  const cache=storage(),item={id:'ep-3',collectionId:'title-1'};
  writeProgress('alice','vault1',item,62,1000,cache);
  assert.equal(readProgress('alice','vault1','ep-3',cache).time,62);
  assert.equal(readProgress('alice','vault1','collection:title-1',cache).itemId,'ep-3');
  assert.equal(readProgress('bob','vault1','ep-3',cache),null);
  assert.equal(readProgress('alice','vault2','ep-3',cache),null);
  writeProgress('alice','vault1',item,995,1000,cache);
  assert.equal(readProgress('alice','vault1','ep-3',cache),null);
  assert.equal(readProgress('alice','vault1','collection:title-1',cache),null);
});
test('unavailable/corrupted storage does not break video playback',()=>{
  const broken={getItem(){throw Error('unavailable')},setItem(){throw Error('full')},removeItem(){throw Error('no')}};
  assert.equal(readProgress('a','b','c',broken),null);
  assert.doesNotThrow(()=>writeProgress('a','b',{id:'c'},10,100,broken));
});
test('Russian and English collection names with the same exact metadata ID produce one title',()=>{
  const catalog={storage:{collections:[{id:'ru',name:'Дандадан',section:'anime',metadata:{ids:{mal:'57334'}}},{id:'en',name:'Dandadan',section:'anime',metadata:{ids:{mal:'57334'}}},{id:'second',name:'Дандадан 2',section:'anime',metadata:{ids:{mal:'60543'}}}]},items:[{id:'1',collectionId:'ru',section:'anime',category:'video',name:'1.mp4'},{id:'2',collectionId:'en',section:'anime',category:'video',name:'2.mp4'},{id:'3',collectionId:'second',section:'anime',category:'video',name:'3.mp4'}]};
  const titles=buildTitles(catalog);assert.equal(titles.length,2);assert.equal(titles[0].items.length,2);assert.equal(titles[1].items.length,1);
});
test('tag filtering matches the selected catalogue tags and requires all requested tags',()=>{
  const item={genres:['Drama'],tags:['School','Time Travel']};
  assert.equal(matchesFilters(item,{tag:'School'}),true);
  assert.equal(matchesFilters(item,{tag:'School, Time Travel'}),true);
  assert.equal(matchesFilters(item,{tag:'School, Vampires'}),false);
});
test('a browser denying localStorage does not crash progress loading',()=>{
  const descriptor=Object.getOwnPropertyDescriptor(globalThis,'localStorage');
  Object.defineProperty(globalThis,'localStorage',{configurable:true,get(){throw Error('denied')}});
  try{assert.equal(readProgress('a','b','c'),null);assert.doesNotThrow(()=>writeProgress('a','b',{id:'c'},20,100));}
  finally{if(descriptor)Object.defineProperty(globalThis,'localStorage',descriptor);else delete globalThis.localStorage;}
});
test('unknown external identifiers cannot merge unrelated catalogue records',async()=>{
 const {normalizeCatalog,mergeCatalog}=await import('../src/catalog.js');
 const data={data:{Page:{media:[{id:1,title:{english:'One'},idMal:0},{id:2,title:{english:'Two'},idMal:null}]}}};
 const rows=normalizeCatalog('anilist',data,'anime');assert.deepEqual(rows[0].ids,{});assert.equal(mergeCatalog(rows).length,2);
});
