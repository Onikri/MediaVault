import test from 'node:test';
import assert from 'node:assert/strict';
import {readWatch,saveWatch,orderedVoices,variantsFor,onlineEpisodeId} from '../src/watch-session.js';
import {animeSeason,browseHref,browseRoute,voiceEpisodeCount} from '../src/anime-navigation.js';
test('facet routes preserve Cyrillic labels and special studio characters without executable URLs',()=>{
 const href=browseHref('studio','','34','Studio & Name');assert.ok(href.startsWith('#'));
 assert.deepEqual(browseRoute(href),{browse:'studio',identity:'34',label:'Studio & Name'});
 assert.equal(browseRoute('#browse=url&value=javascript:alert(1)'),null);
});
test('calendar seasons follow the actual first release date and reject missing or invalid months',()=>{
 assert.deepEqual(animeSeason('2024-10-04'),{value:'fall_2024',label:'Осень 2024'});
 assert.equal(animeSeason('2024'),null);assert.equal(animeSeason('2024-99-01'),null);
});
test('voice episode counts deduplicate sources within the selected season',()=>{
 const v={variants:[{episodes:[{number:1,season:1},{number:2,season:1}]},{episodes:[{number:1,season:1},{number:1,season:2},{number:'unknown'}]}]};
 assert.equal(voiceEpisodeCount(v,1),2);assert.equal(voiceEpisodeCount(v,2),1);
});
test('online resume keeps logical episode and voice across changing source tokens, isolated by account',()=>{
 const entries=new Map(),storage={getItem:k=>entries.get(k),setItem:(k,v)=>entries.set(k,v)};
 saveWatch('one','57334',{voiceId:'anidub',episode:7,season:1},storage);
 saveWatch('one','57334',{audioId:'libria'},storage);
 assert.equal(readWatch('one','57334',storage).episode,7);assert.equal(readWatch('one','57334',storage).voiceId,'anidub');
 assert.deepEqual(readWatch('two','57334',storage),{});
 assert.equal(onlineEpisodeId('57334',1,7),'online:57334:s1:e7');assert.ok(![...entries.values()].some(s=>s.includes('http')));
});
test('preference ordering uses observed personal choices without invented public popularity',()=>{
 const voices=[{id:'a',name:'AniDub',language:'ru'},{id:'b',name:'Libria',language:'ru'},{id:'en',name:'English',language:'en'}];
 assert.deepEqual(orderedVoices(voices,{usage:{b:3}}).map(v=>v.id),['b','a']);
 assert.deepEqual(orderedVoices(voices,{voiceId:'a',usage:{b:3}}).map(v=>v.id),['a','b']);
});
test('source fallback keeps the chosen studio and exact episode',()=>{
 const voice={variants:[{id:'x',player:'Kodik',episodes:[{number:1}]},{id:'y',player:'Alloha',episodes:[{number:7}]},{id:'z',player:'Kodik',episodes:[{number:7}]}]};
 assert.deepEqual(variantsFor(voice,7,new Set(['y'])).map(v=>v.id),['z','x']);
});

import {bestQualityRow,qualityHeights,streamBufferPolicy,contiguousBufferEnd} from '../src/watch-quality.js';
test('quality matching compares real mirrors and keeps chosen audio separate from best video',()=>{
 const rows=[{voiceId:'a',variant:{id:'kodik'},qualities:[720,480]},{voiceId:'a',variant:{id:'alloha'},qualities:[1440,1080,480]},{voiceId:'sub',variant:{id:'raw'},qualities:[2160,1080]}];
 assert.equal(bestQualityRow(rows,{voiceId:'a'}).variant.id,'alloha');
 assert.equal(bestQualityRow(rows,{voiceId:'a',quality:'720'}).variant.id,'kodik');
 assert.equal(bestQualityRow(rows,{voiceId:'a',anyVoice:true}).voiceId,'sub');
 assert.equal(bestQualityRow(rows,{voiceId:'a',quality:'2160'}),undefined);
 assert.equal(bestQualityRow(rows,{voiceId:'a',failed:new Set(['alloha'])}).variant.id,'kodik');
 assert.deepEqual(qualityHeights(rows),[2160,1440,1080,720,480]);
});
test('ahead buffering respects data saver, device memory, preview isolation and independent audio',()=>{
 const normal=streamBufferPolicy(),small=streamBufferPolicy({memory:4}),saver=streamBufferPolicy({saveData:true}),preview=streamBufferPolicy({preview:true}),audio=streamBufferPolicy({audioOnly:true});
 assert.equal(normal.maxBufferLength,75);assert.equal(normal.maxMaxBufferLength,90);assert.equal(normal.maxBufferSize,64*1024*1024);
 assert.equal(small.maxBufferLength,40);assert.ok(saver.maxMaxBufferLength<=30);assert.equal(preview.maxMaxBufferLength,12);assert.equal(preview.backBufferLength,0);
 assert.equal(audio.maxBufferLength,75);assert.ok(audio.maxBufferSize<=40e6);assert.ok(normal.abrBandWidthUpFactor<normal.abrBandWidthFactor);
});
test('buffer display counts the current continuous range rather than disconnected future seek ranges',()=>{
 const ranges={length:2,start:i=>[0,100][i],end:i=>[30,130][i]};
 assert.equal(contiguousBufferEnd(ranges,12),30);assert.equal(contiguousBufferEnd(ranges,50),50);assert.equal(contiguousBufferEnd(ranges,110),130);
});

