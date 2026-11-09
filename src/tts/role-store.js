// Chapter roles kept on this device (IndexedDB): a reopened or prefetched
// chapter is ready at once and costs no model tokens. The key holds the book,
// the chapter, a hash of its text and the role format version; the newest
// LIMIT chapters are kept. Without IndexedDB (private mode) nothing is stored.
const DB='mediavault-tts',STORE='roles',LIMIT=400;
let opening=null;

function open(){
 if(!globalThis.indexedDB)return Promise.resolve(null);
 opening||=new Promise(resolve=>{
  try{
   const request=indexedDB.open(DB,1);
   request.onupgradeneeded=()=>{const store=request.result.createObjectStore(STORE);store.createIndex('at','at');};
   request.onsuccess=()=>resolve(request.result);request.onerror=()=>resolve(null);request.onblocked=()=>resolve(null);
  }catch{resolve(null);}
 });
 return opening;
}
const done=request=>new Promise(resolve=>{request.onsuccess=()=>resolve(request.result);request.onerror=()=>resolve(null);});

// FNV-1a over the chapter text: a changed translation is a new chapter.
export function textHash(paragraphs){
 let hash=0x811c9dc5,length=0;
 for(const paragraph of paragraphs){const value=String(paragraph);length+=value.length;for(let i=0;i<value.length;i++){hash^=value.charCodeAt(i);hash=Math.imul(hash,0x01000193)>>>0;}hash^=10;}
 return hash.toString(36)+'.'+length.toString(36);
}

export async function readRoles(key){
 const db=await open();if(!db)return null;
 try{return await done(db.transaction(STORE).objectStore(STORE).get(key));}catch{return null;}
}

export async function writeRoles(key,value){
 const db=await open();if(!db)return;
 try{
  const store=db.transaction(STORE,'readwrite').objectStore(STORE);
  await done(store.put({...value,at:Date.now()},key));
  const count=await done(store.count());
  if(count>LIMIT){
   const old=db.transaction(STORE,'readwrite').objectStore(STORE).index('at').openCursor();let extra=count-LIMIT;
   old.onsuccess=()=>{const cursor=old.result;if(!cursor||extra--<=0)return;cursor.delete();cursor.continue();};
  }
 }catch{}
}
