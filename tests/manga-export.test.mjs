import test from 'node:test';
import assert from 'node:assert/strict';
import {exportBundles,exportTranslation} from '../src/manga-export-options.js';
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
