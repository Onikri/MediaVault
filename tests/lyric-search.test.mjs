import test from 'node:test';
import assert from 'node:assert/strict';
import {musicIdentity,rankLyricRecord} from '../src/music-identity.js';
import {searchLrcLyrics} from '../src/lyric-search.js';
const track={title:'米津玄師 Kenshi Yonezu — IRIS OUT Kenshi Yonezu (米津玄師)',artists:['Kenshi Yonezu (米津玄師)']};
const row={id:1,trackName:'IRIS OUT',artistName:'米津玄師',albumName:'IRIS OUT / JANE DOE',duration:153,syncedLyrics:'[00:01]Fixture line\n[00:04]'};
test('mixed-script upload captions resolve to a clean title and supplied artist aliases',()=>{
 const identity=musicIdentity(track);assert.equal(identity.title,'IRIS OUT');assert.deepEqual(identity.artists,['Kenshi Yonezu','米津玄師']);
 assert.equal(musicIdentity({title:'Live and Let Die',artists:['Wings']}).title,'Live and Let Die');
 assert.equal(musicIdentity({title:'IRIS OUT (cover)',artists:['Someone']}).title,'IRIS OUT (cover)');
});
test('lyrics reject wrong recordings, reversed metadata and covers instead of picking the first search hit',()=>{
 const identity=musicIdentity(track);assert.ok(rankLyricRecord(row,identity,153)>0);
 for(const wrong of [{...row,duration:28},{...row,duration:219},{...row,artistName:'Trickle'},{...row,trackName:'IRIS OUT (live)'},{...row,trackName:'米津玄師',artistName:'IRIS OUT'},{...row,instrumental:true}])assert.equal(rankLyricRecord(wrong,identity,153),-1);
});
test('an exact miss searches native and Latin aliases, ranks duration, and keeps requests credential-free',async()=>{
 const calls=[];const result=await searchLrcLyrics(track,153,{fetcher:async(url,options)=>{calls.push({url:new URL(url),options});return new Response(JSON.stringify(url.includes('/get?')?{}:[{...row,id:3,duration:25},{...row,id:4,artistName:'Trickle'},row]),{status:url.includes('/get?')?404:200});}});
 assert.equal(result.recordId,1);assert.equal(result.precision,'line');assert.equal(result.lines.length,1);
 assert.deepEqual(calls.slice(1).map(c=>c.url.searchParams.get('artist_name')),['Kenshi Yonezu','米津玄師']);
 for(const c of calls){assert.equal(c.url.searchParams.get('track_name'),'IRIS OUT');assert.equal(c.options.credentials,'omit');assert.equal(c.options.headers,undefined);}
});
test('plain lyrics remain available without inventing synchronization',async()=>{
 const result=await searchLrcLyrics(track,153,{fetcher:async()=>new Response(JSON.stringify({...row,syncedLyrics:null,plainLyrics:'Fixture text without timestamps'}))});
 assert.equal(result.precision,'plain');assert.deepEqual(result.lines,[]);assert.equal(result.plainText,'Fixture text without timestamps');
});
test('cancelled lyric lookup cannot publish a late result',async()=>{
 const abort=new AbortController();abort.abort();await assert.rejects(searchLrcLyrics(track,153,{signal:abort.signal,fetcher:async()=>new Response(JSON.stringify(row))}),{name:'AbortError'});
});
