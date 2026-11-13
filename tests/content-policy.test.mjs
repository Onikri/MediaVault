import test from 'node:test';
import assert from 'node:assert/strict';
import {compileMangaPolicy,setMangaPolicy,contentPolicyFacts,mangaPolicyProfile} from '../src/manga-tag-policy.js';
import {addContentLabels,updateContentRule} from '../src/control/content-policy-editor.js';
import {matchesFilters} from '../src/catalog.js';
import {queryLabel} from '../src/taxonomy.js';

const base={schemaVersion:1,excludedTerms:[],excludedPrefixes:[],tags:[{key:'journey',label:'Путешествие',aliases:['Journey','旅','여행'],category:'genre'}]};
test('one runtime policy classifies, filters and removes tags across all content kinds',()=>{
 setMangaPolicy(base,'fixture-global','all');
 for(const kind of ['movie','tv','anime','manga','ranobe','book']){
  const row=contentPolicyFacts({kind,title:'Garden',genres:[],tags:['旅'],format:''});
  assert.deepEqual(row.genres,['Путешествие']);assert.deepEqual(row.tags,[]);
  assert.ok(matchesFilters(row,{genre:'여행'}));
 }
 assert.equal(queryLabel('Путешествие'),'Journey');
 const hidden={...base,excludedTerms:['Journey']};setMangaPolicy(hidden,'fixture-hidden','all');
 for(const kind of ['movie','tv','anime','manga','ranobe','book'])assert.deepEqual(contentPolicyFacts({kind,tags:['旅'],genres:['Journey']}).genres,[]);
 assert.deepEqual(mangaPolicyProfile({genres:['Journey'],themes:['여행']}).themes,[]);
 setMangaPolicy(base,'fixture-reset');
});
test('bulk paste adds arbitrary neutral names, preserves existing settings and deduplicates aliases',()=>{
 const result=addContentLabels(base,'Ecology\nEcology;Journey\nМир океана','tag');
 assert.equal(result.added,2);assert.equal(base.tags.length,1);
 assert.deepEqual(result.policy.excludedTerms,[]);
 assert.equal(result.policy.tags.at(-1).label,'Мир океана');
 assert.throws(()=>addContentLabels(base,'x'.repeat(121),'tag'));
});
test('renaming and explicit source aliases remain scoped and detect collisions',()=>{
 const policy=updateContentRule(base,'journey',{label:'Дорога',sourceAliases:{'one.example':['Wandering']}});
 const compiled=compileMangaPolicy(policy);
 assert.equal(compiled.key('Wandering','one.example'),'journey');
 assert.equal(compiled.key('Wandering','two.example'),'');
 assert.throws(()=>compileMangaPolicy({...base,tags:[...base.tags,{key:'other',label:'Other',aliases:['旅']}]}));
});
