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
