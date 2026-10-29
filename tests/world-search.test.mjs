import test from 'node:test';
import assert from 'node:assert/strict';
import {worldResults,sourceTitle} from '../src/world-search.js';
import {matchingMangaSources,sameMangaTitle} from '../src/manga-source-identity.js';

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