test('fast playback prefers a direct mirror and restores a renamed studio preference',()=>{
 const voice={variants:[{id:'browser',player:'Alloha',episodes:[{number:1}]},{id:'direct',player:'Kodik',episodes:[]}]};
 assert.equal(variantsFor(voice,1)[0].id,'direct');
 assert.equal(orderedVoices([{id:'other',name:'А'},{id:'new',aliases:['old'],name:'Б'}],{voiceId:'old'})[0].id,'new');
});

test('preview identity isolates season, episode, public source and account',async()=>{
 const {episodePreviewKey:key}=await import('../src/watch-session.js');
 const base=key('16498',1,2,'kodik-17','user-a');
 for(const other of [key('16498',2,2,'kodik-17','user-a'),key('16498',1,3,'kodik-17','user-a'),key('16498',1,2,'alloha-17','user-a'),key('16498',1,2,'kodik-17','user-b')])assert.notEqual(base,other);
});

test('Alloha is playback-only; previews borrow the same episode from Kodik', async () => {
  const {isAllohaVariant, previewSource, previewEntry} = await import('../src/watch-session.js');
  const alloha = {id: 'yani', player: 'Alloha', url: 'https://alloha.yani.tv/?translation=66', sourceUrl: 'https://ru.yummyani.me/catalog/item/x'};
  const dynamic = {id: 'dyn', player: 'Плеер', url: 'https://abc.stravers.live/?e=1', sourceUrl: 'https://site.example/t'};
  const kodikSubs = {id: 'ks', player: 'Kodik', kind: 'subtitles', url: 'https://kodik.info/serial/1/a/720p', sourceUrl: 'https://site.example/t'};
  const kodik = {id: 'kv', player: 'Kodik', url: 'https://kodik.info/serial/1/b/720p', sourceUrl: 'https://site.example/t'};
  const other = {id: 'sib', player: 'Sibnet', url: 'https://video.sibnet.ru/shell.php?videoid=1', sourceUrl: 'https://site.example/t'};
  assert.equal(isAllohaVariant(alloha), true);
  assert.equal(isAllohaVariant(dynamic), true);
  assert.equal(isAllohaVariant(kodik), false);
  const voices = [{id: 'dub', variants: [alloha, other]}, {id: 'subs', kind: 'subtitles', variants: [kodikSubs]}, {id: 'anistar', variants: [kodik, dynamic]}];
  assert.equal(previewSource(voices, kodik), kodik, 'non-Alloha players keep their own previews');
  assert.equal(previewSource(voices, alloha), kodik, 'voiced Kodik before burned-in subtitles and other players');
  assert.equal(previewSource([{id: 'dub', variants: [alloha, other]}], alloha), other);
  assert.equal(previewSource([{id: 'dub', variants: [alloha, dynamic]}], alloha), null, 'never another Alloha mirror');
  assert.deepEqual(previewEntry([{number: 1, url: 'k1'}, {number: 2, url: 'k2'}], {number: '2', url: 'a2'}), {number: 2, url: 'k2'});
  assert.equal(previewEntry([{number: 1, url: 'k1'}], {number: 5}), null);
});

test('Ukrainian dubs are kept, filtered and ordered by content language',()=>{
 const voices=[{id:'ru',name:'AniLibria',language:'ru'},{id:'uk',name:'FanVoxUA',language:'uk'},{id:'en',name:'English',language:'en'}];
 assert.deepEqual(orderedVoices(voices).map(v=>v.id),['ru','uk']);
 assert.deepEqual(orderedVoices(voices,{},{prefer:'uk'}).map(v=>v.id),['uk','ru']);
 assert.deepEqual(orderedVoices(voices,{},{filter:'uk',prefer:'uk'}).map(v=>v.id),['uk']);
 assert.deepEqual(orderedVoices(voices,{},{filter:'ru'}).map(v=>v.id),['ru']);
});
