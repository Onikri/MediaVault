import test from 'node:test';
import assert from 'node:assert/strict';
import {createPlaceSync,syncKeyFor,storageKeyFor,applyPlaces} from '../src/place-sync.js';
import {createRetainedMediaStore} from '../src/retained-media-store.js';
import {saveRanobeProgress,ranobeProgress} from '../src/ranobe-client.js';
import {writeReading,readReading} from '../src/reading-progress.js';
import {writeProgress,readProgress} from '../src/playback-progress.js';
import {saveWatch,readWatch} from '../src/watch-session.js';
import {titleResume} from '../src/title-resume.js';

function memory(){
 const data=new Map();
 return {data,get length(){return data.size;},key:i=>[...data.keys()][i]??null,getItem:k=>data.has(k)?data.get(k):null,setItem:(k,v)=>data.set(k,String(v)),removeItem:k=>data.delete(k)};
}
// The contract of POST /places (server/reading_places.py): per profile, the
// newest change of a place wins, removals stay, a device receives what changed
// after its clock, a page at a time.
function server({page=800}={}){
 const profiles=new Map();let last=0,calls=0,offline=false;
 const request=user=>async(path,{method,body})=>{
  calls++;if(offline)throw Error('Нет сети');
  assert.equal(path,'/places');assert.equal(method,'POST');
  const rows=profiles.get(user)||new Map();profiles.set(user,rows);
  for(const e of body.entries){const row=rows.get(e.k);if(row&&row.at>=e.at)continue;rows.set(e.k,{k:e.k,at:e.at,v:JSON.parse(JSON.stringify(e.v)),seen:++last});}
  const since=body.since>last?0:body.since,changed=[...rows.values()].filter(r=>r.seen>since).sort((a,b)=>a.seen-b.seen),more=changed.length>page,out=changed.slice(0,page);
  return {clock:more?out.at(-1).seen:last,entries:out.map(({k,at,v})=>({k,at,v})),more};
 };
 return {request,profiles,get calls(){return calls;},set offline(v){offline=v;}};
}
const history=(storage,user)=>JSON.parse(storage.getItem('mv_viewing_history_v1:'+user)||'[]');
function device(remote,user,storage=memory()){
 const events=[];const sync=createPlaceSync({user,request:remote.request(user),storage,delay:60000,emit:keys=>events.push(keys)});
 return {storage,sync,events};
}

test('every saved place maps to one sync key of its own profile and back',()=>{
 const pairs=[
  ['mediavault_ranobe_progress_v1:alice:'+encodeURIComponent('https://ranobe.example/book'),'r:'],
  ['mediavault_reading_v1:alice:online:'+encodeURIComponent('online:https://manga.example/c/12'),'m:'],
  ['mediavault_progress_v2:alice:online:'+encodeURIComponent('online:52991:s1:e5'),'p:'],
  ['mv_watch_v1:alice:52991','w:'],
 ];
 for(const [key,family] of pairs){const synced=syncKeyFor('alice',key);assert.ok(synced.startsWith(family),key);assert.equal(storageKeyFor('alice',synced),key);assert.equal(storageKeyFor('bob',synced).includes(':bob:'),true);}
 assert.equal(syncKeyFor('bob',pairs[0][0]),'');
 assert.equal(syncKeyFor('alice','mediavault_progress_v2:alice:'+encodeURIComponent('drive-library')+':file'),'',"a Drive library's own progress stays on the device");
 assert.equal(syncKeyFor('','mv_watch_v1:anonymous:1'),'');
});

test('a chapter read on the computer reaches the phone: «Продолжить · глава 12» and the same paragraph',async()=>{
 const remote=server(),pc=device(remote,'alice'),phone=device(remote,'alice');
 await phone.sync.start();
 await pc.sync.start();
 const book='https://ranobe.example/book/7',chapter='https://ranobe.example/book/7/12';
 saveRanobeProgress('alice',book,{chapter,paragraph:37,title:'Глава 12'},pc.storage);
 // The open reader names the chapter in the viewing history of the computer.
 globalThis.localStorage=pc.storage;
 const workspace=createRetainedMediaStore();workspace.scope('alice');
 workspace.attach('ranobe:alice:shiki-7',{userId:'alice',label:'Книга, глава 12',kind:'reader',route:'#watch=shiki-7&read=12'},{isConnected:true},{});
 workspace.activate('ranobe:alice:shiki-7');
 const row={id:'ranobe:alice:shiki-7'};
 await pc.sync.run();
 await phone.sync.run();
 assert.deepEqual(ranobeProgress('alice',book,phone.storage)?.chapter,chapter);
 assert.equal(ranobeProgress('alice',book,phone.storage).paragraph,37);
 assert.deepEqual(titleResume(history(phone.storage,'alice'),'shiki-7')?.place,'глава 12');
 assert.ok(phone.events.flat().includes('r:'+encodeURIComponent(book)));
 assert.ok(phone.events.flat().includes('h:'+row.id));
 // The computer's own place came back unchanged and was not re-applied.
 assert.equal(pc.events.length,0);
 pc.sync.stop();phone.sync.stop();
});

