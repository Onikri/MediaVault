import test from 'node:test';
import assert from 'node:assert/strict';
import {normalizeProfile,russianText,plainText,imageURL,profileArtwork} from '../src/title-metadata.js';
import {mergeCharacterDetails} from '../src/title-profile-merge.js';

test('a late dossier save preserves fetched character details but respects changed cast',()=>{
 const saved=[{id:'17',description:'Недавно загруженное описание',name:'Наруто'},{id:'18',name:'Удалённый персонаж'}];
 const fresh=mergeCharacterDetails(saved,[{id:17,description:'',name:'Наруто Узумаки'},{id:'19',name:'Новый персонаж'}]);
 assert.equal(fresh[0].description,saved[0].description);
 assert.equal(fresh[0].name,'Наруто Узумаки');
 assert.deepEqual(fresh.map(v=>String(v.id)),['17','19']);
 assert.equal(mergeCharacterDetails(saved,[{id:'17',description:'Обновлённое описание'}])[0].description,'Обновлённое описание');
 assert.deepEqual(mergeCharacterDetails(saved,[]),[]);
});

test('Russian dossier uses Russian descriptions, characters, facts and related media without inserting English prose',()=>{
 const profile=normalizeProfile({id:16498,russian:'Атака титанов',name:'Attack on Titan',kind:'tv',status:'released',source:'manga_source',rating:'r',description:'English synopsis only',aired_on:'2013-04-07',score:'8.55',image:{original:'/cover.jpg'},genres:[{russian:'Экшен',name:'Action'}]}, {
  roles:[{roles:['Main'],roles_russian:['Главный герой'],character:{id:1,russian:'Эрен Йегер',image:{preview:'/eren.jpg'}}},{roles:['Director'],person:{russian:'Тэцуро Араки'}}],
  related:[{relation_russian:'Первоисточник',manga:{id:23390,russian:'Атака титанов',kind:'manga'}}],screenshots:[{original:'/still.jpg'}]
 });
 assert.equal(profile.title,'Атака титанов');assert.equal(profile.description,'');assert.equal(profile.status,'Завершён');assert.equal(profile.origin,'Манга');assert.equal(profile.rating,'17+');assert.deepEqual(profile.genres,['Экшен']);
 assert.equal(profile.characters[0].name,'Эрен Йегер');assert.equal(profile.related[0].kind,'manga');assert.equal(profile.background,'https://shikimori.io/still.jpg');
 assert.equal(russianText('<p>Русское <b>описание</b></p>'),'Русское описание');assert.equal(plainText('[character=1]Эрен[/character]'),'Эрен');
 assert.equal(imageURL('javascript:alert(1)'),'');assert.equal(imageURL(''),'');assert.equal(imageURL('https://user:password@example.test/image.jpg'),'');
 assert.equal(profileArtwork(profile).length,3);
});


test('legacy PBKDF2 encrypted libraries open with the unified server-import key derivation',async()=>{
 const {deriveVaultMaterial,sealIndex,openIndex}=await import('../crypto.js');
 const salt=crypto.getRandomValues(new Uint8Array(16)),phrase='legacy integration fixture phrase';
 const raw=await crypto.subtle.importKey('raw',new TextEncoder().encode(phrase),'PBKDF2',false,['deriveKey']);
 const legacy=await crypto.subtle.deriveKey({name:'PBKDF2',salt,iterations:310000,hash:'SHA-256'},raw,{name:'AES-GCM',length:256},false,['encrypt','decrypt']);
 const catalog={version:1,folderId:'legacy-root',items:[{id:'old-episode'}],custom:{retained:true}};
 const envelope=await sealIndex(catalog,legacy,salt),current=await deriveVaultMaterial(phrase,salt);
 try{assert.deepEqual(await openIndex(envelope,current.key),catalog);assert.equal(current.key.extractable,false);assert.equal(current.serverKey.length,32);}finally{current.serverKey.fill(0);}
});

test('background dossier retries back off and stop instead of rewriting Drive on every visit',async()=>{
 const {profileNeedsRefresh,scheduleProfileRetry,previewNeedsRetry,PROFILE_RETRY_LIMIT}=await import('../src/title-metadata.js');
 const {libraryEnrichmentDue,jobNoticeWanted}=await import('../src/import-service.js');
 const now=1_800_000_000_000,hour=3600000;
 assert.equal(profileNeedsRefresh(undefined,now),true);
 const complete={version:4,sourceId:'1',partial:false};
 assert.equal(profileNeedsRefresh(complete,now),false);
 assert.equal(profileNeedsRefresh({...complete,genres:[]},now),false,'a catalogue without genres is not a reason to refetch');
 let profile={version:4,sourceId:'1',partial:true};
 assert.equal(profileNeedsRefresh(profile,now),true);
 profile=scheduleProfileRetry(profile,profile,now);
 assert.equal(profile.profileAttempts,1);assert.equal(profile.retryAfter,now+6*hour);
 assert.equal(profileNeedsRefresh(profile,now+60000),false);
 for(let i=1;i<PROFILE_RETRY_LIMIT;i++)profile=scheduleProfileRetry(profile,profile,profile.retryAfter);
 assert.equal(profile.profileAttempts,PROFILE_RETRY_LIMIT);
 assert.equal(profileNeedsRefresh(profile,now+10**12),false);
 assert.deepEqual(scheduleProfileRetry({...complete},profile,now),{...complete,profileAttempts:0,retryAfter:0});
 const frame={category:'video',previewAttempts:1,previewRetryAfter:now+hour};
 assert.equal(previewNeedsRetry(frame,now),false);assert.equal(previewNeedsRetry(frame,now+hour),true);
 assert.equal(previewNeedsRetry({...frame,previewAttempts:3},now+10**12),false);
 const catalog={items:[{category:'manga',collectionId:'c'},{...frame}],titleProfiles:{'manga:c':complete}};
 assert.equal(libraryEnrichmentDue(catalog,now),false);
 assert.equal(libraryEnrichmentDue(catalog,now+hour),true);
 assert.equal(libraryEnrichmentDue({items:[{category:'video',previewArtwork:{}}],titleProfiles:{x:profile}},now),false);
 const enrich=status=>({status,progress:{taskType:'enrich'}});
 assert.equal(jobNoticeWanted(enrich('completed')),false);assert.equal(jobNoticeWanted(enrich('failed')),false);
 assert.equal(jobNoticeWanted(enrich('waiting_auth')),true);
 assert.equal(jobNoticeWanted({status:'completed',progress:{taskType:'import'}}),true);
});
