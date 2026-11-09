import test from 'node:test';
import assert from 'node:assert/strict';
import JSZip from 'jszip';
import {suggestedTitle,acceptedFiles,mangaChapters,packCbz,crc32,cardProfile,malIdentity} from '../src/local-title.js';
import {openRangeArchive} from '../src/zip-reader.js';

const file=(name,bytes=[1,2,3],path='')=>Object.assign(new File([new Uint8Array(bytes)],name),{webkitRelativePath:path});

test('title name comes from the folder or a numbered file',()=>{
 assert.equal(suggestedTitle([file('a.cbz',[1],'Берсерк/Том 1/a.cbz')]),'Берсерк');
 assert.equal(suggestedTitle([file('Dune_Vol.2.epub')]),'Dune');
 assert.equal(suggestedTitle([file('Монолог фармацевта - 03.mkv')]),'Монолог фармацевта');
 assert.equal(suggestedTitle([file('Война и мир.fb2')]),'Война и мир');
});
test('only formats the reader or player opens are accepted for the kind',()=>{
 const {files,rejected}=acceptedFiles('book',[file('x.epub'),file('y.mkv'),file('z.FB2')]);
 assert.deepEqual(files.map(f=>f.name),['x.epub','z.FB2']);assert.equal(rejected.length,1);
});
test('page folders become chapters in natural order',()=>{
 const chapters=mangaChapters([file('10.jpg',[1],'Manga/Глава 2/10.jpg'),file('2.jpg',[1],'Manga/Глава 2/2.jpg'),file('1.png',[1],'Manga/Глава 10/1.png'),file('1.png',[1],'Manga/Глава 1/1.png')]);
 assert.deepEqual(chapters.map(c=>c.name),['Глава 1','Глава 2','Глава 10']);
 assert.deepEqual(chapters[1].pages.map(p=>p.name),['2.jpg','10.jpg']);
});
test('packed CBZ is a stored ZIP that both chapter readers open',async()=>{
 assert.equal(crc32(new TextEncoder().encode('123456789')),0xcbf43926);
 const pages=[file('b.jpg',[0xff,0xd8,9,9]),file('a.png',[0x89,0x50,1])];
 const cbz=await packCbz('Глава/1',pages);
 assert.equal(cbz.name,'Глава 1.cbz');
 const zip=await JSZip.loadAsync(await cbz.arrayBuffer());
 assert.deepEqual(Object.keys(zip.files),['0001.jpg','0002.png']);
 assert.deepEqual([...await zip.files['0001.jpg'].async('uint8array')],[0xff,0xd8,9,9]);
 const entries=await openRangeArchive({size:cbz.size},async(_,start,end)=>cbz.slice(start,end));
 assert.deepEqual(entries.map(e=>e.name),['0001.jpg','0002.png']);
 await assert.rejects(packCbz('empty',[]),/от 1 до 1500/);
});
test('a catalogue card becomes the stored profile and MAL identity',()=>{
 const card={provider:'shikimori',title:'Берсерк',aliases:['Berserk'],ids:{mal:'2'},cover:'https://x/y.jpg',year:1989,links:[{url:'https://shikimori.io/mangas/2'}]};
 const profile=cardProfile(card);
 assert.equal(profile.title,'Берсерк');assert.equal(profile.sourceId,'2');assert.equal(profile.sourceURL,'https://shikimori.io/mangas/2');
 assert.equal(malIdentity(card),2);assert.equal(malIdentity({ids:{openlibrary:'OL1W'}}),undefined);
});
