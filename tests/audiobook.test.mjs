import test from 'node:test';
import assert from 'node:assert/strict';
import {createClipStore,chapterReadiness,chapterAudio,wavFile,oggCrc,oggPage,oggOpusFile,opusTags,audiobookFileName,audiobookWriter,renderPhrase} from '../src/tts/audiobook.js';

const row=(text,extra={})=>({segment:text,p:0,text,voice:'Charon',style:'',rate:1,gain:1,eq:{low:0,mid:0,high:0},pause:.2,...extra});
function clip(samples,{error=null,delay=0}={}){
 const c={chunks:[],done:false,error:null,aborted:false,sampleRate:24000,provider:'gemini',wake:null};
 c.ready=new Promise(resolve=>setTimeout(()=>{if(error)c.error=error;else c.chunks.push(Float32Array.from(samples));c.done=true;resolve();},delay));
 return c;
}

test('voiced phrases are kept and reused; failed or interrupted ones are not',async()=>{
 const store=createClipStore(),a=row('Один'),b=row('Два'),c=row('Три');
 await store.track(a,'ru',clip([.5,-.5])).ready;
 const failed=store.track(b,'ru',clip([],{error:Error('quota')}));await failed.ready;
 const interrupted=clip([.1]);interrupted.ready=interrupted.ready.then(()=>{interrupted.aborted=true;});store.track(c,'ru',interrupted);await interrupted.ready;
 await new Promise(r=>setTimeout(r,0));
 assert.ok(store.has(a,'ru'));assert.ok(!store.has(b,'ru'));assert.ok(!store.has(c,'ru'));
 assert.equal(store.get(b,'ru'),null);assert.equal(store.get(c,'ru'),null);
 const again=store.get(a,'ru');
 assert.ok(again.done&&again.stored);assert.ok(Math.abs(again.chunks[0][0]-.5)<1e-4);
 // Another voice or language is another phrase.
 assert.ok(!store.has({...a,voice:'Kore'},'ru'));assert.ok(!store.has(a,'uk'));
 assert.deepEqual(chapterReadiness([a,b,c],store,'ru'),{ready:1,total:3,missing:2});
});

test('the chapter asks the engine only for missing phrases, two at a time, in reading order',async()=>{
 const store=createClipStore(),rows=['А','Б','В','Г','Д'].map(t=>row(t));
 await store.track(rows[1],'ru',clip([.2])).ready;
 // A phrase the player is still streaming is shared, not requested again.
 store.track(rows[3],'ru',clip([.4],{delay:30}));
 await new Promise(r=>setTimeout(r,0));
 const made=[];let active=0,peak=0;
 const make=r=>{made.push(r.text);active++;peak=Math.max(peak,active);const c=clip([.1],{delay:10});c.ready=c.ready.then(()=>{active--;});return c;};
 const order=[],progress=[];
 for await(const part of chapterAudio({rows,language:'ru',store,make,ahead:2,onProgress:p=>progress.push(p)}))order.push(part.row.text);
 assert.deepEqual(order,['А','Б','В','Г','Д']);
 assert.deepEqual(made,['А','В','Д']);
 assert.ok(peak<=2,'at most two requests at once: '+peak);
 assert.deepEqual(progress.at(-1),{done:5,total:5,made:3});
 assert.equal(chapterReadiness(rows,store,'ru').missing,0);
});

test('a failing phrase is asked three times with a pause, then the file stops with a clear reason',async()=>{
 const store=createClipStore();let calls=0;
 const make=()=>{calls++;return clip([],{error:Error('нет ответа')});};
 await assert.rejects(async()=>{for await(const _ of chapterAudio({rows:[row('Сбой')],language:'ru',store,make,retryDelay:1}));},/Фраза 1 не озвучилась: нет ответа/);
 assert.equal(calls,3);
});

test('a phrase that fails once is voiced on the next try',async()=>{
 const store=createClipStore();let calls=0;
 const make=()=>++calls===1?clip([],{error:Error('квота')}):clip([.3]);
 const parts=[];for await(const part of chapterAudio({rows:[row('Да.')],language:'ru',store,make,retryDelay:1}))parts.push(part);
 assert.equal(calls,2);assert.equal(parts.length,1);
});

test('plain Gemini phrases are written as they are',async()=>{
 const audio=Float32Array.from([.1,.2]);
 assert.equal(await renderPhrase({audio,sampleRate:24000},row('x'),24000,()=>{throw Error('no chain');},null),audio);
});

test('WAV carries 16-bit samples and the book and chapter names',async()=>{
 const blob=wavFile([Float32Array.from([0,1,-1])],24000,{title:'Глава 1',album:'Повелитель',artist:'Мaruyama'});
 const bytes=new Uint8Array(await blob.arrayBuffer()),view=new DataView(bytes.buffer),text=new TextDecoder().decode(bytes);
 assert.equal(text.slice(0,4),'RIFF');assert.equal(view.getUint32(4,true),bytes.length-8);assert.equal(text.slice(8,12),'WAVE');
 assert.equal(view.getUint32(24,true),24000);
 assert.ok(text.includes('INAMГлава 1')||text.includes('Глава 1'));assert.ok(text.includes('Повелитель'));
 const data=bytes.findIndex((b,i)=>b===100&&bytes[i+1]===97&&bytes[i+2]===116&&bytes[i+3]===97);assert.equal(view.getUint32(data+4,true),6);
 assert.deepEqual([view.getInt16(data+8,true),view.getInt16(data+10,true),view.getInt16(data+12,true)],[0,32767,-32768]);
});

test('Ogg pages use the Ogg CRC and Opus headers',async()=>{
 assert.equal(oggCrc(new TextEncoder().encode('123456789')),0x89a1897f);
 const page=oggPage([new Uint8Array(300)],{granule:960,serial:1,sequence:2});
 assert.deepEqual([...page.slice(26,29)],[2,255,45]);
 const tags=new TextDecoder().decode(opusTags({title:'Глава 1',album:'Книга'}));
 assert.ok(tags.startsWith('OpusTags')&&tags.includes('TITLE=Глава 1')&&tags.includes('ALBUM=Книга'));
 const file=new Uint8Array(await oggOpusFile([{data:new Uint8Array([1]),samples:960},{data:new Uint8Array([2]),samples:960}],{preSkip:312,totalSamples48:1000}).arrayBuffer());
 const pages=[];for(let at=0;at<file.length;){pages.push(at);at+=27+file[at+26]+[...file.slice(at+27,at+27+file[at+26])].reduce((n,v)=>n+v,0);}
 assert.equal(pages.length,3);
 const last=new DataView(file.buffer,pages[2]);
 assert.equal(file[pages[2]+5],4,'last page ends the stream');
 assert.equal(Number(last.getBigUint64(6,true)),1312,'granule trims the encoder padding');
});

test('without WebCodecs the writer falls back to WAV',async()=>{
 const writer=await audiobookWriter(24000,{Encoder:undefined});
 await writer.write(new Float32Array(24000));
 assert.equal(writer.ext,'wav');assert.equal(Math.round(writer.seconds),1);
 assert.equal((await writer.finish()).type,'audio/wav');
});

test('audiobook names hold the book and the chapter',()=>{
 assert.equal(audiobookFileName('Повелитель','Глава 2: Начало','opus'),'Повелитель — Глава 2 Начало.opus');
 assert.equal(audiobookFileName('Повелитель','Повелитель · Глава 2','wav'),'Повелитель · Глава 2.wav');
 assert.equal(audiobookFileName('','','wav'),'Аудиокнига.wav');
});
