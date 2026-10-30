import test from 'node:test';
import assert from 'node:assert/strict';
import {readingOrder,linkPageBlocks,packBlockSheets,unpackBlockTranslations} from '../src/manga-blocks.js';
import {DirectChapter} from '../src/manga-direct.js';
import {translationConfig,resultConfig} from '../src/manga-translation.js';
import {directRequest,validateDirectResponse} from '../src/manga-direct-api.js';

const page=(n,boxes=[[100,100,300,200]])=>({id:'P'+n,page:n,width:600,height:900,inputMode:'blocks',regions:boxes.map((bbox,i)=>({id:'P'+n+'_B'+(i+1),bbox})),detectionMs:1});
test('six sparse pages share one sheet without shrinking native crop pixels',()=>{
 const pages=Array.from({length:6},(_,i)=>page(i+1)),groups=linkPageBlocks(pages),sheets=packBlockSheets(groups);
 assert.equal(sheets.length,1);assert.equal(sheets[0].regions.length,6);
 for(const{box,group}of sheets[0].placements){assert.equal(box[2]-box[0],group.width);assert.equal(box[3]-box[1],group.height);}
 const request=directRequest(sheets.map(s=>({...s,image:'fixture',mime:'image/png'})));
 assert.equal(request.contents[0].parts.filter(p=>p.inlineData).length,1);assert.match(request.contents[0].parts[0].text,/contact sheets/);
});
test('reading order groups rows deterministically for manga and webtoons',()=>{
 const regions=page(1,[[20,30,120,100],[300,35,400,110],[10,200,150,280]]).regions;
 assert.deepEqual(readingOrder(regions,'ltr').map(r=>r.id),['P1_B1','P1_B2','P1_B3']);
 assert.deepEqual(readingOrder(regions,'rtl').map(r=>r.id),['P1_B2','P1_B1','P1_B3']);
});
test('sheet budgets split dense pages and preserve IDs across sheets',()=>{
 const groups=linkPageBlocks([page(1,Array.from({length:30},(_,i)=>[50,i*20,550,i*20+250]))]);
 const sheets=packBlockSheets(groups);assert.ok(sheets.length>1);assert.equal(new Set(sheets.flatMap(s=>s.regions.map(r=>r.id))).size,30);
 for(const sheet of sheets)for(const r of sheet.regions){assert.ok(r.bbox[2]<=sheet.width);assert.ok(r.bbox[3]<=sheet.height);}
});
test('webtoon seam is translated once and flows across both original page rectangles',()=>{
 const pages=[page(1,[[100,840,300,899]]),page(2,[[105,0,295,80]])],groups=linkPageBlocks(pages,{webtoon:true,direction:'ltr'});
 assert.equal(groups.length,1);assert.equal(groups[0].parts.length,2);
 assert.equal(linkPageBlocks(pages,{webtoon:false}).length,2);
 const sheets=packBlockSheets(groups),rows=[{page:1,regions:[{uid:'P1_B1',ru_translation:'Единая реплика без повторения.',font_style:'standard_comic'}]}],out=unpackBlockTranslations(rows,sheets,pages);
 assert.equal(out[0].regions[0].flow.id,out[1].regions[0].flow.id);assert.equal(out[0].regions[0].flow.offsetY,0);assert.equal(out[1].regions[0].flow.offsetY,60);
 assert.deepEqual(out[0].regions[0].text_bbox,pages[0].regions[0].bbox);assert.deepEqual(out[1].regions[0].text_bbox,pages[1].regions[0].bbox);
 assert.equal(out[0].regions[0].flow.height,140);
});
test('seams reject ambiguous bubbles, nonadjacent pages and unequal source widths',()=>{
 const a=page(1,[[100,840,300,899]]),b=page(2,[[105,0,295,80],[110,0,290,90]]);
 assert.equal(linkPageBlocks([a,b],{webtoon:true}).length,3);
 assert.equal(linkPageBlocks([a,{...page(3,[[100,0,300,80]])}],{webtoon:true}).length,2);
 assert.equal(linkPageBlocks([a,{...page(2,[[100,0,300,80]]),width:650}],{webtoon:true}).length,2);
});
test('missing or duplicate block IDs cannot paint a partial response',()=>{
 const pages=[page(1),page(2)],sheets=packBlockSheets(linkPageBlocks(pages));
 assert.throws(()=>unpackBlockTranslations([{regions:[]}],sheets,pages),/не все/);
 assert.throws(()=>unpackBlockTranslations([{regions:[{uid:'P1_B1'},{uid:'P1_B1'}]}],sheets,pages),/ID/);
});
test('block cache identity separates reading direction, input and linked-page policy',()=>{
 const base=translationConfig({engine:'direct',directInput:'blocks'});
 assert.notDeepEqual(resultConfig(base),resultConfig({...base,directInput:'annotated'}));
 assert.notDeepEqual(resultConfig(base),resultConfig({...base,direction:'ltr'}));
 assert.notDeepEqual(resultConfig(base),resultConfig({...base,webtoon:true}));
 assert.ok(!JSON.stringify(resultConfig({...base,apiKey:'secret'})).includes('secret'));
});
test('chapter queues six source pages as one sheet request, then returns original geometry',async()=>{
 const calls=[],entries=Array.from({length:6},(_,i)=>({async:async()=>new Blob(['page'+i])}));
 const c=new DirectChapter({entries,scope:'fixture',keyScope:'fixture',config:translationConfig({engine:'direct',directInput:'blocks',cache:false}),prepare:async(blob,i)=>page(i+1),getKey:()=> 'fixture-key',google:async sheets=>{
  calls.push(sheets);return {pages:validateDirectResponse({candidates:[{finishReason:'STOP',content:{parts:[{text:JSON.stringify(sheets.flatMap(s=>s.regions.map(r=>({id:r.id,ru:'Привет!'}))))}]}}]},sheets)};
 },cacheKey:async blob=>blob.text(),renderPage:async(blob,p)=>({regions:p.regions,timings:{}})});
 c.canvasTask=async message=>{assert.equal(message.operation,'blocks-pack');return message.sheets.map(s=>({...s,image:'fixture',mime:'image/png'}));};
 try{const result=await c.render(new Blob(['page0']),0,'auto',null,{},new AbortController().signal);assert.equal(calls.length,1);assert.equal(calls[0].length,1);assert.equal(calls[0][0].regions.length,6);assert.deepEqual(result.regions[0].text_bbox,[100,100,300,200]);assert.equal(result.detected.regions.length,1);assert.equal(result.detectionReport.translated,1);assert.equal(c.snapshot().jobs.filter(j=>j.state==='done').length,6);}finally{c.close();}
});

test('failed first source rejects its waiter instead of leaving the reader loading',async()=>{
 const c=new DirectChapter({entries:[{async:async()=>{throw Error('source failed');}}],scope:'fixture',config:translationConfig({engine:'direct',directInput:'blocks',cache:false}),getKey:()=> 'fixture',cacheKey:async()=> 'fixture'});
 try{await assert.rejects(c.request(0,null).promise,/source failed/);assert.equal(c.jobs.size,0);}finally{c.close();}
});
test('webtoon cache identity changes when either adjacent source changes',async()=>{
 const make=next=>new DirectChapter({entries:[{async:async()=>new Blob(['same'])},{async:async()=>new Blob([next])}],scope:'fixture',config:translationConfig({engine:'direct',directInput:'blocks',webtoon:true}),cacheKey:async blob=>blob.text()});
 const a=make('old'),b=make('new');try{assert.notEqual(await a.jsonCacheId(new Blob(['same']),0),await b.jsonCacheId(new Blob(['same']),0));}finally{a.close();b.close();}
});
