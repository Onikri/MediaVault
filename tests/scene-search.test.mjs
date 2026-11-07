import test from 'node:test';
import assert from 'node:assert/strict';
import {sceneEpisode,sceneMatches,clock,requestSceneJump,readSceneJump,consumeSceneJump,searchScene} from '../src/scene-search.js';

const row=(over={})=>({anilist:{id:21034,idMal:29787,title:{native:'ご注文はうさぎですか？？',romaji:'Gochuumon wa Usagi desu ka??',english:'Is the Order a Rabbit?? Season 2'},isAdult:false},episode:1,from:272.18,at:279.77,to:282.65,similarity:.99,video:'https://api.trace.moe/video/abc',image:'https://api.trace.moe/image/abc',...over});
function memory(){const values=new Map();return {getItem:k=>values.has(k)?values.get(k):null,setItem:(k,v)=>values.set(k,String(v)),removeItem:k=>values.delete(k)};}

test('episodes are normalised from numbers, ranges, strings and movies',()=>{
 assert.equal(sceneEpisode(3),3);assert.equal(sceneEpisode([12,13]),12);assert.equal(sceneEpisode('7'),7);assert.equal(sceneEpisode(null),1);assert.equal(sceneEpisode(''),1);
});
test('duplicate encodes collapse to one match per work and episode, best first',()=>{
 const rows=sceneMatches([row({similarity:.97}),row({similarity:.992}),row({episode:2,similarity:.6}),row({anilist:{id:1,idMal:null,title:{romaji:'Other'}},similarity:.9}),{anilist:12}]);
 assert.equal(rows.length,3);assert.equal(rows[0].similarity,.992);assert.equal(rows[0].mal,'29787');assert.equal(rows[0].time,279.77);assert.equal(rows[0].episode,1);
 assert.equal(rows.find(r=>r.anilistId===1).mal,'');
});
test('preview links from other hosts are dropped',()=>{
 const [match]=sceneMatches([row({video:'https://evil.example/x.mp4',image:'javascript:alert(1)'})]);assert.equal(match.video,'');assert.equal(match.image,'');
});
test('clock formats minutes and hours',()=>{assert.equal(clock(279.77),'4:39');assert.equal(clock(3725),'1:02:05');});
test('a scene jump is handed to the matching title only and expires',()=>{
 const storage=memory();requestSceneJump({mal:'29787',episode:4,time:100},storage);
 assert.equal(readSceneJump('1',storage),null);
 assert.deepEqual({...readSceneJump('29787',storage),at:0},{mal:'29787',episode:4,time:98,at:0});
 consumeSceneJump(storage);assert.equal(readSceneJump('29787',storage),null);
});
test('quota and unreadable images become clear Russian errors',async()=>{
 const reply=(status,body)=>async()=>({ok:status<400,status,json:async()=>body,headers:new Map()});
 await assert.rejects(searchScene('https://x.example/a.jpg',{fetcher:reply(402,{error:'quota'})}),/Лимит/);
 await assert.rejects(searchScene('https://x.example/a.jpg',{fetcher:reply(400,{error:'bad'})}),/не смог прочитать/);
 await assert.rejects(searchScene('http://x.example/a.jpg',{fetcher:reply(200,{})}),/https/);
 const ok=await searchScene('https://x.example/a.jpg',{fetcher:async url=>{assert.match(url,/anilistInfo.*url=https%3A/);return {ok:true,status:200,json:async()=>({error:'',result:[row()]}),headers:{get:()=>'42'}};}});
 assert.equal(ok.matches[0].mal,'29787');assert.equal(ok.remaining,42);
});
