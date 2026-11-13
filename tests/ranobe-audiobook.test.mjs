// Save window audiobook contracts: the chapter script is the reader's own
// (bible, role pass, cast → multi-voice Gemini rows) and the device save writes
// one file per chapter. Google is mocked: no real model or voice is called.
import test from 'node:test';
import assert from 'node:assert/strict';
import {chapterScript,cleanPrefs} from '../src/tts/chapter-script.js';
import {saveChapterAudiobooks} from '../src/ranobe-audiobook.js';

const bible={version:2,model:'gemini-3.5-flash-lite',tone:'тревожный',
 narrator:{gender:'m',age:'adult',timbre:'dark',voice:'низкий спокойный',geminiVoice:'Charon'},
 characters:[{name:'Аня',aliases:[],gender:'f',age:'young',importance:'main',timbre:'bright',voice:'звонкий',geminiVoice:'Leda',traits:'смелая',speech:'быстро'}]};
const paragraphs=['Он вошёл в тёмную комнату и прислушался.','— Кто здесь? — испуганно спросила Аня.'];
function google(answer){
 const calls=[];
 return {calls,service:{session:{serverVersion:71,googleGatewayVersion:5},async request(path,options){
  calls.push({path,model:options.body.model,text:JSON.stringify(options.body.request).slice(0,4000)});
  return {candidates:[{content:{parts:[{text:JSON.stringify(answer)}]}}],usageMetadata:{promptTokenCount:10,candidatesTokenCount:5}};
 }}};
}

test('the chapter script is the reader director: roles from the model, each speaker in their own voice',async()=>{
 const {calls,service}=google({lines:['1|S|Аня|fear|7'],moods:[],cast:[]});
 const direction={prefs:{geminiNarrator:'auto',pace:1,roles:true,rolesModel:'gemini-3.5-flash-lite',bibleModel:'gemini-3.5-flash-lite'},saved:{},cast:{},bible};
 const script=await chapterScript({paragraphs,bookKey:'book:test-1',chapterKey:'chapter:1',meta:{title:'Книга',language:'ru'},service,userId:'u',direction});
 assert.equal(script.analysis,'model');
 assert.ok(calls.length>=1&&calls.every(c=>c.path==='/reader/google/generate'&&c.model==='gemini-3.5-flash-lite'));
 const narration=script.rows.filter(r=>r.kind==='narration'),speech=script.rows.filter(r=>r.kind==='speech');
 assert.ok(narration.length&&speech.length,'narration and speech rows');
 assert.deepEqual([...new Set(narration.map(r=>r.voice))],['Charon']);
 assert.deepEqual([...new Set(speech.map(r=>r.voice))],['Leda']);
 assert.match(speech[0].style,/Аня/);
 assert.match(speech[0].style,/эмоция/);
 assert.equal(speech[0].text,'Кто здесь?');
});

test('the listener\'s own voice choices and narrator win, and roles off means heuristic roles without requests',async()=>{
 const {calls,service}=google({lines:[],moods:[],cast:[]});
 const direction={prefs:{geminiNarrator:'Schedar',roles:false},saved:{'Аня':{voice:'Aoede',note:'шёпотом'}},cast:{},bible};
 const script=await chapterScript({paragraphs,bookKey:'book:test-2',chapterKey:'chapter:1',meta:{title:'Книга'},service,userId:'u',direction});
 assert.equal(script.analysis,'heuristic');assert.equal(calls.length,0);
 assert.deepEqual([...new Set(script.rows.filter(r=>r.kind==='narration').map(r=>r.voice))],['Schedar']);
 const speech=script.rows.find(r=>r.kind==='speech');
 assert.equal(speech.voice,'Aoede');assert.match(speech.style,/шёпотом/);
});

