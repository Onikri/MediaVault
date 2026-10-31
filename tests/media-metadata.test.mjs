import test from 'node:test';
import assert from 'node:assert/strict';
import {jikan,youtubeTrailer} from '../src/media-metadata.js';
import {fillProfile,jikanProfile} from '../src/title-supplement.js';
import {searchBooks,searchMusic} from '../src/use-global-search.js';

test('public metadata shares requests and caller cancellation cannot cancel another consumer',async()=>{
 const original=globalThis.fetch,abort=new AbortController();let release,calls=0;
 globalThis.fetch=async(url,init)=>{calls++;assert.equal(init.credentials,'omit');await new Promise(r=>release=r);return {ok:true,json:async()=>({data:{mal_id:991}})};};
 try{
  const first=jikan('anime/991/full',{server:'https://fixture.test',signal:abort.signal});
  const second=jikan('anime/991/full',{server:'https://fixture.test'});
  abort.abort();release();
  await assert.rejects(first,{name:'AbortError'});assert.equal((await second).data.mal_id,991);
  await jikan('anime/991/full',{server:'https://fixture.test'});assert.equal(calls,1);
  await assert.rejects(jikan('../secret',{server:'https://fixture.test'}));assert.equal(calls,1);
 }finally{globalThis.fetch=original;}
});

test('supplement fills missing metadata without replacing Russian names or private artwork',()=>{
 const extra=jikanProfile({mal_id:20,title:'Naruto',title_english:'Naruto',type:'TV',status:'Finished Airing',episodes:220,genres:[{name:'Drama'}],images:{jpg:{large_image_url:'https://example.test/cover.jpg'}},trailer:{youtube_id:'X_SnV_SdO4k'}});
 const artwork={file:{fileId:'private'}};
 const merged=fillProfile({title:'Наруто',characters:[{id:'1'}],screenshots:[],artwork},extra);
 assert.equal(merged.title,'Наруто');assert.equal(merged.status,'Завершён');assert.equal(merged.episodes,220);
 assert.equal(merged.artwork,artwork);assert.deepEqual(merged.characters,[{id:'1'}]);assert.equal(merged.trailers.length,1);
 assert.equal(youtubeTrailer({embed_url:'https://youtube.com.evil.test/embed/X_SnV_SdO4k'}),null);
 assert.equal(youtubeTrailer({youtube_id:'bad'}),null);
});

test('book search maps real works, rejects malformed IDs and preserves cover metadata',async()=>{
 let target;const rows=await searchBooks('Миядзаки',undefined,async url=>{target=new URL(url);return {ok:true,json:async()=>({docs:[{key:'/works/OL123W',title:'Мой сосед',author_name:['Автор'],cover_i:9},{key:'../secret',title:'Invalid'}]})};});
 assert.equal(target.searchParams.get('q'),'Миядзаки');assert.equal(rows.length,1);assert.equal(rows[0].kind,'book');
 assert.equal(rows[0].sourceURL,'https://openlibrary.org/works/OL123W');assert.equal(rows[0].cover,'https://covers.openlibrary.org/b/id/9-L.jpg');
});

test('music search keeps only usable video identities and has no dependency on Drive',async()=>{
 assert.deepEqual(await searchMusic('song','',undefined),[]);
 const rows=await searchMusic('song','https://fixture.test',undefined,async()=>({ok:true,json:async()=>({results:[{id:'X_SnV_SdO4k',title:'Песня',author:'Автор'},{id:'broken',title:'Bad'}]})}));
 assert.equal(rows.length,1);assert.equal(rows[0].youtubeId,'X_SnV_SdO4k');assert.deepEqual(rows[0].artists,['Автор']);
});
