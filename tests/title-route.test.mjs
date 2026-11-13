import test from 'node:test';
import assert from 'node:assert/strict';
import {mergeCatalog} from '../src/catalog.js';
import {readOnlineTitle,onlineTitleLocation} from '../src/title-route.js';

test('online title address restores exact identity without a catalogue search or private media',()=>{
 const values=new Map(),storage={getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)};
 const previous=Object.fromEntries(['location','localStorage','history','dispatchEvent','HashChangeEvent'].map(k=>[k,globalThis[k]]));
 Object.assign(globalThis,{location:{pathname:'/MediaVault/',search:'',hash:'#library'},localStorage:storage,history:{pushState(_a,_b,url){globalThis.location.hash=url.slice(url.indexOf('#'));}},dispatchEvent(){},HashChangeEvent:class{}});
 try{
  onlineTitleLocation({id:'shiki:16498',provider:'shikimori',providerId:'16498',kind:'anime',title:'Атака титанов',ids:{mal:'16498'},privateToken:'secret',stream:'https://private.invalid'});
  const saved=readOnlineTitle();assert.equal(saved.providerId,'16498');assert.equal(saved.title,'Атака титанов');assert.equal(saved.privateToken,undefined);assert.equal(saved.stream,undefined);
  const shared=readOnlineTitle(location.hash,{getItem:()=>null});
  assert.equal(shared.ids.mal,'16498','A shared link resolves without a local snapshot');
  assert.doesNotThrow(()=>mergeCatalog([shared,{...shared,title:'Атака титанов',titles:{ru:'Атака титанов'}}]));
  assert.doesNotThrow(()=>mergeCatalog([saved,{...shared,title:'Атака титанов',titles:{ru:'Атака титанов'}}]));
  assert.equal(readOnlineTitle('#library',storage),null);
  assert.equal(readOnlineTitle('#watch=invalid:shikimori:16498',storage),null);
  onlineTitleLocation({id:'fixture:1',provider:'fixture',providerId:'1',kind:'manga',title:'Garden World',catalogId:'a'.repeat(32),sources:[{catalogId:'b'.repeat(32),url:'https://private.invalid/stream'},{catalogId:'not-an-index-id'}]});
  const manga=readOnlineTitle();assert.deepEqual(manga.catalogIds,['a'.repeat(32),'b'.repeat(32)]);
  assert.equal(manga.sources,undefined,'Only public index identities survive routing, never source/stream payloads');
 }finally{Object.assign(globalThis,previous);}
});
