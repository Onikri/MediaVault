import test from 'node:test';import assert from 'node:assert/strict';
import {prepareInkPatch,compositeInkPatch} from '../src/manga-cleaning.js';
import {fitComicText} from '../src/manga-typeset.js';
import {googleStreamAccumulator,completedJsonRows} from '../src/google-stream.js';
import {directRequest,callDirectGoogle} from '../src/manga-direct-api.js';
const image=(width=180,height=120)=>({width,height,data:new Uint8ClampedArray(width*height*4).fill(255)});
function rect(img,x,y,w,h,color=0){for(let yy=y;yy<y+h;yy++)for(let xx=x;xx<x+w;xx++){const n=(yy*img.width+xx)*4;for(let c=0;c<3;c++)img.data[n+c]=color;}}
test('dense artwork cannot become a near-full Telea mask; valid glyph masks retain context',()=>{
 const page=image();rect(page,30,25,90,50);assert.ok(prepareInkPatch(page,[30,25,120,75]).declined);
 const text=image();for(let x=35;x<100;x+=12)rect(text,x,35,5,18);const patch=prepareInkPatch(text,[30,30,110,60]);assert.ok(!patch.declined);assert.ok(patch.coverage>0&&patch.coverage<.6);assert.ok(patch.width>80);assert.deepEqual(patch.background,[255,255,255]);
});
test('cleanup composites only the owning mask; the immutable source and neighbouring artwork survive',()=>{
 const source=image();rect(source,40,40,6,15);rect(source,150,20,10,80,80);const snapshot=source.data.slice(),patch=prepareInkPatch(source,[35,35,55,60]),target={...source,data:source.data.slice()},modified=patch.data.slice();modified.fill(230);
 compositeInkPatch(target,patch,modified);assert.deepEqual(source.data,snapshot);
 let changed=0;for(let y=0;y<source.height;y++)for(let x=0;x<source.width;x++){const n=(y*source.width+x)*4;if(target.data[n]!==snapshot[n]){changed++;assert.ok(x>=patch.left&&x<patch.left+patch.width&&y>=patch.top&&y<patch.top+patch.height);assert.equal(patch.mask[(y-patch.top)*patch.width+x-patch.left],1);}}
 assert.ok(changed>0);assert.equal(target.data[(20*source.width+150)*4],80);
 assert.ok(prepareInkPatch(source,[-10,0,40,40]).declined);
});
test('Russian typesetting wraps a long word and keeps measured lines inside the box',()=>{
 const fit=fitComicText('Электроэнцефалография спасла положение',[0,0,150,200],(s,n)=>Array.from(s).length*n*.5,{oval:false});assert.ok(fit.fits);assert.ok(fit.lines.every(l=>Array.from(l).length*fit.fontSize*.5<=120));assert.ok(fit.lines.join('').replaceAll('-','').replaceAll(' ','').includes('Электроэнцефалография'));
});
test('Gemma stream frames split chunks, excludes thought text and observes completed tuples before EOF',()=>{
 const updates=[],stream=googleStreamAccumulator(p=>updates.push(p));
 const wire=v=>'data: '+JSON.stringify(v)+'\n\n';
 const text=wire({candidates:[{content:{parts:[{text:'private hidden thought',thought:true},{text:'[[1,"Привет!",0,0],'}]}}]})+wire({candidates:[{content:{parts:[{text:'[2,"Стой!",1,0]]'}]},finishReason:'STOP'}],usageMetadata:{thoughtsTokenCount:0}});
 for(let i=0;i<text.length;i+=7)stream.feed(text.slice(i,i+7));const result=stream.finish(text);assert.equal(updates[0].completedRegions,1);assert.equal(updates.at(-1).completedRegions,2);assert.equal(result.candidates[0].content.parts[0].text,'[[1,"Привет!",0,0],[2,"Стой!",1,0]]');assert.ok(!JSON.stringify(result).includes('hidden thought'));assert.equal(completedJsonRows('[[1,"скобка ] в тексте",0,0],'),1);
});
test('native Gemma uses the streaming endpoint, no forced JSON grammar, and strict ordinal mapping',async()=>{
 const page={id:'P10',page:10,width:100,height:100,mime:'image/webp',image:'YWJjZA==',regions:[{id:'P10_B1',bbox:[10,10,30,30]}]};
 const body=directRequest([page]);assert.equal(body.generationConfig.responseMimeType,undefined);assert.equal(body.generationConfig.thinkingConfig.thinkingLevel,'MINIMAL');assert.match(body.contents[0].parts[0].text,/tuples/);
 let sent;const raw='data: '+JSON.stringify({candidates:[{content:{parts:[{text:'[[1,"Привет!",0,0]]'}]},finishReason:'STOP'}]})+'\n\n';
 const result=await callDirectGoogle([page],{key:'fixture',transport:async request=>{sent=request;request.onChunk(raw.slice(0,20));request.onChunk(raw.slice(20));return {status:200,text:raw};}});
 assert.match(sent.url,/:streamGenerateContent\?alt=sse$/);assert.equal(result.pages[0].regions[0].uid,'P10_B1');assert.equal(result.pages[0].regions[0].ru_translation,'Привет!');assert.ok(result.diagnostics.metrics.streamChars>0);assert.equal(result.diagnostics.metrics.completedRegions,1);
});
