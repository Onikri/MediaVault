import test from 'node:test';
import assert from 'node:assert/strict';
import {mergeCatalog,titleLookup} from '../src/catalog.js';
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

test('index-only cards reopened without a snapshot read the index card, never a catalogue API',()=>{
 const empty={getItem:()=>null};
 for(const [route,kind,provider,id] of [
  ['ranobe:ranobelib:ranobelib:https://ranobelib.me/ru/book/116379--i-devour-mechas','ranobe','ranobelib','https://ranobelib.me/ru/book/116379--i-devour-mechas'],
  ['anime:hanime:hanime:https://hanime.tv/videos/hentai/tropical-kiss-ova-1','anime','hanime','https://hanime.tv/videos/hentai/tropical-kiss-ova-1']]){
  const value=readOnlineTitle('#watch='+route,empty);
  // The route alone sets providerId to the whole "provider:url" identity.
  assert.equal(value.providerId,provider+':'+id);
  assert.deepEqual(titleLookup(value,true),{index:{kind,provider,id}});
  assert.equal(titleLookup(value,false),null,'an older server without the index asks nothing');
  // The same identity from the index row itself (no providerId) needs no lookup.
  assert.equal(titleLookup({kind,provider,id:provider+':'+id,title:'X'},true),null);
 }
 assert.deepEqual(titleLookup({kind:'anime',provider:'shikimori',providerId:'1'},true),{catalog:true});
 assert.deepEqual(titleLookup({kind:'book',provider:'openlibrary',providerId:'OL1W'},false),{catalog:true});
 assert.equal(titleLookup({kind:'book',provider:'openlibrary',providerId:'OL1M'},true),null);
 assert.deepEqual(titleLookup({kind:'movie',provider:'omdb',providerId:'42'},true),{index:{kind:'movie',provider:'omdb',id:'42'}});
 assert.equal(titleLookup({kind:'movie',provider:'omdb',providerId:'42'},false),null);
 assert.equal(titleLookup({kind:'anime',provider:'youtube',providerId:'v'},true),null);
 assert.equal(titleLookup({kind:'manga',provider:'mangalib',providerId:'mangalib:https://mangalib.me/ru/x'},true),null);
 assert.equal(titleLookup({kind:'anime',provider:'hanime',providerId:'hanime:u',sourceOnly:true},true),null);
});
