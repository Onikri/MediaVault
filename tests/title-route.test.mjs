import test from 'node:test';
import assert from 'node:assert/strict';
import {readOnlineTitle,onlineTitleLocation} from '../src/title-route.js';

test('online title address restores exact identity without a catalogue search or private media',()=>{
 const values=new Map(),storage={getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)};
 const previous=Object.fromEntries(['location','localStorage','history','dispatchEvent','HashChangeEvent'].map(k=>[k,globalThis[k]]));
 Object.assign(globalThis,{location:{pathname:'/MediaVault/',search:'',hash:'#library'},localStorage:storage,history:{pushState(_a,_b,url){globalThis.location.hash=url.slice(url.indexOf('#'));}},dispatchEvent(){},HashChangeEvent:class{}});
 try{
  onlineTitleLocation({id:'shiki:16498',provider:'shikimori',providerId:'16498',kind:'anime',title:'Атака титанов',ids:{mal:'16498'},privateToken:'secret',stream:'https://private.invalid'});
  const saved=readOnlineTitle();assert.equal(saved.providerId,'16498');assert.equal(saved.title,'Атака титанов');assert.equal(saved.privateToken,undefined);assert.equal(saved.stream,undefined);
  assert.equal(readOnlineTitle(location.hash,{getItem:()=>null}).ids.mal,'16498','A shared link resolves without a local snapshot');
  assert.equal(readOnlineTitle('#library',storage),null);
  assert.equal(readOnlineTitle('#watch=invalid:shikimori:16498',storage),null);
 }finally{Object.assign(globalThis,previous);}
});
