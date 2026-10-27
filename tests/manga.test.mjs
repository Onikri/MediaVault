import test from 'node:test';import assert from 'node:assert/strict';
import {chapterRanges,selectChapters} from '../src/manga-import.js';
import {readReading,writeReading} from '../src/reading-progress.js';
test('Russian manga selection retains zero, decimals and volume identity while rejecting another language',()=>{
 const entries=[{number:0,season:1,language:'ru',url:'zero'},{number:1.5,season:1,language:'ru',url:'extra'},{number:1.5,season:2,language:'ru',url:'other-volume'},{number:2,season:1,language:'en',url:'english'}];
 assert.deepEqual(selectChapters(entries,{selection:'0-2'}).map(e=>e.url),['zero','extra','other-volume']);assert.deepEqual(selectChapters(entries,{volume:'2',selection:'1.5'}).map(e=>e.url),['other-volume']);assert.throws(()=>chapterRanges('4-1'));assert.throws(()=>chapterRanges('1.0001'));
});
test('Reading positions are isolated by account and library and remember the exact chapter',()=>{
 const values=new Map(),storage={getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v)};const item={id:'chapter-12.5',collectionId:'story'};
 writeReading('A','library',item,3,64,storage);assert.equal(readReading('A','library',item.id,storage).page,3);assert.equal(readReading('A','library','collection:story',storage).itemId,item.id);assert.equal(readReading('B','library',item.id,storage),null);assert.equal(readReading('A','other',item.id,storage),null);
});
test('raw Japanese and Korean chapters keep their source language and never mix with translated variants',()=>{
 const entries=['ru','en','ja','ko'].flatMap(language=>[{number:0,season:1,language,url:language+'0'},{number:1.5,season:1,language,url:language+'1.5'}]);
 assert.deepEqual(selectChapters(entries,{language:'ja'}).map(v=>v.url),['ja0','ja1.5']);assert.deepEqual(selectChapters(entries,{language:'ko',selection:'1-2'}).map(v=>v.url),['ko1.5']);
});
