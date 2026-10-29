import test from 'node:test';
import assert from 'node:assert/strict';
import {worldResults,sourceTitle} from '../src/world-search.js';
import {matchingMangaSources,sameMangaTitle} from '../src/manga-source-identity.js';

test('real MangaLib franchise alias does not merge Sakura and Charasuke into Naruto',()=>{
 const original={id:'lib:195',provider:'mangalib',providerName:'MangaLib',sourceId:'1',kind:'manga',title:'Наруто',aliases:['Наруто','Naruto'],identityTitles:['Наруто','Naruto'],year:1999,url:'https://mangalib.me/ru/195--naruto'};
 const spinOff={...original,id:'lib:96636',title:'Сакура и Чараске',aliases:['Сакура и Чараске','Naruto','Наруто'],identityTitles:['Сакура и Чараске'],year:2017,url:'https://mangalib.me/ru/96636--sakura-i-caraske'};
 const meta={...sourceTitle(original),id:'shikimori:11',sourceOnly:false,ids:{mal:'11'}};
 const values=worldResults([meta],[original,spinOff],'Наруто');
 assert.equal(values.length,2);const naruto=values.find(v=>v.ids.mal==='11');
 assert.deepEqual(naruto.sources.map(v=>v.url),[original.url]);assert.ok(!naruto.aliases.includes(spinOff.title));
 assert.equal(sameMangaTitle({...meta,year:null},{...spinOff,year:null}),false,'Canonical names also reject the franchise alias when year is unknown');
});

test('title source picker rejects unrelated popular results even when a provider ignores its query',()=>{
 const item={kind:'manga',title:'Моя геройская академия',aliases:['My Hero Academia','僕のヒーローアカデミア']};
 const rows=[{title:'Игрок максимального уровня',url:'https://example/1'},{title:'Гоблин 999 уровня',url:'https://example/2'},{title:'My Hero Academia',url:'https://example/3'},{title:'僕のヒーローアカデミア',url:'https://example/4'},{title:'My Hero Academia: Vigilantes',url:'https://example/5'}];
 assert.deepEqual(matchingMangaSources(item,rows).map(v=>v.url),['https://example/3','https://example/4']);
 assert.equal(matchingMangaSources(item,[rows[0]],{attached:true}).length,0);
 assert.equal(matchingMangaSources(item,[{url:'https://example/legacy'}],{attached:true})[0].title,item.title);
});
test('conflicting IDs, years and media kinds do not attach a source to the selected title',()=>{
 const item={title:'Dororo',kind:'manga',year:1967,ids:{mal:'1043'}};
 assert.equal(sameMangaTitle(item,{title:'Dororo',kind:'anime'}),false);
 assert.equal(sameMangaTitle(item,{title:'Dororo',year:2019}),false);
 assert.equal(sameMangaTitle(item,{title:'Dororo',ids:{mal:'99'}}),false);
 assert.equal(sameMangaTitle(item,{title:'どろろ',ids:{mal:'1043'}}),true);
});
test('source-only titles remain openable without a metadata catalog identity',()=>{
 const row={id:'suwayomi:1:9',provider:'suwayomi:1',sourceId:'1',providerName:'Source A',title:'新しい漫画',kind:'manga',url:'https://media.example/__manga/suwayomi/m/9',language:'ja'};
 const values=worldResults([], [row], '新しい');assert.equal(values.length,1);assert.equal(values[0].sourceOnly,true);assert.deepEqual(values[0].ids,{});assert.equal(values[0].sources[0].url,row.url);
});
test('metadata and exact source matches merge with every selectable source retained',()=>{
 const a=sourceTitle({id:'a',provider:'suwayomi:1',sourceId:'1',title:'One Piece',kind:'manga',url:'https://media.example/m/1'});
 const b={...a,id:'b',provider:'suwayomi:2',sourceId:'2',url:'https://media.example/m/2'};
 const meta={...a,id:'kitsu:1',provider:'kitsu',providerId:'1',sourceOnly:false,ids:{mal:'13'},year:1997};
 const values=worldResults([meta],[a,b],'One Piece',['2']);assert.equal(values.length,1);assert.equal(values[0].sourceOnly,false);assert.equal(values[0].sources.length,2);assert.deepEqual(values[0].ids,{mal:'13'});
 assert.equal(worldResults([meta],[a],'One Piece',['2']).length,0);
});


test('verified Russian source and English MangaDex aliases share the title and retain source filters',()=>{
 const lib={id:'lib',provider:'hentailib',sourceId:'4',kind:'manga',title:'Белый Кит',aliases:['Белый Кит','Moby Dick','모비딕'],identityTitles:['Белый Кит','mobidig'],year:2023,age:18,url:'https://hentailib.me/ru/187444--mobidig'};
 const dex={id:'dex',provider:'mangadex',sourceId:'2',kind:'manga',title:'Moby Dick',aliases:['Moby Dick','모비딕','Белый Кит'],year:2023,age:18,url:'https://mangadex.org/title/fixture?lang=en'};
 const rows=worldResults([],[lib,dex],'Белый кит');assert.equal(rows.length,1);assert.equal(rows[0].sources.length,2);assert.equal(rows[0].age,18);assert.equal(worldResults([],[lib,dex],'Белый кит',['2']).length,1);
});
