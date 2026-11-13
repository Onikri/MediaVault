import test,{afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {compileMangaPolicy,setMangaPolicy,mangaPolicyFacts,mangaPolicyProfile,subscribeMangaPolicy,acceptContentPolicy,contentPolicyRevision} from '../src/manga-tag-policy.js';
import {blossomRecord} from '../src/blossom/media-adapter.js';
import {mangaFacetOptions} from '../src/manga-catalog.js';
const bundled=JSON.parse(readFileSync(new URL('../server/manga-tag-policy.json',import.meta.url)));
const base={schemaVersion:1,excludedTerms:[],excludedPrefixes:[],tags:[
 {key:'fantasy',label:'Фэнтези',aliases:['Fantasy','幻想','판타지']},
 {key:'drama',label:'Драма',aliases:['Drama']}]};
afterEach(()=>setMangaPolicy(bundled));

test('all registered sources use the same aliases and deletion removes cards and profiles',()=>{
 setMangaPolicy(base);
 for(let i=0;i<18;i++)assert.deepEqual(mangaPolicyFacts({url:'https://source'+i+'.example/title',tags:[['Fantasy','幻想','판타지'][i%3]],genres:['Drama']}).tags,['Фэнтези']);
 let notified=0;const stop=subscribeMangaPolicy(()=>notified++);
 setMangaPolicy({...base,tags:[base.tags[1]]});stop();assert.equal(notified,1);
 assert.deepEqual(mangaPolicyFacts({tags:['Fantasy'],genres:['Drama']}),{tags:[],genres:['Драма']});
 assert.deepEqual(mangaPolicyProfile({genres:['Fantasy'],themes:['幻想']}).genres,[]);
 assert.deepEqual(blossomRecord({kind:'manga',genres:['Fantasy']}).genres,[]);
 assert.deepEqual(blossomRecord({kind:'anime',genres:['Fantasy']}).genres,[{name:'Fantasy'}]);
});
test('exclusions hide every alias; source-specific aliases stay scoped',()=>{
 const policy=compileMangaPolicy({...base,excludedTerms:['Fantasy']});
 for(const value of ['Fantasy','幻想','판타지','Фэнтези'])assert.equal(policy.key(value),'');
 const scoped=compileMangaPolicy({...base,tags:[{...base.tags[0],sourceAliases:{'one.example':['Special label']}},base.tags[1]]});
 assert.equal(scoped.key('Special label','one.example'),'fantasy');assert.equal(scoped.key('Special label','two.example'),'');
 setMangaPolicy(scoped.data);
 assert.equal(mangaFacetOptions(null,[{key:'fantasy',original:'Special label',type:'tags'}])[0].label,'Фэнтези');
});
test('ambiguous aliases are rejected before replacing active rules',()=>{
 assert.throws(()=>setMangaPolicy({...base,tags:[base.tags[0],{...base.tags[1],aliases:['Fantasy']}]}),/алиас/);
});

test('automatic vocabulary preserves unknown labels and exact hides are reversible',()=>{
 const data={...base,includeDiscovered:true,hiddenTags:['Ecology']};
 assert.deepEqual(compileMangaPolicy(data).facts({genres:['Ecology','Ocean worlds']}),{genres:['Ocean worlds'],tags:[]});
 assert.deepEqual(compileMangaPolicy({...data,hiddenTags:[]}).facts({genres:['Ecology']}),{genres:['Ecology'],tags:[]});
});

test('cached catalogue response installs expanded vocabulary before projecting rows',()=>{
 setMangaPolicy(base,'old','all');
 const response={items:[{kind:'manga',genres:['Ocean worlds']}],tagPolicy:{revision:'new',scope:'all',policy:{...base,tags:[...base.tags,{key:'ocean worlds',label:'Миры океана',aliases:['Ocean worlds']}]}}};
 assert.equal(acceptContentPolicy(response),response);assert.equal(contentPolicyRevision(),'new');
 assert.deepEqual(mangaPolicyFacts(response.items[0]).genres,['Миры океана']);
});
