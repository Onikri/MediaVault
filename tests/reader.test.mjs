import {translationFont} from '../src/translation-layout.js';
import test from 'node:test';import assert from 'node:assert/strict';import JSZip from 'jszip';
import {openRangeArchive,openChapter} from '../src/zip-reader.js';import{sanitize,readSettings,saveSettings}from'../src/reader-settings.js';import{toggleTrack,tracks,spotifySearch,youtubeSearch,musicIdentityFor}from'../src/music-library.js';
const storage=()=>{const m=new Map();return{getItem:k=>m.get(k),setItem:(k,v)=>m.set(k,v)}};

test('online page distinguishes expired sessions from safe source errors and rejects oversized upstream bodies',async t=>{
 const page=async response=>{t.mock.method(globalThis,'fetch',async()=>response);const [p]=await openChapter({onlinePages:['https://reader.test/page']});try{return await p.async();}finally{t.mock.restoreAll();}};
 await assert.rejects(page(Response.json({detail:'На сервере источников заполнен кэш страниц.'},{status:422})),/заполнен кэш/);
 await assert.rejects(page(new Response('',{status:410})),/просмотр завершён/);
 await assert.rejects(page(new Response('No space left on device',{status:500})),/HTTP 500/);
 await assert.rejects(page(Response.json({detail:'<script>private upstream</script>'},{status:422})),/^Error: Не удалось загрузить страницу/);
 await assert.rejects(page(Response.json({detail:'x'.repeat(10000)},{status:422})),/^Error: Не удалось загрузить страницу/);
});
test('CBZ opens the directory and visible page without reading a whole chapter',async()=>{const zip=new JSZip();zip.file('001.png',new Uint8Array(6*1024*1024));zip.file('002.png',new Uint8Array([1,2,3,4]));const blob=await zip.generateAsync({type:'blob',compression:'STORE'});let total=0;const read=async(item,a,b)=>{total+=b-a;return blob.slice(a,b);};const pages=await openRangeArchive({size:blob.size},read);assert.equal(pages.length,2);assert.deepEqual(new Uint8Array(await(await pages[1].async('blob')).arrayBuffer()),new Uint8Array([1,2,3,4]));assert.ok(total<100000,'only directory, header and selected image fetched');});
test('malformed and compressed archives use the compatible loader instead of trusting offsets',async()=>{await assert.rejects(openRangeArchive({size:100},async()=>new Blob([new Uint8Array(100)])));const zip=new JSZip();zip.file('1.png','compress me');const blob=await zip.generateAsync({type:'blob',compression:'DEFLATE'});await assert.rejects(openRangeArchive({size:blob.size},async(i,a,b)=>blob.slice(a,b)),/сжатого CBZ/);});
test('reader preferences and music library are isolated by account',()=>{const s=storage();saveSettings('A',{mode:'scroll',preload:4,translate:true},s);assert.equal(readSettings('A',s).mode,'scroll');assert.equal(readSettings('B',s).translate,false);assert.equal(sanitize({width:100000,preload:100}).width,900);const t={id:'theme:1',title:'Song',artists:['Artist']};toggleTrack('A',t,s);assert.equal(tracks('A',s).length,1);assert.equal(tracks('B',s).length,0);assert.equal(toggleTrack('A',t,s).length,0);assert.ok(spotifySearch(t).startsWith('https://open.spotify.com/search/'));assert.ok(youtubeSearch(t).startsWith('https://music.youtube.com/'));});

test('movie numeric IDs never become unrelated anime music',()=>{assert.equal(musicIdentityFor({section:'movie',metadataId:57334}),null);assert.equal(musicIdentityFor({section:'anime',metadataId:57334}),'57334');assert.equal(musicIdentityFor({section:'movie',collectionId:'film'},{storage:{collections:[{id:'film',metadata:{ids:{mal:'199'}}}]}}),'199');});

test('translation text adapts to the speech bubble and reader size',()=>{const r={w:.16,h:.1,text:'Я не верю в НЛО и инопланетян.'};const small=translationFont(r,{width:390,height:585}),large=translationFont(r,{width:1000,height:1500});assert.ok(small>=9&&small<large);assert.ok(large<=18);assert.ok(translationFont({...r,text:'длинный перевод '.repeat(100)},{width:390,height:585})>=9);});

test('service diagnostics are off by default and saved per reader profile',()=>{
 const s=storage();assert.equal(sanitize().diagnostics,false);saveSettings('A',{diagnostics:true},s,'manga');
 assert.equal(readSettings('A',s,{},'manga').diagnostics,true);assert.equal(readSettings('A',s,{},'webtoon').diagnostics,false);assert.equal(readSettings('B',s,{},'manga').diagnostics,false);
});


import {ChapterLease} from '../src/reader-chapter-lease.js';
test('a prefetched Drive range archive transfers its lifetime when its chapter becomes active',async()=>{
 const zip=new JSZip();zip.file('padding.bin',new Uint8Array(100000));zip.file('1.png',new Uint8Array([1,2,3]));zip.file('2.png',new Uint8Array([4,5,6]));const blob=await zip.generateAsync({type:'blob',compression:'STORE'}),item={id:'21',size:blob.size,chunks:[{}]};let reads=0;
 const readRange=async(item,a,b,{signal})=>{signal.throwIfAborted();reads++;return blob.slice(a,b);};
 const prefetch=new ChapterLease(item.id,'account:drive',signal=>openChapter(item,()=>assert.fail('No whole-chapter fallback expected'),readRange,signal));await prefetch.promise;
 prefetch.releasePrefetch('21');const active=new AbortController(),pages=await prefetch.adopt(active.signal);await Promise.resolve();assert.equal(prefetch.controller.signal.aborted,false);
 assert.deepEqual([...new Uint8Array(await(await pages[0].async()).arrayBuffer())],[1,2,3]);assert.ok(reads>=3);
 active.abort();await assert.rejects(pages[1].async(),e=>e.name==='AbortError');assert.equal(prefetch.controller.signal.aborted,true);
});

test('cancelled, unused and wrong-account chapter prefetches cannot be adopted',async()=>{
 const lease=new ChapterLease('21','account:A',async()=>[]);assert.equal(lease.matches('21','account:B'),false);lease.releasePrefetch('20');assert.equal(lease.matches('21','account:A'),false);assert.throws(()=>lease.adopt(new AbortController().signal),e=>e.name==='AbortError');
 const orphan=new ChapterLease('21','account:A',async()=>[]);orphan.releasePrefetch('21');await Promise.resolve();assert.equal(orphan.controller.signal.aborted,true);
});
