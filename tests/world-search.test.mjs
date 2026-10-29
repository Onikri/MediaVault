import test from 'node:test';
import assert from 'node:assert/strict';
import {worldResults,sourceTitle} from '../src/world-search.js';
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
