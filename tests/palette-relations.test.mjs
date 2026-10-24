import test from 'node:test';
import assert from 'node:assert/strict';
import {scenePalette,contrast} from '../src/palette.js';
import {wikidataRelations} from '../src/cross-media.js';
test('frame palette keeps an accessible accent for dark surfaces and ignores black frames',()=>{
 const colors=new Uint8ClampedArray(64*4);for(let i=0;i<colors.length;i+=4)colors.set([12,74,91,255],i);
 const theme=scenePalette(colors);assert.ok(contrast(theme.accent.split(' ').map(Number),[23,26,32])>=5);
 assert.ok(contrast(scenePalette(new Uint8ClampedArray(256)).accent.split(' ').map(Number),[23,26,32])>=5);
});
test('cross-media relations include only explicitly linked works and Russian labels',()=>{
 const claim=id=>({mainsnak:{datavalue:{value:{id}}}}),entity={id:'Q1',claims:{P4969:[claim('Q2'),claim('Q3'),claim('Q4')]}};
 const values={Q2:{id:'Q2',labels:{ru:{value:'Игра по аниме'}},descriptions:{ru:{value:'Компьютерная игра'}},claims:{P31:[claim('Q7889')]}},Q3:{id:'Q3',labels:{ru:{value:'Книга'}},claims:{P31:[claim('Q571')]}},Q4:{id:'Q4',labels:{en:{value:'English-only work'}},claims:{P31:[claim('Q7889')]}},Q5:{id:'Q5',labels:{ru:{value:'Не связанная игра'}},claims:{P31:[claim('Q7889')]}}};
 const related=wikidataRelations(entity,values);assert.deepEqual(related.map(r=>r.kind),['game','book']);assert.ok(related.every(r=>r.sourceURL.startsWith('https://www.wikidata.org/')));assert.equal(related.some(r=>r.id==='Q5'),false);
});
