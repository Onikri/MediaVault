import test from 'node:test';import assert from 'node:assert/strict';
import {prepareInkPatch,compositeInkPatch,lamaInputSize,lamaInputTensors,applyLamaOutput} from '../src/manga-cleaning.js';
import {fitComicText,russianBreaks,comicInkColor,styleFont} from '../src/manga-typeset.js';
import {miganInputs,applyMiganOutput} from '../src/migan-model.js';
import {googleStreamAccumulator,completedJsonRows} from '../src/google-stream.js';

test('line boxes over SFX artwork never erase the crossing illustration or fill a rectangle',()=>{
 const source=image(240,240);rect(source,80,10,10,210,30);rect(source,110,90,5,14,0);
 const patch=prepareInkPatch(source,[65,65,165,165],{category:'sfx'});assert.ok(!patch.declined);
 const target={...source,data:source.data.slice()},replacement=patch.data.slice();replacement.fill(255);compositeInkPatch(target,patch,replacement);
 assert.equal(target.data[(100*240+85)*4],30);assert.equal(target.data[(95*240+112)*4],255);
 const solid=image(240,240);rect(solid,65,65,100,100,0);assert.ok(prepareInkPatch(solid,[65,65,165,165],{category:'sfx'}).declined);
});
import {directRequest,callDirectGoogle} from '../src/manga-direct-api.js';
const image=(width=180,height=120)=>({width,height,data:new Uint8ClampedArray(width*height*4).fill(255)});
function rect(img,x,y,w,h,color=0){for(let yy=y;yy<y+h;yy++)for(let xx=x;xx<x+w;xx++){const n=(yy*img.width+xx)*4;for(let c=0;c<3;c++)img.data[n+c]=color;}}

test('Moebius text hole includes reversed glyphs, outlines and upper AA, preserving the nearby frame',()=>{
 const source=image(220,220);rect(source,85,20,70,180,70);rect(source,100,50,12,90,255);rect(source,114,47,3,95,10);rect(source,95,15,1,185,0);
 const patch=prepareInkPatch(source,[100,50,125,145],{model:'moebius',neural:true,category:'sfx'});
 const at=(x,y)=>patch.mask[(y-patch.top)*patch.width+x-patch.left];
 assert.equal(at(100,50),1);assert.equal(at(114,47),1);assert.ok(patch.mask.some(Boolean));assert.equal(at(95,50),0);
 assert.equal(patch.maskKind,'outlined-glyphs');assert.equal(source.data[(50*220+100)*4],255);
});

test('Russian patterns never split a single letter or separate a soft sign from its consonant',()=>{
 for(const word of ['его','семья','Мэйтлин','пленено','электроэнцефалография','подъезд','пальчик'])for(const at of russianBreaks(word)){
  assert.ok(at>=2&&word.length-at>=2,word);assert.ok(!/^[ьъыЙй]/.test(word.slice(at)),word);
 }
 assert.deepEqual(russianBreaks('его'),[]);assert.deepEqual(russianBreaks('я'),[]);
 const fit=fitComicText('Его сердце всё ещё пленено…',[0,0,56,300],(s,n)=>s.length*n*.5,{oval:false});assert.ok(fit.fits);
 assert.ok(!fit.lines.some(l=>/^\p{L}-$/u.test(l)||/^\p{L}[.…!?]*$/u.test(l)),fit.lines.join('|'));
 assert.equal(fit.lines.join('').replaceAll('-','').replaceAll(' ',''),'Егосердцевсёещёпленено…');
});

test('Russian ink follows the restored bubble interior rather than dark border artwork',()=>{
 const clean=image();rect(clean,0,0,180,15,0);assert.equal(comicInkColor(clean,[0,10,180,110]).dark,false);
 rect(clean,10,20,160,90,15);assert.equal(comicInkColor(clean,[10,20,170,110]).dark,true);
 assert.equal(styleFont('handwritten_soft'),'pangolin');assert.equal(styleFont('handwritten_narrow'),'neucha');
});

