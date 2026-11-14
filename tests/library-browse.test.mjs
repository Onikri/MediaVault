import test from 'node:test';
import assert from 'node:assert/strict';
import {browseQuery,fetchBrowsePage} from '../src/catalog.js';
import {titleSlug} from '../src/title-route.js';
import {tabTitle,kindIcon} from '../src/tab-identity.js';

test('browse pages are one ordered AniList list with a stable tie-break', ()=>{
 const one=browseQuery({kind:'anime',page:1,perPage:24,sort:'score'}),five=browseQuery({kind:'anime',page:5,perPage:24,sort:'score'});
 assert.match(one.query,/sort:\[\$sort,ID\]/);
 assert.equal(one.variables.sort,'SCORE_DESC');
 assert.deepEqual([one.variables.page,five.variables.page],[1,5]);
 assert.equal(five.variables.perPage,24);
 assert.match(one.query,/pageInfo\{lastPage total\}/);
});

test('sorts, kinds and filters map onto AniList arguments', ()=>{
 const manga=browseQuery({kind:'manga',sort:'length',year:'2019'});
 assert.equal(manga.variables.type,'MANGA');assert.equal(manga.variables.sort,'CHAPTERS_DESC');
 assert.deepEqual(manga.variables.notFormat,['NOVEL']);
 assert.deepEqual([manga.variables.from,manga.variables.to],[20190000,20200000]);
 const ranobe=browseQuery({kind:'ranobe',sort:'new'});
 assert.deepEqual(ranobe.variables.format,['NOVEL']);
 assert.equal(ranobe.variables.dated,10000000,'dated sorts skip undated announcements');
 const anime=browseQuery({kind:'anime',format:'movie',genre:'Action',year:'2021'});
 assert.deepEqual(anime.variables.format,['MOVIE']);assert.deepEqual(anime.variables.genres,['Action']);assert.equal(anime.variables.year,2021);
});

test('a browse page keeps AniList order and only borrows Russian names', async ()=>{
 const media=[1,2,3].map(id=>({id,idMal:100+id,title:{romaji:'Title '+id},genres:[],tags:[],format:'TV'}));
 const calls=[];
 const fetcher=async(url,init)=>{calls.push(String(url));
  if(String(url).includes('anilist'))return {ok:true,json:async()=>({data:{Page:{pageInfo:{lastPage:7,total:150},media}}})};
  return {ok:true,json:async()=>[{id:103,name:'Title 3',russian:'Третий'},{id:101,name:'Title 1',russian:'Первый'},{id:999,name:'Other',russian:'Чужой'}]};};
 const items=await fetchBrowsePage({kind:'anime',page:2,perPage:3},fetcher);
 assert.deepEqual(items.map(i=>i.title),['Первый','Title 2','Третий']);
 assert.equal(items.pages,7);
 assert.match(calls[1],/ids=101%2C102%2C103/);
});

test('titles get a readable address name and their own tab', ()=>{
 assert.equal(titleSlug('Король меча!'),'korol-mecha');
 assert.equal(titleSlug('Пикник в Потусторонье'),'piknik-v-potustorone');
 assert.equal(tabTitle('Пикник в Потусторонье','anime'),'Пикник в Потусторонье — Аниме · MediaVault');
 assert.equal(tabTitle('','manga'),'Манга · MediaVault');
 assert.match(kindIcon('manga'),/^data:image\/svg\+xml,/);
 assert.equal(kindIcon('all'),null);
});
