import test from 'node:test';import assert from 'node:assert/strict';
import{depthInput,depthSize,normalizeDepth,shadowCutoff,videoRect,depthSurface}from'../src/pause-depth-model.js';import{parseCharacters}from'../src/character-recognition.js';
import{pauseContext,localizeCharacters,characterCropBox,characterRoster}from'../src/pause-character-context.js';
import{characterVerificationRequest,verifiedCharacters,CHARACTER_MODEL}from'../src/pause-character-gemini.js';

test('Russian catalogue aliases resolve Japanese and reordered Latin names without merging distinct characters',()=>{
 const roster=[{nameRu:'Эдвард Элрик',aliases:['エドワード・エルリック','Elric, Edward']},{nameRu:'Альфонс Элрик',aliases:['Alphonse Elric']}];
 const values=localizeCharacters([{id:'0',candidates:[{name:'エドワード・エルリック'}],uncertain:false},{id:'1',candidates:[{name:'Edward Elric'},{name:'Alphonse Elric'}],uncertain:true}],roster);
 assert.equal(values[0].nameRu,'Эдвард Элрик');assert.equal(values[0].verification,'catalog');assert.equal(values[1].nameRu,'');assert.equal(values[1].verification,'needed');
 const context=pauseContext({episode:3,season:2,section:'anime',collectionId:'a'},{storage:{collections:[{id:'a',metadata:{ids:{mal:5114}}}]}},'Стальной алхимик');assert.equal(context.malId,'5114');assert.equal(context.season,'2');assert.equal(context.episode,'3');
});
test('Character roster joins native AniList aliases to Russian Shikimori names',async()=>{
 const original=globalThis.fetch;
 globalThis.fetch=async url=>({ok:true,json:async()=>String(url).includes('anilist')?{data:{Media:{characters:{nodes:[{name:{full:'Test Character',native:'試験人物',alternative:[]}}]}}}}:[{character:{id:11,name:'Test Character',russian:'Тестовый персонаж'}}]});
 try{const roster=await characterRoster({malId:'9876543'},{server:'https://fixture.test'});assert.equal(localizeCharacters([{candidates:[{name:'試験人物'}]}],roster)[0].nameRu,'Тестовый персонаж');}finally{globalThis.fetch=original;}
});
test('Gemini verifier sends labelled crops, episode context and candidates, and rejects non-Russian or duplicated answers',()=>{
 const box=characterCropBox([.8,.7,1,1],1000,500);assert.ok(box.left>=0&&box.top>=0&&box.left+box.width<=1000&&box.top+box.height<=500);
 const request=characterVerificationRequest({title:'Алхимик',season:2,episode:4,timecode:'00:05:12',timeSeconds:312,aliases:['Fullmetal Alchemist']},[{id:'0',face:[.2,.1,.8,.5],image:'jpeg-data',candidates:[{name:'Alphonse',work:'FMA'}]}]);
 assert.equal(CHARACTER_MODEL,'gemini-3.5-flash-lite');assert.equal(request.contents[0].parts[2].inlineData.data,'jpeg-data');assert.ok(request.contents[0].parts[0].text.includes('00:05:12'));assert.ok(request.contents[0].parts[1].text.includes('Alphonse'));assert.ok(request.systemInstruction.parts[0].text.includes('unresolved'));
 const values=[{id:'0',uncertain:true,candidates:[]}],answer=rows=>({candidates:[{content:{parts:[{text:JSON.stringify({characters:rows})}]}}]});
 assert.equal(verifiedCharacters(values,answer([{id:'0',status:'resolved',nameRu:'Альфонс Элрик'}]))[0].nameRu,'Альфонс Элрик');
 assert.equal(verifiedCharacters([{...values[0],nameRu:'Эдвард Элрик',uncertain:false}],answer([{id:'0',status:'resolved',nameRu:'Другой'}]))[0].nameRu,'Эдвард Элрик');
 assert.equal(verifiedCharacters(values,answer([{id:'0',status:'resolved',nameRu:'Alphonse'}]))[0].verification,'unresolved');
 assert.equal(verifiedCharacters(values,answer([{id:'0',status:'unresolved',nameRu:''}]))[0].uncertain,true);
 assert.equal(verifiedCharacters(values,answer([{id:'0',status:'resolved',nameRu:'Один'},{id:'0',status:'resolved',nameRu:'Другой'}]))[0].nameRu,undefined);
});
test('Depth Anything uses planar normalized RGB, patch multiples and full depth range',()=>{const s=depthSize(1920,1080);assert.equal(s.width%14,0);assert.equal(s.height%14,0);assert.equal(Math.max(s.width,s.height),392);const v=depthInput(new Uint8Array([255,0,128,255]),1,1);assert.ok(Math.abs(v[0]-(1-.485)/.229)<1e-5);assert.ok(Math.abs(v[1]+.456/.224)<1e-5);assert.equal(normalizeDepth(Float32Array.from({length:100},(_,i)=>i))[0],0);assert.equal(normalizeDepth(Float32Array.from({length:100},(_,i)=>i))[99],255);assert.throws(()=>normalizeDepth(new Float32Array(20).fill(1)));});
test('Breathing is periodic and letterboxed coordinates stay on the original picture',()=>{assert.ok(Math.abs(shadowCutoff(0)-shadowCutoff(12))<1e-10);assert.ok(shadowCutoff(6)>shadowCutoff(0));assert.deepEqual(videoRect(800,450,400,400),{left:175,top:0,width:450,height:450});});
test('Depth-connected highlighting does not cross an unrelated far-depth surface',()=>{const depth=new Uint8Array(100*100);for(let y=0;y<100;y++)for(let x=55;x<100;x++)depth[y*100+x]=220;const mask=depthSurface(depth,100,100,[.6,.2,.8,.4]);assert.ok(mask[30*100+70]>0);assert.equal(mask[30*100+30],0);assert.equal(mask[30*100+54],0);});
test('Recognition bounds and ambiguous candidates are validated without invented confidence',()=>{const r=parseCharacters({code:0,data:[{box:[.1,.2,.4,.6],not_confident:false,character:[{character:'A',work:'One'},{character:'B',work:'Two'}]},{box:[NaN,0,1,1],character:[{character:'Bad'}]}]});assert.equal(r.length,1);assert.equal(r[0].uncertain,true);assert.equal(r[0].candidates[0].name,'A');assert.throws(()=>parseCharacters({code:17728,data:[]}));});