test('the newest place wins; an offline phone keeps its change and sends it later',async()=>{
 const remote=server(),pc=device(remote,'alice'),phone=device(remote,'alice');
 await pc.sync.start();await phone.sync.start();
 const book='https://ranobe.example/b';
 saveRanobeProgress('alice',book,{chapter:'c1',paragraph:5},phone.storage);
 const older=JSON.parse(phone.storage.getItem('mediavault_ranobe_progress_v1:alice:'+encodeURIComponent(book)));
 older.updatedAt-=60000;phone.storage.setItem('mediavault_ranobe_progress_v1:alice:'+encodeURIComponent(book),JSON.stringify(older));
 saveRanobeProgress('alice',book,{chapter:'c9',paragraph:1},pc.storage);
 await pc.sync.run();
 remote.offline=true;await phone.sync.run();
 assert.equal(ranobeProgress('alice',book,phone.storage).chapter,'c1','offline: the phone keeps reading where it was');
 remote.offline=false;await phone.sync.run();
 assert.equal(ranobeProgress('alice',book,phone.storage).chapter,'c9','the newer computer place wins over the older phone save');
 // A new phone save after that wins everywhere.
 await new Promise(r=>setTimeout(r,5));
 saveRanobeProgress('alice',book,{chapter:'c10',paragraph:3},phone.storage);
 await phone.sync.run();await pc.sync.run();
 assert.equal(ranobeProgress('alice',book,pc.storage).chapter,'c10');
 pc.sync.stop();phone.sync.stop();
});

test('manga pages, episode seconds and the chosen episode follow the profile; finished and removed places stay removed',async()=>{
 const remote=server(),pc=device(remote,'alice'),phone=device(remote,'alice');
 await pc.sync.start();await phone.sync.start();
 writeReading('alice','online',{id:'online:https://manga.example/c/3',collectionId:'online-title:shiki-9'},14,30,pc.storage);
 writeProgress('alice','online',{id:'online:52991:s1:e5',collectionId:'online-title:52991',episode:5,season:1},612,1420,pc.storage);
 saveWatch('alice','52991',{episode:5,season:1,voiceId:'anilibria'},pc.storage);
 writeReading('alice','drive-library',{id:'file-1'},3,10,pc.storage);
 await pc.sync.run();await phone.sync.run();
 assert.equal(readReading('alice','online','online:https://manga.example/c/3',phone.storage).page,14);
 assert.equal(readReading('alice','online','collection:online-title:shiki-9',phone.storage).page,14);
 assert.equal(readProgress('alice','online','online:52991:s1:e5',phone.storage).time,612);
 assert.equal(readWatch('alice','52991',phone.storage).episode,5);
 assert.equal(readReading('alice','drive-library','file-1',phone.storage),null);
 // Watching to the end removes the place; the removal reaches the computer.
 writeProgress('alice','online',{id:'online:52991:s1:e5',collectionId:'online-title:52991',episode:5,season:1},1415,1420,phone.storage);
 await phone.sync.run();await pc.sync.run();
 assert.equal(readProgress('alice','online','online:52991:s1:e5',pc.storage),null);
 assert.equal(readProgress('alice','online','online:52991:s1:e5',phone.storage),null,'the removal is not undone by the server copy');
 pc.sync.stop();phone.sync.stop();
});

test('places kept before syncing are sent once; profiles never mix; big histories arrive page by page',async()=>{
 const remote=server({page:3}),old=memory();
 for(let i=0;i<7;i++)saveRanobeProgress('alice','https://ranobe.example/'+i,{chapter:'c'+i,paragraph:i},old);
 saveRanobeProgress('bob','https://ranobe.example/bob',{chapter:'b',paragraph:1},old);
 const pc=device(remote,'alice',old);await pc.sync.start();
 assert.equal(remote.profiles.get('alice').size,7);
 assert.equal(remote.profiles.has('bob'),false);
 const phone=device(remote,'alice');await phone.sync.start();
 for(let i=0;i<7;i++)assert.equal(ranobeProgress('alice','https://ranobe.example/'+i,phone.storage).paragraph,i);
 const stranger=device(remote,'carol');await stranger.sync.start();
 assert.equal([...stranger.storage.data.keys()].filter(k=>k.includes('ranobe_progress')).length,0);
 pc.sync.stop();phone.sync.stop();stranger.sync.stop();
});

test('an unsent change on this device is not overwritten by an older server copy',()=>{
 const storage=memory();
 saveRanobeProgress('alice','https://r.example/x',{chapter:'mine',paragraph:2},storage);
 const key='r:'+encodeURIComponent('https://r.example/x');
 const applied=applyPlaces('alice',[{k:key,at:1,v:{chapter:'theirs',paragraph:0,updatedAt:1}},{k:'h:gone',at:5,v:null}],{[key]:Date.now()},storage);
 assert.deepEqual(applied,[]);
 assert.equal(ranobeProgress('alice','https://r.example/x',storage).chapter,'mine');
 assert.deepEqual(applyPlaces('alice',[{k:'h:bad',at:5,v:{id:'h',label:'x',route:'no-hash'}}],{},storage),[],'a malformed history row is refused');
});
