import test,{beforeEach,afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {normalizeCatalog,mergeCatalog,matchesFilters,providerUrl,safeImage,alternateSpelling,rankCatalog,fetchCatalog,catalogProviders} from '../src/catalog.js';
import {mangaCatalogParams,mangaFacetOptions,mangaTagKey,mangaFormatLabel} from '../src/manga-catalog.js';
import {tagLabels} from '../src/taxonomy.js';
import {readFileSync} from 'node:fs';
import {setMangaPolicy,compileMangaPolicy} from '../src/manga-tag-policy.js';
const defaultPolicy=JSON.parse(readFileSync(new URL('../server/manga-tag-policy.json',import.meta.url)));
const fixturePolicy=JSON.parse(readFileSync(new URL('./fixtures/manga-tag-policy.json',import.meta.url)));
beforeEach(()=>setMangaPolicy(fixturePolicy));
afterEach(()=>setMangaPolicy(defaultPolicy));

test('source catalogue passes combined filters and preserves source ID precision',()=>{
 const params=mangaCatalogParams({query:' Garden World ',filters:{genre:'Драма',tag:'Time Travel',year:'2024',format:'Манхва',age:'adult'},language:'en',sourceIds:['990000000000000003','1'],page:3});
 assert.equal(params.get('q'),'Garden World');assert.equal(params.get('sourceIds'),'1,990000000000000003');assert.equal(params.get('offset'),'60');
 assert.equal(params.get('genre'),'Драма');assert.equal(params.get('tag'),'Time Travel');assert.equal(params.get('language'),'en');
 assert.equal(mangaFormatLabel('manhwa'),'Манхва');
});

test('frontend and backend share tag aliases, case and format filters',()=>{
 const policy=JSON.parse(readFileSync(new URL('../server/manga-tag-policy.json',import.meta.url)));
 assert.equal(compileMangaPolicy(policy).rules.size,policy.tags.length);
 assert.equal(mangaTagKey('TIME TRAVEL'),mangaTagKey(tagLabels['Time Travel']));
 const row={genres:['DRAMA'],tags:['TIME TRAVEL'],format:'manhwa',year:2024,age:18};
 assert.equal(matchesFilters(row,{genre:'Драма',tag:tagLabels['Time Travel'],format:'Манхва',year:'2024',age:'adult'}),true);
 assert.equal(matchesFilters(row,{tag:'Horror'}),false);
});

test('taxonomy facets retain provider labels and scope static terms by selected sources',()=>{
 const snapshot={sources:[{name:'Source A',domain:'a.example'},{name:'Source B',domain:'b.example'}],tags:[
  {category:'genre',label:'Drama',sources:['a.example']},{category:'tag',label:'Time Travel',sources:['b.example']}]};
 const live=[{type:'genres',original:'Драма',originalLabels:['Drama','Драма'],works:4}];
 const facets=mangaFacetOptions(snapshot,live,{sourceIds:['1'],sources:{'1':{name:'Source A'}}});
 assert.equal(facets.length,1);assert.equal(facets[0].label,'Драма');assert.equal(facets[0].works,4);
 assert.deepEqual(new Set(facets[0].originalLabels),new Set(['Drama','Драма']));
 assert.equal(mangaFacetOptions(snapshot,[],{sourceIds:['2'],sources:{'2':{name:'Source B'}}}).length,1);
});

test('metadata providers merge the same MAL title and preserve multilingual aliases and real dates',()=>{
  const shiki=normalizeCatalog('shikimori',[{id:20,russian:'Наруто',name:'Naruto',kind:'tv',aired_on:'2002-10-03',episodes:220,rating:'pg_13',image:{original:'/system/animes/original/20.jpg'},url:'/animes/20',genres:[{name:'Action',russian:'Экшен'}]}]);
  const ani=normalizeCatalog('anilist',{data:{Page:{media:[{id:20,idMal:20,title:{english:'Naruto',native:'ナルト'},synonyms:['火影忍者','나루토'],genres:['Action'],isAdult:false,startDate:{year:2002,month:10,day:3},airingSchedule:{nodes:[{episode:3,airingAt:1900000000}]}}]}}});
  const result=mergeCatalog([...shiki,...ani]);
  assert.equal(result.length,1);assert.equal(result[0].title,'Наруто');
  for(const alias of ['Naruto','Наруто','ナルト','火影忍者','나루토'])assert.ok(result[0].aliases.includes(alias));
  assert.equal(result[0].releases[0].episode,3);assert.equal(result[0].releases[0].date,new Date(1900000000*1000).toISOString());
  assert.equal(result[0].age,13);assert.equal(ani[0].age,null,'A non-adult boolean does not imply a specific certification');
  assert.equal(matchesFilters(result[0],{year:'2002',genre:'экшен'}),true);
  assert.equal(matchesFilters(result[0],{year:'2003'}),false);
});
test('partial saved titles merge with enriched catalogue rows in either order without mutation',()=>{
  const partial={id:'saved',provider:'shikimori',kind:'anime',title:'Наруто',ids:{mal:'20'},year:2002};
  const [full]=normalizeCatalog('anilist',{data:{Page:{media:[{id:1735,idMal:20,type:'ANIME',title:{english:'Naruto',native:'ナルト'},startDate:{year:2002},genres:['Action']}]}}});
  const snapshot=JSON.stringify([partial,full]);
  for(const rows of [[partial,full],[full,partial]]){
    const merged=mergeCatalog(rows);assert.equal(merged.length,1);
    assert.deepEqual(new Set(merged[0].providers),new Set(['shikimori','anilist']));
    assert.ok(merged[0].aliases.includes('Наруто'));assert.ok(merged[0].aliases.includes('Naruto'));
    assert.deepEqual(merged[0].ids,{...full.ids,...partial.ids});assert.deepEqual(merged[0].genres,['Action']);
    assert.ok(Array.isArray(merged[0].links));assert.ok(Array.isArray(merged[0].releases));
  }
  assert.equal(JSON.stringify([partial,full]),snapshot);
});

test('Kitsu data produces real covers, genres and plain descriptions; dangerous image protocols are rejected',()=>{
  const [item]=normalizeCatalog('kitsu',{data:[{type:'manga',id:'1',attributes:{canonicalTitle:'物語',titles:{en:'Story',ja_jp:'物語'},synopsis:'<b>A story</b><script>bad()</script>',posterImage:{large:'javascript:bad()'},startDate:'2020-01-01',ageRating:'R18',chapterCount:12},relationships:{genres:{data:[{type:'genres',id:'2'}]}}}],included:[{type:'genres',id:'2',attributes:{name:'Fantasy'}}]},'manga');
  assert.equal(item.cover,'');assert.ok(!item.description.includes('<'));assert.deepEqual(item.genres,['Fantasy']);assert.equal(item.age,18);assert.equal(item.chapters,12);
  assert.equal(safeImage('https://user:password@example.com/a.jpg'),'');
});
test('matching names in different years or media types do not collapse into one title',()=>{
  const records=normalizeCatalog('imdb',{d:[{id:'tt1',l:'Example',qid:'movie',y:2001},{id:'tt2',l:'Example',qid:'movie',y:2020},{id:'tt3',l:'Example',qid:'tvSeries',y:2020}]},'movie');
  assert.equal(mergeCatalog(records).length,3);
  const url=new URL(providerUrl('kitsu',{query:'나루토 火影忍者',kind:'manga'}));assert.equal(url.searchParams.get('filter[text]'),'나루토 火影忍者');
  const relay=new URL(providerUrl('imdb',{query:'Матрица',kind:'movie',server:'https://import.example.com'}));assert.equal(relay.pathname,'/metadata/imdb');assert.equal(relay.searchParams.get('q'),'Матрица');
});

test('exact multilingual aliases rank ahead of sequels without mutating provider results',()=>{
  const items=[{id:'sequel',aliases:['Naruto: Shippuden','ナルト 疾風伝']},{id:'original',aliases:['Naruto','ナルト','火影忍者','나루토']},{id:'other',aliases:['Boruto: Naruto Next Generations']}];
  for(const query of ['Naruto','ＮＡＲＵＴＯ','Наруто','ナルト','火影忍者','나루토'])assert.equal(rankCatalog(items,query)[0].id,'original',query);
  assert.equal(items[0].id,'sequel');assert.equal(alternateSpelling('Наруто'),'naruto');assert.equal(alternateSpelling('ナルト'),'');
});

test('Cyrillic search retries one alternate spelling only after an empty response',async()=>{
  const queries=[],fetcher=async url=>{
    const query=new URL(url).searchParams.get('filter[text]');queries.push(query);
    return {ok:true,json:async()=>({data:query==='naruto'?[{id:'20',attributes:{canonicalTitle:'Naruto'}}]:[]})};
  };
  const items=await fetchCatalog('kitsu',{query:'Наруто',kind:'anime'},fetcher);
  assert.deepEqual(queries,['Наруто','naruto']);assert.equal(items[0].searchSpelling,'naruto');
  assert.equal(items[0].title,'Naruto');assert.ok(!items[0].aliases.includes('Наруто'),'Do not invent a translated alias');
  const found=[];
  await fetchCatalog('kitsu',{query:'Наруто'},async url=>{found.push(url);return {ok:true,json:async()=>({data:[{id:'20',attributes:{canonicalTitle:'Наруто'}}]})};});
  assert.equal(found.length,1,'No extra request when the original query matched');
});

test('cancelled searches do not start either an original or alternate request',async()=>{
  const abort=new AbortController();abort.abort();let calls=0;
  await assert.rejects(fetchCatalog('kitsu',{query:'Наруто',signal:abort.signal},async()=>{calls++;}),{name:'AbortError'});
  assert.equal(calls,0);
  const during=new AbortController();
  await assert.rejects(fetchCatalog('kitsu',{query:'Наруто',signal:during.signal},async()=>{
    calls++;during.abort();return {ok:true,json:async()=>({data:[]})};
  }),{name:'AbortError'});
  assert.equal(calls,1);
});

test('free metadata can fall back from an unavailable relay without forwarding credentials',async()=>{
  const calls=[];
  const result=await fetchCatalog('kitsu',{query:'Naruto',kind:'anime',server:'https://import.example.com'},async(url,options)=>{
    calls.push({url,options});
    return url.startsWith('https://import.example.com')?{ok:false,status:503}:{ok:true,json:async()=>({data:[{id:'20',attributes:{canonicalTitle:'Naruto'}}]})};
  });
  assert.equal(result[0].title,'Naruto');assert.equal(calls.length,2);
  assert.equal(new URL(calls[1].url).hostname,'kitsu.io');
  assert.ok(calls.every(call=>!call.options.headers?.Authorization));
  let attempts=0;
  await assert.rejects(fetchCatalog('imdb',{query:'Matrix',kind:'movie',server:'https://import.example.com'},async()=>{attempts++;return {ok:false,status:503};}));
  assert.equal(attempts,1,'A provider without direct CORS support remains on the server');
});

// Ranobe, film and book browse (2026-11-08): answers shaped like the live APIs.
test('ranobe catalogues ask for novels and merge Russian and English bases',()=>{
  assert.deepEqual(catalogProviders('ranobe','',''),['shikimori','anilist','kitsu']);
  assert.match(providerUrl('shikimori',{kind:'ranobe'}),/\/api\/ranobe\?/);
  assert.match(providerUrl('kitsu',{kind:'ranobe'}),/filter%5Bsubtype%5D=novel/);
  assert.match(providerUrl('jikan',{kind:'ranobe',query:'overlord'}),/type=lightnovel/);
  const shiki=normalizeCatalog('shikimori',[{id:55215,name:'Utsuro no Hako to Zero no Maria',russian:'Пустая шкатулка и нулевая Мария',kind:'light_novel',image:{original:''},url:'/ranobe/55215'}],'ranobe');
  const ani=normalizeCatalog('anilist',{data:{Page:{media:[{id:1,idMal:55215,format:'NOVEL',title:{romaji:'Utsuro no Hako to Zero no Maria'},coverImage:{large:'https://example.org/a.jpg'}}]}}},'ranobe');
  assert.equal(shiki[0].kind,'ranobe');assert.equal(ani[0].kind,'ranobe');
  const merged=mergeCatalog([...shiki,...ani]);
  assert.equal(merged.length,1);assert.equal(merged[0].title,'Пустая шкатулка и нулевая Мария');
});
test('films browse Kinobox (Kinopoisk) with Russian titles and play by Kinopoisk ID',()=>{
  assert.deepEqual(catalogProviders('movie','','https://vm'),['kinobox']);
  assert.deepEqual(catalogProviders('tv','дюна','https://vm'),['kinobox','imdb','tvmaze','wikidata']);
  const rows=normalizeCatalog('kinobox',{data:{items:[{id:409424,type:'Film',title:{russian:'Дюна',original:'Dune: Part One'},gallery:{posterUrl:'https://cdn.example/get-kinopoisk-image/1/2/orig'},year:2021,rating:{kinopoisk:{value:8},imdb:{}},restriction:{age:'age12'},genres:[{name:'фантастика'}]},
    {id:1435343,type:'Series',title:{russian:'Джентльмены',original:null},gallery:{},year:2024,rating:{}}]}},'movie');
  assert.equal(rows[0].kind,'movie');assert.equal(rows[0].title,'Дюна');assert.deepEqual(rows[0].ids,{kinopoisk:'409424'});
  assert.equal(rows[0].cover,'https://cdn.example/get-kinopoisk-image/1/2/600x900');assert.equal(rows[0].age,12);assert.deepEqual(rows[0].genres,['Фантастика']);
  assert.ok(rows[0].aliases.includes('Dune: Part One'));
  assert.equal(rows[1].kind,'tv');
  const detail=normalizeCatalog('kinobox',{data:{success:true,movie:{id:7378605,type:'Film',title:{russian:'Обитель зла',original:'Resident Evil'},synopsis:'Курьер везёт посылку.',gallery:{},year:2026,rating:{}}}},'movie');
  assert.equal(detail[0].description,'Курьер везёт посылку.');
});
test('books come from Open Library editions and Fantlab, merged by title',()=>{
  assert.deepEqual(catalogProviders('book','',''),['openlibrary']);
  assert.deepEqual(catalogProviders('book','дюна',''),['openlibrary','fantlab']);
  const url=new URL(providerUrl('openlibrary',{kind:'book'}));
  assert.equal(url.searchParams.get('sort'),'readinglog');assert.match(url.searchParams.get('q'),/^language:(rus|ukr)$/);
  const ol=normalizeCatalog('openlibrary',{mvLanguage:'ru',docs:[{key:'/works/OL82563W',title:"Harry Potter and the Philosopher's Stone",author_name:['J. K. Rowling'],first_publish_year:1997,cover_i:1,editions:{docs:[{title:'Гарри Поттер и философский камень',cover_i:8267739}]}},
    {key:'/works/OL1W',title:'Rich Dad, Poor Dad',editions:{docs:[{title:'Bogatyĭ papa, bednyĭ papa'}]}}]},'book');
  assert.equal(ol[0].title,'Гарри Поттер и философский камень');assert.equal(ol[0].cover,'https://covers.openlibrary.org/b/id/8267739-L.jpg');
  assert.deepEqual(ol[0].authors,['J. K. Rowling']);assert.equal(ol[1].title,'Rich Dad, Poor Dad');
  const fl=normalizeCatalog('fantlab',{matches:[{work_id:1,rusname:'Гарри Поттер и философский камень',name:"Harry Potter and the Philosopher's Stone",all_autor_rusname:'Джоан Роулинг',year:1997,pic_edition_id:5,midmark:[8.4],name_show_im:'роман'}]},'book');
  assert.equal(fl[0].cover,'https://fantlab.ru/images/editions/big/5');assert.equal(fl[0].format,'Роман');
  assert.equal(mergeCatalog([...ol,...fl]).filter(x=>/Гарри/.test(x.title)).length,1);
});
