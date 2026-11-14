import test,{beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {setMangaPolicy} from '../src/manga-tag-policy.js';
import {matchesFilters} from '../src/catalog.js';
import {taxonomyFacts,formatOptions,hasCatalogFilters} from '../src/catalog-taxonomy.js';
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
