import test from 'node:test';
import assert from 'node:assert/strict';
import JSZip from 'jszip';
import {crc32,createPdf,createZip,imageExtension} from '../src/chapter-archive.js';
import {activityLabel,formatDuration,pagesWord,saveReaderChapter} from '../src/reader-chapter-save.js';

const webp=label=>{const text=new TextEncoder().encode(label),bytes=new Uint8Array(12+text.length);bytes.set([0x52,0x49,0x46,0x46,0,0,0,0,0x57,0x45,0x42,0x50]);bytes.set(text,12);return bytes;};
const png=label=>{const text=new TextEncoder().encode(label),bytes=new Uint8Array(8+text.length);bytes.set([0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a]);bytes.set(text,8);return bytes;};
const read=async blob=>JSZip.loadAsync(await blob.arrayBuffer(),{checkCRC32:true});
const text=async(zip,name)=>new TextDecoder().decode((await zip.file(name).async('uint8array')).slice(12));

test('stored ZIP is readable with verified CRC and keeps UTF-8 names',async()=>{
 const zip=createZip(),page=webp('страница');zip.add('001.webp',page);zip.add('глава/002.webp',new Blob([page]),crc32(page));
 const archive=await read(zip.finish());
 assert.deepEqual(Object.keys(archive.files),['001.webp','глава/002.webp']);
 assert.equal(await text(archive,'глава/002.webp'),'страница');
 assert.equal(crc32(new TextEncoder().encode('123456789')),0xcbf43926);
 assert.throws(()=>createZip().add('x.webp',new Blob([page])),/контрольная сумма/);
});

test('PDF cross-reference offsets point at their objects',async()=>{
 const pdf=createPdf();pdf.add(new Uint8Array([0xff,0xd8,1,2,3,0xff,0xd9]),600,850);pdf.add(new Blob([new Uint8Array([0xff,0xd8,9,0xff,0xd9])]),800,1200);
 const raw=new Uint8Array(await pdf.finish().arrayBuffer()),body=new TextDecoder('latin1').decode(raw);
 assert.ok(body.startsWith('%PDF-1.4'));assert.match(body,/\/Count 2/);assert.match(body,/\/MediaBox \[0 0 450 637.5\]/);
 const xref=Number(body.match(/startxref\n(\d+)/)[1]);assert.ok(body.slice(xref).startsWith('xref'));
 const offsets=[...body.slice(xref).matchAll(/^(\d{10}) 00000 n $/gm)].map(m=>Number(m[1]));
 offsets.forEach((offset,i)=>assert.ok(body.slice(offset).startsWith((i+1)+' 0 obj'),'object '+(i+1)));
});

test('magic bytes decide page extensions',()=>{
 assert.equal(imageExtension(webp('x')),'webp');assert.equal(imageExtension(png('x')),'png');assert.equal(imageExtension(new Uint8Array([0xff,0xd8,0xff])),'jpg');assert.equal(imageExtension(new Uint8Array([1,2,3,4])),'');
});

test('saves every page, retries a failure, never waits forever and reports gaps',async()=>{
 const calls=[],events=[];let failedOnce=false,recovered=false;
 const source={
  blob:async index=>new Blob([png('source '+(index+1))]),
  render:async(index,blob,signal,status)=>{
   calls.push(index);status({phase:'translating'});
   if(index===4&&!failedOnce){failedOnce=true;throw Error('Google временно занят');}
   if(index===3)return new Promise((_,reject)=>signal.addEventListener('abort',()=>reject(signal.reason),{once:true}));
   if(index===2&&!recovered)return {renderedImage:webp('partial 3'),unresolvedRegions:['P3_B1']};
   if(index===0)return {renderedImage:webp('cached 1'),cacheHit:true};
   return {renderedImage:webp('ru '+(index+1))};
  },
  retry:index=>calls.push('retry:'+index),
  recover:async(indices)=>{assert.deepEqual(indices,[2]);recovered=true;return [2];},
  state:()=>({translated:5,partial:1})
 };
 const result=await saveReaderChapter({total:6,format:'cbz',name:'Манга: том 1 / глава 2',source,stallMs:40,tick:5,onProgress:value=>events.push(value)});
 assert.equal(result.filename,'Манга том 1 глава 2.cbz');
 const archive=await read(result.blob);
 assert.deepEqual(Object.keys(archive.files),['001.webp','002.webp','003.webp','004.png','005.webp','006.webp']);
 assert.equal(await text(archive,'003.webp'),'ru 3','recovered page is rendered again');
 assert.equal(new TextDecoder().decode((await archive.file('004.png').async('uint8array')).slice(8)),'source 4','stalled page falls back to its original');
 assert.equal(await text(archive,'005.webp'),'ru 5','failed page succeeds on retry');
 assert.deepEqual(result.problems.map(p=>[p.page,p.kind]),[[4,'stalled']]);
 assert.equal(result.counts.cached,1);assert.ok(calls.includes('retry:4')&&calls.includes('retry:3'));
 assert.ok(events.some(e=>e.phase==='recover')&&events.at(-1).phase==='done');
 assert.ok(events.every(e=>e.done<=e.total));
});

test('original mode never calls the translator and partial pages stay listed without a fallback',async()=>{
 let rendered=0;
 const original=await saveReaderChapter({total:2,translate:false,format:'zip',source:{blob:async i=>new Blob([png('p'+i)]),render:async()=>{rendered++;}}});
 assert.equal(rendered,0);assert.deepEqual(Object.keys((await read(original.blob)).files),['001.png','002.png']);
 const partial=await saveReaderChapter({total:1,format:'cbz',source:{blob:async()=>new Blob([png('p')]),render:async()=>({renderedImage:webp('x'),unresolvedRegions:['a','b']})}});
 assert.deepEqual(partial.problems,[{page:1,kind:'partial',untranslated:2,message:'2 реплики без перевода'}]);
});

test('stop aborts the save',async()=>{
 const controller=new AbortController();
 const pending=saveReaderChapter({total:3,source:{blob:async()=>new Blob([png('p')]),render:(i,b,signal)=>new Promise((_,reject)=>signal.addEventListener('abort',()=>reject(signal.reason),{once:true}))},signal:controller.signal});
 setTimeout(()=>controller.abort(new DOMException('Сохранение остановлено','AbortError')),20);
 await assert.rejects(pending,{name:'AbortError'});
});

test('Russian wording helpers',()=>{
 assert.equal(pagesWord(1),'1 страница');assert.equal(pagesWord(3),'3 страницы');assert.equal(pagesWord(12),'12 страниц');assert.equal(pagesWord(21),'21 страница');
 assert.equal(formatDuration(42000),'около 40 с');assert.equal(formatDuration(130000),'около 2 мин 10 с');assert.equal(formatDuration(8*60000),'около 8 мин');
 assert.equal(activityLabel({cacheHit:true}),'Берём готовую страницу из кэша');assert.equal(activityLabel({phase:'translating'}),'Переводим в Google');
});
