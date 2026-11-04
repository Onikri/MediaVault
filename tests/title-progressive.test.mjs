import test from 'node:test';import assert from 'node:assert/strict';
import {loadTitleProfile} from '../src/title-metadata.js';
test('title core appears while independent sections are still loading',async()=>{
 const original=globalThis.fetch;let release,done=false;const gate=new Promise(r=>release=r),parts=[],updates=[];
 globalThis.fetch=async value=>{const url=new URL(value);let body={data:{Media:null}};
  if(url.pathname==='/metadata/shikimori'){
   const part=url.searchParams.get('part');
   if(part){parts.push(part);await gate;body=[];}else body={id:987654321,russian:'Быстрый тайтл',name:'Fast title',description:'Описание уже доступно',kind:'tv',image:{original:'https://art.example/cover.jpg'}};
  }else if(url.pathname==='/metadata/posters')body={};
  return {ok:true,json:async()=>body};
 };
 try{
  const full=loadTitleProfile('987654321','anime',{server:'https://metadata.fixture',onPartial:value=>updates.push(value)}).then(value=>{done=true;return value;});
  await new Promise(r=>setTimeout(r,10));assert.equal(done,false);assert.equal(updates[0].title,'Быстрый тайтл');assert.ok(updates[0].description);assert.ok(parts.includes('roles')&&parts.includes('related')&&parts.includes('screenshots'),'independent I/O starts together');
  release();const result=await full;assert.equal(result.title,'Быстрый тайтл');assert.equal(result.partial,false);assert.equal(updates.at(-1).partial,false);
 }finally{release?.();globalThis.fetch=original;}
});
