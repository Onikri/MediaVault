// Real queues/render handoff; detector, Google and raster output are fixtures.
import test from 'node:test';import assert from 'node:assert/strict';
import {DirectChapter} from '../src/manga-direct.js';
import {translationConfig} from '../src/manga-translation.js';
import {saveReaderChapter} from '../src/reader-chapter-save.js';
import {probeReaderLanguage} from '../src/reader-language.js';
const tick=()=>new Promise(r=>setTimeout(r,0));
const defer=()=>{let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve};};

test('saving a chapter finishes page one before loading the remaining pages',async()=>{
 const gate=defer(),read=[],saved=[],png=new Uint8Array([137,80,78,71,13,10,26,10,1]);
 const task=saveReaderChapter({total:3,source:{blob:async i=>{read.push(i);return new Blob([png]);},render:async i=>{if(i===0)await gate.promise;return{renderedImage:png.buffer};}},onPage:i=>saved.push(i),concurrency:3});
 for(let n=0;n<5;n++)await tick();assert.deepEqual(read,[0]);assert.deepEqual(saved,[]);
 gate.resolve();const result=await task;assert.equal(result.total,3);assert.deepEqual(saved,[0,1,2]);
});

test('language identification does not wait for a stalled second page',async()=>{
 const gate=defer(),bodies=[];
 try{const value=await probeReaderLanguage({entries:[{async:async()=>new Blob(['page0'])},{async:async()=>gate.promise}],config:translationConfig({engine:'vm'}),serverSlots:[0],service:{status:'connected',session:{googleGatewayVersion:5},request:async(p,o)=>{bodies.push(o.body);return{candidates:[{content:{parts:[{text:JSON.stringify({dialogue:{en:100},sfx:{ja:100},hasDialogue:true})}]}}]};}},encode:async()=> 'fixture'});
  assert.deepEqual(value.samplePages,[1]);assert.equal(value.language,'English');assert.ok(value.prepMs<1500);assert.equal(bodies[0].priority,'interactive');assert.equal(bodies[0].pool,true);
 }finally{gate.resolve(new Blob(['page1']));}
});

for(const mode of ['annotated','blocks'])test('first '+mode+' page renders without waiting for its neighbour; background follows rendering',async()=>{
 const neighbour=defer(),render=defer(),sent=[];let painting=false;
 const c=new DirectChapter({entries:Array.from({length:4},(_,i)=>({async:async()=>{if(i)await neighbour.promise;return new Blob(['page'+i]);}})),scope:'priority',config:translationConfig({engine:'vm',directInput:mode,chapterPipeline:mode!=='blocks',firstPagePriority:true,cache:false}),serverSlots:[0,1,2],service:()=>({}),cacheKey:async b=>b.text(),
  prepare:async(b,i)=>({id:'P'+(i+1),page:i+1,width:100,height:100,image:'fixture',mime:'image/png',regions:[{id:'P'+(i+1)+'_B1',bbox:[10,10,60,60]}]}),
  google:async(pages,o)=>{sent.push({ids:pages.flatMap(p=>p.regions.map(r=>r.id)),interactive:o.interactive});return{pages:pages.map(p=>({page:p.page,width:p.width,height:p.height,regions:p.regions.map(r=>({uid:r.id,text_bbox:r.bbox,ru_translation:'Готово'}))}))};},
  renderPage:async()=>{painting=true;await render.promise;return{renderedImage:new Uint8Array([1,2]).buffer,timings:{}};}});
 c.canvasTask=async m=>m.operation==='blocks-pack'?m.sheets.map(s=>({...s,image:'fixture',mime:'image/png'})):{regions:[],cleanedImage:new ArrayBuffer(0)};
 try{
  const first=c.render(new Blob(['page0']),0,'auto');
  for(let n=0;n<100&&!painting;n++)await tick();
  assert.ok(painting,'First-page typesetting starts while neighbour download is blocked');
  assert.deepEqual(sent,[{ids:['P1_B1'],interactive:true}]);
  neighbour.resolve();for(let n=0;n<5;n++)await tick();assert.equal(sent.length,1,'Background API work waits until the first image is ready');
  render.resolve();await first;
  if(mode==='blocks')await Promise.all([1,2,3].map(i=>c.render(new Blob(['page'+i]),i,'auto')));
  else await Promise.all([...c.jobs.values()].map(j=>j.promise));
  assert.ok(sent.length>1);assert.equal(sent.flatMap(p=>p.ids).filter(id=>id==='P1_B1').length,1);
 }finally{neighbour.resolve();render.resolve();c.close();}
});

test('the interactive race is requested only once and only with a capable server',async()=>{
 const bodies=[];const c=new DirectChapter({entries:[],config:translationConfig({directViaOracle:true}),serverSlots:[0],service:()=>({session:{googleGatewayVersion:5},request:async(p,o)=>{bodies.push(o.body);return{};}}),google:async(p,o)=>{await o.transport({json:'{}'});return{pages:[]};}});
 try{for(let n=0;n<2;n++)await c.callGoogle([],{key:'oracle-slot:0',interactive:true,model:'gemini-3.5-flash-lite'});assert.deepEqual(bodies.map(b=>b.priority),['interactive','background']);assert.ok(bodies.every(b=>b.pool));}finally{c.close();}
});
