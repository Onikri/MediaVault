import test from 'node:test';
import assert from 'node:assert/strict';
import {normalizeProfile,russianText,plainText,imageURL,profileArtwork} from '../src/title-metadata.js';

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
