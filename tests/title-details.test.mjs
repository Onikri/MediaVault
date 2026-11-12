import test from 'node:test';
import assert from 'node:assert/strict';
import {alternativeTitleNames,mergeTitleIdentity,profileCatalogFields,preserveCatalogFacts,mangaPublication,publicationFacts} from '../src/title-details.js';
import {normalizeCatalog} from '../src/catalog.js';
import {importedProfile,translate} from '../src/title-metadata.js';

test('Russian and original aliases survive catalogue, dossier and source identity updates',()=>{
 const item=normalizeCatalog('anilist',{data:{Media:{id:104,title:{romaji:'Yotsuba to!',english:'Yotsuba&!',native:'よつばと!'},synonyms:['Yotsubato!'],status:'RELEASING',chapters:120,volumes:16,idMal:104}}},'manga')[0];
 const identity=mergeTitleIdentity(item,{title:'Ёцуба и!',aliases:['Yotsuba&!','ЁЦУБА И!']});
 assert.equal(identity.title,'Ёцуба и!');assert.equal(identity.titles.ru,'Ёцуба и!');assert.equal(identity.id,item.id);assert.deepEqual(identity.ids,item.ids);
 assert.deepEqual(alternativeTitleNames(identity),['Yotsuba&!','よつばと!','Yotsuba to!']);
 const profile=importedProfile(identity);
 assert.ok(profile.aliases.includes('Ёцуба и!'));assert.equal(profile.chapters,120);assert.equal(profile.volumes,16);assert.equal(profile.status,'Выходит');
 const kept=preserveCatalogFacts(item,{chapters:null,volumes:0,aliases:[]});
 assert.equal(kept.chapters,120);assert.equal(kept.volumes,0);assert.deepEqual(kept.aliases,profileCatalogFields(item).aliases);
 assert.equal(translate('current'),'Выходит');assert.equal(translate('NOT_YET_RELEASED'),'Анонсирован');
});

test('ongoing episode facts separate planned totals, published episodes and future schedules',()=>{
 const now=Date.parse('2026-11-12T00:00:00Z');
 assert.deepEqual(publicationFacts({status:'Выходит',episodes:24,episodesAired:5},'anime',now),[['Выпущено серий','5'],['Последняя серия','5'],['Серий запланировано','24']]);
 assert.deepEqual(publicationFacts({status:'ongoing',episodes:null,episodesAired:0},'anime',now),[['Выпущено серий','0']]);
 assert.deepEqual(publicationFacts({status:'RELEASING',releases:[{episode:5,date:'2026-11-01'},{episode:6,date:'2026-12-01'},{episode:10,season:2,date:'2026-11-01'}]},'anime',now),[['Выпущено серий','5'],['Последняя серия','5']]);
 assert.deepEqual(publicationFacts({status:'Завершён',episodes:12},'anime',now),[['Эпизоды','12']]);
 assert.deepEqual(publicationFacts({status:'Выходит'},'anime',now),[]);
});

test('source chapter numbers and counts are deduplicated without replacing catalogue totals',()=>{
 const data={readable:true,language:'ru',providerName:'MangaLib',truncated:true,episodes:[{number:1,season:1,url:'https://example.test/a'},{number:1,season:1,url:'https://example.test/b'},{number:2.5,season:1,url:'https://example.test/c'},{number:'invalid',url:'https://example.test/no'},{number:3}]};
 assert.equal(mangaPublication({...data,readable:false}),null);
 const sourcePublication=mangaPublication(data);
 assert.equal(sourcePublication.count,2);assert.equal(sourcePublication.latest,2.5);
 assert.deepEqual(publicationFacts({chapters:120,volumes:16,sourcePublication},'manga'),[['Главы в каталоге','120'],['Тома','16'],['Главы в источнике','не менее 2 · Русский'],['Последняя глава в источнике','2.5']]);
 assert.deepEqual(publicationFacts({},'manga'),[]);
});