test('MI-GAN uses uint8 NCHW with inverted mask polarity and commits only the requested hole',()=>{
 const source=image(4,3);rect(source,1,1,1,1,30);const before=source.data.slice(),mask=new Uint8Array(12);mask[5]=1;
 const {rgb,known}=miganInputs(source,mask);assert.equal(known[5],0);assert.equal(known[0],255);assert.equal(rgb[5],30);assert.equal(rgb[12+5],30);
 applyMiganOutput(source,mask,new Uint8Array(36).fill(180));assert.equal(source.data[5*4],180);
 for(let n=0;n<12;n++)if(!mask[n])assert.deepEqual(source.data.slice(n*4,n*4+4),before.slice(n*4,n*4+4));
 assert.throws(()=>miganInputs(source,new Uint8Array(1)));assert.throws(()=>applyMiganOutput(source,mask,new Uint8Array(3)));
});
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
 const body=directRequest([page],{model:'gemma-4-26b-a4b-it'});assert.equal(body.generationConfig.responseMimeType,undefined);assert.equal(body.generationConfig.thinkingConfig.thinkingLevel,'MINIMAL');assert.match(body.contents[0].parts[0].text,/tuples/);
 let sent;const raw='data: '+JSON.stringify({candidates:[{content:{parts:[{text:'[[1,"Привет!",0,0]]'}]},finishReason:'STOP'}]})+'\n\n';
 const result=await callDirectGoogle([page],{key:'fixture',model:'gemma-4-26b-a4b-it',transport:async request=>{sent=request;request.onChunk(raw.slice(0,20));request.onChunk(raw.slice(20));return {status:200,text:raw};}});
 assert.match(sent.url,/:streamGenerateContent\?alt=sse$/);assert.equal(result.pages[0].regions[0].uid,'P10_B1');assert.equal(result.pages[0].regions[0].ru_translation,'Привет!');assert.ok(result.diagnostics.metrics.streamChars>0);assert.equal(result.diagnostics.metrics.completedRegions,1);
});

test('LaMa dynamic ROI keeps native pixels, edge padding, mask polarity and bounded writes',()=>{
 assert.deepEqual(lamaInputSize(230,70),{width:256,height:128});assert.equal(lamaInputSize(600,70),null);
 const page=image(12,10);rect(page,3,4,2,2,0);const mask=new Uint8Array(120);mask[4*12+3]=1;
 const crop={x:-2,y:-2,w:16,h:16},input=lamaInputTensors(page,mask,crop),plane=256;
 assert.equal(input.holes[6*16+5],1);assert.equal(input.rgb[6*16+5],0);assert.equal(input.rgb[0],1);assert.equal(input.holes[0],0);
 const original=page.data.slice(),values=new Float32Array(plane*3).fill(.5);
 applyLamaOutput(page,mask,values,{crop,commit:{x:0,y:0,w:12,h:10}},new Uint8Array(120));
 assert.equal(page.data[(4*12+3)*4],128);assert.equal(page.data[0],original[0]);
 for(let y=0;y<10;y++)for(let x=0;x<12;x++)if(Math.abs(x-3)>2||Math.abs(y-4)>2)assert.equal(page.data[(y*12+x)*4],original[(y*12+x)*4]);
 assert.throws(()=>applyLamaOutput(page,mask,new Float32Array(3),{crop,commit:crop},new Uint8Array(120)));
});


test('narrow Japanese narration boxes accept Russian words with ellipses and repeated punctuation',()=>{
 const measure=(s,n)=>s.length*n*.55,box=[651.27,124.61,704.89,281.17];
 for(const text of ['сколько же прошло...','Подожди?!']){const fit=fitComicText(text,box,measure,{oval:false});assert.ok(fit.fits,text);assert.equal(fit.lines.join('').replaceAll('-','').replaceAll(' ',''),text.replaceAll(' ','').replace(/\.{3,}/g,'…'));}
});
