import test from 'node:test';
import assert from 'node:assert/strict';
import {exportBundles,exportTranslation} from '../src/manga-export-options.js';
import {mangaExportJobs} from '../src/manga-export-client.js';
const entries=[{number:2,season:2,url:'b'},{number:0,season:1,url:'zero'},{number:1.5,season:1,url:'extra'},{number:1,season:3,url:'c'}];
test('chapter and volume export keep extras in order and apply volume intervals',()=>{
 assert.deepEqual(exportBundles(entries,{grouping:'volumes',volumes:'1-2'},'Тайтл').map(g=>g.entries.map(e=>e.url)),[['zero','extra'],['b']]);
 assert.deepEqual(exportBundles(entries,{grouping:'single',volumes:'1,3'},'Тайтл')[0].entries.map(e=>e.url),['zero','extra','c']);
 assert.equal(exportBundles(entries,{grouping:'chapters'},'Тайтл').length,4);
 assert.throws(()=>exportBundles(entries,{volumes:'3-1'}));
 assert.equal(exportBundles(entries,{volumes:'8'}).length,0);
});
test('only translator settings are sent; credentials and unrelated UI state stay out',()=>{
 assert.deepEqual(exportTranslation({directModel:'gemini-3.5-flash-lite',directBatchPages:3,apiKey:'secret',engine:'direct',cache:true},'Japanese'),{directModel:'gemini-3.5-flash-lite',directBatchPages:3,language:'Japanese'});
});
test('a partial Drive chapter stages only missing originals without sending its vault key',async()=>{
 const rendered=new Blob(['rendered']),original=new Blob(['original']);
 const jobs=await mangaExportJobs([{number:0,season:1}],{mode:'translate',format:'cbz',grouping:'chapters',directInput:'vision'},{name:'Drive',cache:{pages:[{page:0,blob:rendered,sourceHash:'a'.repeat(64)}],total:2,complete:false},entries:[{async:async()=>{throw Error('Cached page must not be read again')}},{async:async()=>original}],total:2,vaultKey:'never-forward'});
 assert.equal(jobs[0].body.manga.mode,'translate');assert.deepEqual(jobs[0].body.manga.chapters,[]);assert.equal(jobs[0].body.manga.pageCount,2);
 assert.equal(jobs[0].body.manga.originals[0].page,1);assert.equal(jobs[0].body.manga.cached[0].page,0);assert.equal(jobs[0].uploads[1].source,true);
 assert.equal(JSON.stringify(jobs[0].body).includes('never-forward'),false);
});
