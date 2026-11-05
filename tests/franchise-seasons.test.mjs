import test from 'node:test';import assert from 'node:assert/strict';
import {episodeDetail,catalogueSeasonHint} from '../src/franchise-seasons.js';
import {inspectSeasonSource} from '../src/use-season-source.js';
import {minimumEpisodeDuration,voicesForCatalogue} from '../src/watch-session.js';
test('episode labels do not repeat the card heading but preserve real titles and translation notes',()=>{
 for(const title of ['Серия 2','2 серия','Эпизод 02','Episode 2','02 episode'])assert.equal(episodeDetail(title,2),undefined,title);
 assert.equal(episodeDetail('4 серия (Другой перевод: AniDUB)',4),'(Другой перевод: AniDUB)');assert.equal(episodeDetail('Серия 2 — Лекарство',2),'Лекарство');assert.equal(episodeDetail('Два лекаря',2),'Два лекаря');assert.equal(episodeDetail('Серия 20',2),'Серия 20');
});
test('a separate season catalogue entry may use source-local season 1',async()=>{
 const calls=[],service={request:async(p,o)=>{calls.push(o.body);return{seasons:[{number:1}],episodes:[{number:1,season:1,url:'https://source.test/s2/e1'}]}}};
 const value=await inspectSeasonSource(service,{sourceUrl:'https://source.test/s2',url:'https://source.test/dub'},2,new AbortController().signal);
 assert.equal(value.season,1);assert.equal(value.entries[0].url,'https://source.test/s2/e1');assert.equal(calls.length,1);assert.ok(!('season'in calls[0]),'Do not force a catalogue ordinal into the provider API');
});
test('a bundled source missing season 2 is never substituted with season 1 or 3',async()=>{
 const service={request:async()=>({seasons:[{number:1},{number:3}],episodes:[{number:1,season:1,url:'https://source.test/1'}]})};
 await assert.rejects(inspectSeasonSource(service,{sourceUrl:'https://source.test/all',url:'https://source.test/dub'},2,new AbortController().signal),/не предоставляет/);
});
test('a published bundled season URL is followed and duplicate episode numbers collapse',async()=>{
 let calls=0;const service={request:async(p,o)=>{calls++;return calls===1?{seasons:[{number:1},{number:2,url:'https://source.test/season2'}],episodes:[{number:1,season:1,url:'https://source.test/season1/e1'}]}:{seasons:[{number:2}],episodes:[{number:1,season:2,url:'https://source.test/season2/e1'},{number:1,season:2,url:'https://source.test/season2/e1'}]}}};
 const value=await inspectSeasonSource(service,{sourceUrl:'https://source.test/all',url:'https://source.test/dub'},2,new AbortController().signal);assert.equal(value.season,2);assert.equal(value.entries.length,1);assert.equal(calls,2);
});

test('catalogue season hints choose the actual numbered season before a bundled source is opened',()=>{
 assert.equal(catalogueSeasonHint({title:'Монолог фармацевта 3'}),3);assert.equal(catalogueSeasonHint({title:'Монолог фармацевта 3. Часть 2'}),3);assert.equal(catalogueSeasonHint({title:'Kusuriya no Hitorigoto 2nd Season'}),2);assert.equal(catalogueSeasonHint({title:'Монолог фармацевта'}),null);
});

test('sequel discovery keeps source-local season one but excludes first-season tracks from a bundled player',()=>{
 const sources=[{url:'standalone',seasons:[{number:1}]},{url:'bundle',seasons:[{number:1},{number:2}]}];
 const first={number:1,season:1,url:'first'},second={number:1,season:2,url:'second'};
 const voices=[{id:'libria',variants:[{sourceUrl:'standalone',episodes:[first],url:'first'}]},{id:'mixed',variants:[{sourceUrl:'bundle',episodes:[first,second],url:'first'}]},{id:'first-only-dub',variants:[{sourceUrl:'bundle',episodes:[first],url:'first'}]}];
 const result=voicesForCatalogue(voices,sources,2);
 assert.deepEqual(result.map(v=>v.id),['libria','mixed']);assert.equal(result[0].variants[0].episodes[0].season,1);assert.equal(result[1].variants[0].url,'second');assert.deepEqual(result[1].variants[0].episodes,[second]);
 assert.equal(voices[1].variants[0].episodes.length,2,'The shared catalogue cache stays unchanged');
 assert.deepEqual(voicesForCatalogue(voices,[],2).map(v=>v.id),['libria','mixed']);
 assert.deepEqual(voicesForCatalogue(voices,sources,3).map(v=>v.id),['libria']);
});

test('long catalogue works reject placeholder clips without breaking short or unknown works',()=>{
 assert.equal(minimumEpisodeDuration({duration:28}),60);
 assert.equal(minimumEpisodeDuration({duration:5}),60);
 assert.equal(minimumEpisodeDuration({duration:2}),0);
 assert.equal(minimumEpisodeDuration({}),0);
});