test('a role pass that failed everywhere is reported, not voiced as if it were directed',async()=>{
 const service={session:{serverVersion:71},async request(){throw Object.assign(Error('Квота'),{status:429});}};
 const script=await chapterScript({paragraphs,bookKey:'book:test-3',chapterKey:'chapter:1',meta:{title:'Книга'},service,userId:'u',direction:{prefs:{},saved:{},cast:{},bible}});
 assert.equal(script.analysis,'failed');
});

test('only offered Lite/Gemma models are kept from preferences',()=>{
 assert.equal(cleanPrefs({rolesModel:'gemini-3.5-flash',bibleModel:'gemini-2.5-flash'}).rolesModel,'gemini-3.5-flash-lite');
 assert.equal(cleanPrefs({bibleModel:'gemma-4-31b-it'}).bibleModel,'gemma-4-31b-it');
});

function fakeWriter(){
 const writers=[];
 return {writers,writer:async rate=>{const w={rate,ext:'opus',samples:0,closed:false,async write(a){w.samples+=a.length;},async finish(){return new Blob([String(w.samples)]);},close(){w.closed=true;}};writers.push(w);return w;}};
}
const clip=(samples,error=null)=>{const c={chunks:error?[]:[new Float32Array(samples)],done:true,error,aborted:false,sampleRate:24000,provider:'gemini',ready:Promise.resolve()};return c;};
const row=(text,voice='Charon')=>({text,voice,style:'',rate:1,gain:1,eq:{low:0,mid:0,high:0},pause:.5,kind:'narration'});

test('every chapter becomes its own file; a chapter that does not load is skipped',async()=>{
 const {writer,writers}=fakeWriter(),saved=[],voiced=[];
 const entries=[{url:'1',title:'Глава 1'},{url:'2',title:'Глава 2'},{url:'3',title:'Глава 3'}];
 const result=await saveChapterAudiobooks({entries,book:{title:'Книга',authors:['Автор']},writer,
  prepare:async entry=>{if(entry.url==='2')throw Error('нет текста');return {title:entry.title,analysis:'model',rows:[row('А.'),row('Б.','Leda')]};},
  make:r=>{voiced.push([r.text,r.voice]);return clip(100);},save:async(blob,name)=>saved.push([name,await blob.text()])});
 assert.deepEqual(result,{files:['Книга — Глава 1.opus','Книга — Глава 3.opus'],failed:1,partial:[]});
 // 2 phrases × 100 samples + 2 pauses × 0.5 s at 24 kHz.
 assert.deepEqual(saved.map(s=>s[1]),[String(200+24000),String(200+24000)]);
 assert.deepEqual(voiced.slice(0,2),[['А.','Charon'],['Б.','Leda']]);
 assert.equal(writers.length,2);
});

test('a failed role pass stops the save and reports the chapters already saved',async()=>{
 const {writer}=fakeWriter(),entries=[{url:'1',title:'Глава 1'},{url:'2',title:'Глава 2'}];
 await assert.rejects(saveChapterAudiobooks({entries,book:{title:'Книга'},writer,save:async()=>{},make:()=>clip(10),
  prepare:async entry=>({title:entry.title,analysis:entry.url==='2'?'failed':'model',rows:[row('А.')]})}),
  error=>/квота/.test(error.message)&&error.saved.length===1);
});

test('stopping keeps finished chapters and closes the open file',async()=>{
 const {writer:base,writers}=fakeWriter(),controller=new AbortController();
 // The second chapter's file is open when the listener presses «Остановить».
 const writer=async rate=>{const w=await base(rate),write=w.write;w.write=async a=>{await write(a);if(writers.length===2)controller.abort();};return w;};
 const entries=[{url:'1',title:'Глава 1'},{url:'2',title:'Глава 2'}];
 await assert.rejects(saveChapterAudiobooks({entries,book:{title:'Книга'},writer,signal:controller.signal,save:async()=>{},
  prepare:async entry=>({title:entry.title,analysis:'model',rows:[row('А.'),row('Б.')]}),make:()=>clip(10)}),
  error=>error.name==='AbortError'&&error.saved.length===1);
 assert.equal(writers[1].closed,true);
});
