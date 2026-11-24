import test,{beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {setMangaPolicy} from '../src/manga-tag-policy.js';
import {matchesFilters} from '../src/catalog.js';
import {taxonomyFacts,formatOptions,hasCatalogFilters,readableCatalogLabel,classifyLabel} from '../src/catalog-taxonomy.js';
import {mangaCatalogParams} from '../src/manga-catalog.js';
beforeEach(()=>setMangaPolicy({schemaVersion:1,tags:[],includeDiscovered:true,hiddenTags:[],excludedTerms:[],excludedPrefixes:[]}));
test('OR inside each positive group, AND between groups, any exclusion wins',()=>{
 const row={kind:'manga',genres:['Fantasy'],tags:['Dragons']};
 assert.ok(matchesFilters(row,{genre:'Comedy,Фэнтези',tag:'Robots,Dragons'}));
 assert.equal(matchesFilters(row,{genre:'Comedy',tag:'Dragons'}),false);
 assert.equal(matchesFilters(row,{genre:'Fantasy',excludeGenre:'Comedy,Fantasy'}),false);
 assert.equal(matchesFilters(row,{excludeTag:'Robots,Dragons'}),false);
 assert.equal(matchesFilters(row,{tag:'Fantasy'}),false);
});
test('source genres migrate to semantic genres or flat tags, never numeric IDs',()=>{
 const row=taxonomyFacts({kind:'manga',genres:['Fantasy','School','106'],tags:['Comedy','3D']});
 assert.deepEqual(row.genres,['Фэнтези','Комедия']);assert.deepEqual(row.tags,['School','3D']);
});
test('catalogue labels repair mojibake and policy aliases keep Crime a genre',()=>{
 assert.equal(readableCatalogLabel('РљСЂРёРјРёРЅР°Р»'),'Криминал');
 setMangaPolicy({schemaVersion:1,includeDiscovered:true,hiddenTags:[],excludedTerms:[],excludedPrefixes:[],tags:[{key:'преступность',label:'Преступность',aliases:['Crime']}]});
 assert.equal(classifyLabel('Криминал','tags','anime').category,'genres');
 assert.equal(classifyLabel('Преступность','tags','anime').category,'genres');
 assert.deepEqual(taxonomyFacts({kind:'anime',genres:[],tags:['Crime']}).genres,['Криминал']);
});
test('ordinary books retain real genres and novels retain tags',()=>{
 assert.deepEqual(taxonomyFacts({kind:'book',genres:['Fantasy','shelf 106'],tags:['Dragons']}).tags,[]);
 assert.deepEqual(taxonomyFacts({kind:'ranobe',genres:['Fantasy'],tags:['Dragons']}).tags,['Dragons']);
 assert.equal(formatOptions('movie').length,0);assert.equal(formatOptions('tv').length,0);
});
test('hentai is scoped to illustrated/novel content, formats depend on kind',()=>{
 assert.deepEqual(taxonomyFacts({kind:'movie',tags:['Hentai','Erotica']}).genres,['Эротика']);
 assert.ok(matchesFilters({kind:'anime',format:'TV',genres:[],tags:[]},{format:'Аниме-сериал'}));
 assert.ok(matchesFilters({kind:'manga',format:'manhwa',readingMode:'webtoon',genres:[],tags:[]},{format:'Манхва',readingMode:'webtoon'}));
});
test('all signed groups and separate reading mode travel to Oracle',()=>{
 const query=mangaCatalogParams({filters:{genre:'Fantasy,Comedy',excludeGenre:'Horror',tag:'Dragons',excludeTag:'Robots',readingMode:'webtoon'}});
 assert.equal(query.get('excludeGenre'),'Horror');assert.equal(query.get('excludeTag'),'Robots');assert.equal(query.get('readingMode'),'webtoon');
});

test('a source label containing a comma remains one signed value',()=>{const query=mangaCatalogParams({filters:{tag:['Dragons, ancient'],excludeTag:['Robots']}});assert.deepEqual(JSON.parse(query.get('tag')),['Dragons, ancient']);assert.ok(matchesFilters({kind:'manga',tags:['Dragons, ancient'],genres:[]},{tag:['Dragons, ancient']}));});

test('cleared groups do not start speculative source enrichment',()=>{assert.equal(hasCatalogFilters({genre:[],tag:[],excludeTag:[],excludeGenre:[]}),false);assert.equal(hasCatalogFilters({genre:'[]'}),false);assert.ok(hasCatalogFilters({excludeTag:['Robots']}));assert.equal(mangaCatalogParams({filters:{genre:[],tag:[]}}).has('genre'),false);});

test('trusted source catalogues imply hentai, general adult sources and lookalikes do not',()=>{
 for(const sourceUrl of ['https://hentailib.me/garden','https://x17.h-chan.me/garden','https://hitomi.la/garden','https://g.nude-moon.fun/garden'])assert.ok(taxonomyFacts({kind:'manga',sourceUrl,genres:[],tags:[]}).genres.includes('Хентай'));
 for(const sourceUrl of ['https://mangalib.me/garden','https://manga-chan.me/garden','https://hitomi.la.evil.example/garden'])assert.equal(taxonomyFacts({kind:'manga',sourceUrl,adult:true,genres:[],tags:[]}).genres.includes('Хентай'),false);
 assert.ok(taxonomyFacts({kind:'anime',provider:'hanime',genres:[],tags:[]}).genres.includes('Хентай'));
 assert.equal(taxonomyFacts({kind:'movie',provider:'hanime',genres:[],tags:[]}).genres.includes('Хентай'),false);
});

test('non-hentai veto beats origin, explicit genre, and a hidden source label',()=>{
 for(const tag of ['Не хентай','NON-HENTAI','Not hentai']){
  const row=taxonomyFacts({kind:'manga',sourceUrl:'https://hentailib.me/garden',genres:['Hentai'],tags:[tag]});
  assert.equal(row.genres.includes('Хентай'),false);assert.equal(row.hentaiExcluded,true);
 }
 const row=taxonomyFacts({kind:'manga',provider:'hitomi',genres:['Hentai'],tags:[],workFacts:{hentaiExcluded:true}});
 assert.equal(row.genres.includes('Хентай'),false);
});

test('source evidence survives folding into a metadata card',async()=>{
 const {worldResults}=await import('../src/world-search.js');
 const meta={id:'meta:1',provider:'fixture',kind:'manga',title:'Garden',titles:{},aliases:[],genres:[],tags:[],links:[],ids:{},releases:[]};
 const source={provider:'hentailib',sourceId:'4',kind:'manga',title:'Garden',sourceUrl:'https://hentailib.me/garden',url:'https://hentailib.me/garden',genres:[],tags:[]};
 const item=worldResults([meta],[source],'')[0];assert.ok(taxonomyFacts(item).genres.includes('Хентай'));
 const veto=worldResults([meta],[{...source,hentaiExcluded:true}],'')[0];assert.equal(taxonomyFacts(veto).genres.includes('Хентай'),false);
});

test('title profile preserves inferred genre and work veto after metadata enrichment',async()=>{
 const {mangaPolicyProfile}=await import('../src/manga-tag-policy.js');
 const row={sourceURL:'https://hentailib.me/garden',genres:[],themes:[]};
 assert.ok(mangaPolicyProfile(row,'manga').genres.includes('Хентай'));
 assert.equal(mangaPolicyProfile({...row,genres:['Hentai'],hentaiExcluded:true},'manga').genres.includes('Хентай'),false);
});
