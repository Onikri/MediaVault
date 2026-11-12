import test from 'node:test';
import assert from 'node:assert/strict';
import JSZip from 'jszip';
import {epubFile,textFile,loadChapters,safeFileName} from '../src/book-export.js';
import {rankSources} from '../src/source-ranking.js';
import {passportVolume,runtime} from '../src/title-passport-model.js';
import {plural,counted} from '../src/title-context.js';

const chapters=[{entry:{number:1,title:'Глава 1'},title:'Глава 1',paragraphs:['Первый <абзац> & «кавычки».']},{entry:{number:2,title:'Ночь'},title:'Ночь',paragraphs:[],error:'Источник не ответил'}];

test('EPUB keeps the stored mimetype first, a navigation document and every chapter',async()=>{
 const blob=await epubFile({title:'Волчица и пряности',authors:['Исуна Хасэкура'],language:'ru',source:'RanobeHub',chapters,identifier:'mediavault:test'});
 const zip=await JSZip.loadAsync(await blob.arrayBuffer());
 const names=Object.keys(zip.files);
 assert.equal(names[0],'mimetype');
 assert.equal(await zip.file('mimetype').async('string'),'application/epub+zip');
 assert.ok(names.includes('META-INF/container.xml'));
 const opf=await zip.file('OEBPS/content.opf').async('string');
 assert.match(opf,/<dc:title>Волчица и пряности<\/dc:title>/);
 assert.match(opf,/properties="nav"/);
 assert.match(opf,/<itemref idref="c2"\/>/);
 const first=await zip.file('OEBPS/c1.xhtml').async('string');
 assert.match(first,/Первый &lt;абзац&gt; &amp; «кавычки»\./);
 assert.match(await zip.file('OEBPS/c2.xhtml').async('string'),/Глава не загрузилась: Источник не ответил/);
 assert.match(await zip.file('OEBPS/nav.xhtml').async('string'),/Глава 2\. Ночь/);
});

test('text export names a failed chapter instead of dropping it',async()=>{
 const text=await textFile({title:'Книга',authors:[],source:'Wikisource',chapters}).text();
 assert.match(text,/^Книга\nИсточник: Wikisource/);
 assert.match(text,/\[Глава не загрузилась: Источник не ответил\]/);
});

test('chapters load in order with retries and report failures',async()=>{
 const tries={};const progress=[];
 const rows=await loadChapters([{url:'a',number:1},{url:'b',number:2},{url:'c',number:3}],async entry=>{tries[entry.url]=(tries[entry.url]||0)+1;if(entry.url==='b'&&tries.b<2)throw Error('временно');if(entry.url==='c')throw Error('нет главы');return {title:entry.url,paragraphs:['x']};},{attempts:2,onProgress:p=>progress.push(p)});
 assert.deepEqual(rows.map(r=>r.title),['a','b','']);
 assert.equal(rows[2].error,'нет главы');
 assert.equal(tries.b,2);
 assert.deepEqual(progress.at(-1),{done:3,total:3,failed:1});
 assert.equal(safeFileName('Re:Zero / том 1?'),'Re Zero том 1');
});

test('sources: favourites first, then the translation closest to the total',()=>{
 const s=(provider,count)=>({provider,url:provider,count});
 const list=[s('desu',42),s('remanga',95),s('mangalib',108),s('unknown',null)];
 const order=rankSources(list,{expected:108,count:x=>x.count}).map(x=>x.provider);
 assert.deepEqual(order,['mangalib','remanga','desu','unknown']);
 assert.deepEqual(rankSources(list,{expected:108,favorites:['desu'],count:x=>x.count}).map(x=>x.provider),['desu','mangalib','remanga','unknown']);
 // Without a known total the longer list goes first.
 assert.deepEqual(rankSources(list,{count:x=>x.count}).map(x=>x.provider),['mangalib','remanga','desu','unknown']);
});

test('passport states the size of a work and what exists so far',()=>{
 const manga=passportVolume('manga',{chapters:108,volumes:12,status:'Завершён'},{chapters:95,sourceName:'ReManga'});
 assert.deepEqual(manga.figures,[[108,['глава','главы','глав']],[12,['том','тома','томов']]]);
 assert.equal(manga.note,'Переведено 95 из 108 · ReManga');
 assert.equal(manga.ruler.units,12);
 const ongoing=passportVolume('manga',{status:'Выходит'},{chapters:230,volumes:24,sourceName:'MangaLib'});
 assert.equal(ongoing.note,'Выходит · общее число глав ещё не объявлено · MangaLib');
 const series=passportVolume('tv',{seasons:2,episodes:18,episodesAired:12,duration:58,status:'Выходит'},null);
 assert.equal(series.note,'Вышло 12 из 18 · Серия ≈ 58 мин');
 assert.equal(series.ruler.filled,12/18);
 assert.equal(passportVolume('movie',{duration:122},null).lead,'2 ч 2 мин');
 assert.equal(runtime(45),'45 мин');
 assert.equal(plural(21,['глава','главы','глав']),'глава');
 assert.equal(counted(12,['том','тома','томов']),'12 томов');
});
