// Real export DirectChapter dispatcher, mocked detector/Google/render contracts.
import test from 'node:test';import assert from 'node:assert/strict';
import {DirectChapter} from '../src/manga-direct.js';
import {translationConfig} from '../src/manga-translation.js';
const tick=()=>new Promise(r=>setTimeout(r,0));

test('a blank export page needs neither a credential nor a Google request',async()=>{
 const c=new DirectChapter({entries:[{async:async()=>new Blob(['blank'])}],scope:'blank-export',config:translationConfig({chapterPipeline:false,directInput:'blocks',cache:false}),getKey:()=>'',cacheKey:async()=> 'blank',prepare:async()=>({page:1,width:100,height:100,regions:[]}),google:async()=>{throw Error('Blank page must remain local');}});
 try{const result=await c.request(0,null).promise;assert.deepEqual(result.regions,[]);assert.equal(c.keyBusy.size,0);}finally{c.close();}
});

test('export crop packets overlap across available keys, skip saved pages and release every lease',async()=>{
 let release;const gate=new Promise(r=>release=r),sent=[],prepared=[],read=[],skip=new Set([2]);
 const c=new DirectChapter({entries:Array.from({length:7},(_,i)=>({async:async()=>{read.push(i);assert.ok(!skip.has(i));return new Blob(['page'+i]);}})),scope:'export',config:translationConfig({engine:'vm',directViaOracle:true,chapterPipeline:false,directInput:'blocks',cache:false,skipPages:skip}),serverSlots:[0,1,2],service:()=>({}),cacheKey:async b=>b.text(),
  prepare:async(b,i)=>{prepared.push(i);return {id:'P'+(i+1),page:i+1,width:1800,height:2200,image:'fixture',mime:'image/png',regions:[{id:'P'+(i+1)+'_B1',bbox:[10,10,1610,2010]}]};},
  google:async(pages,o)=>{sent.push({ids:pages.flatMap(p=>p.regions.map(r=>r.id)),key:o.key});await gate;return{pages:pages.map(p=>({page:p.page,regions:p.regions.map(r=>({uid:r.id,text_bbox:r.bbox,ru_translation:'Готовый перевод'}))}))};}});
 c.canvasTask=async m=>m.sheets.map(s=>({...s,image:'fixture',mime:'image/png'}));
 try{
  const jobs=[0,1,3,4,5,6].map(i=>c.request(i,null));
  for(let n=0;n<150&&sent.length<3;n++)await tick();
  assert.equal(sent.length,3,'A waiting Google packet does not stall preparation or other credentials');
  assert.equal(new Set(sent.map(v=>v.key)).size,3);assert.equal(c.active,3);
  release();const result=await Promise.all(jobs.map(j=>j.promise));
  assert.deepEqual(result.map(p=>p.page),[1,2,4,5,6,7]);assert.equal(prepared.length,6);assert.equal(read.length,6,'Fingerprint/source work is not repeated for the first page');
  for(let n=0;n<20&&c.keyBusy.size;n++)await tick();assert.equal(c.keyBusy.size,0);assert.equal(c.active,0);
 }finally{release();c.close();}
});
