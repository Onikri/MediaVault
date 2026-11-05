import test from 'node:test';import assert from 'node:assert/strict';
import {parseReaderLanguage,probeReaderLanguage,readerLanguagePrompt} from '../src/reader-language.js';
import {setDirectKey} from '../src/manga-direct-key.js';
test('dialogue determines the language even with foreign SFX',()=>{
 const v=parseReaderLanguage({dialogue:{en:95,ja:5},sfx:{ja:100},hasDialogue:true},'Japanese');assert.equal(v.language,'English');assert.equal(v.confident,true);assert.equal(v.sfx.ja,100);assert.match(readerLanguagePrompt,/English with Japanese SFX is English/);
});
test('ambiguous, unsupported or cover-only pages retain the explicit fallback',()=>{
 for(const data of [{dialogue:{en:50,ja:50},hasDialogue:true},{dialogue:{other:100},hasDialogue:true},{dialogue:{ja:100},hasDialogue:false}]){const v=parseReaderLanguage(data,'Korean');assert.equal(v.confident,false);assert.equal(v.language,'Korean');}
 assert.throws(()=>parseReaderLanguage({dialogue:{en:-1}}));assert.throws(()=>parseReaderLanguage({}));
});
test('server probe sends two bounded images once through the selected key slot and pacing',async()=>{
 const sent=[],reserved=[],pages=[];const result=await probeReaderLanguage({entries:[0,1,2].map(index=>({async:async()=>{pages.push(index);return new Blob(['page'+index]);}})),page:0,config:{engine:'vm',language:'Japanese',directModel:'gemini-3.5-flash-lite'},serverSlots:[2],signal:new AbortController().signal,encode:async blob=>btoa(await blob.text()),pacer:{reserve:async key=>reserved.push(key)},send:async body=>{sent.push(body);return{candidates:[{content:{parts:[{text:JSON.stringify({dialogue:{en:100},sfx:{ja:100},hasDialogue:true})}]}}]};}});
 assert.deepEqual(pages,[0,1]);assert.equal(sent.length,1);assert.equal(sent[0].slot,2);assert.equal(sent[0].key,undefined);assert.equal(sent[0].request.contents[0].parts.length,3);assert.equal(sent[0].request.generationConfig.maxOutputTokens,512);assert.equal(result.keyVerified,true);assert.equal(result.language,'English');assert.deepEqual(reserved,['oracle-slot:2']);
});
test('personal mode never borrows a server slot; provider failure is not retried',async()=>{
 setDirectKey('language-test','fixture-private-key');let calls=0;
 await assert.rejects(probeReaderLanguage({entries:[{async:async()=>new Blob(['page'])}],config:{engine:'direct',language:'English',directModel:'gemini-3.5-flash-lite'},keyScope:'language-test',serverSlots:[0],signal:new AbortController().signal,encode:async()=>'',pacer:{reserve:async()=>{}},send:async body=>{calls++;assert.equal(body.key,'fixture-private-key');assert.equal(body.slot,undefined);throw Error('HTTP 429');}}),/429/);assert.equal(calls,1);setDirectKey('language-test','');
});
test('aborting the probe prevents any Google call',async()=>{
 const controller=new AbortController();controller.abort();let calls=0;
 await assert.rejects(probeReaderLanguage({entries:[{async:async()=>new Blob(['x'])}],config:{engine:'vm',language:'Japanese',directModel:'gemini-3.5-flash-lite'},serverSlots:[0],signal:controller.signal,encode:async()=>'',pacer:{reserve:async()=>{}},send:async()=>{calls++;}}));assert.equal(calls,0);
});
