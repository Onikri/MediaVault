// Account-bound encrypted binary cache. No capability URLs or plaintext pages
// are persisted. Source and cleaned images stay compressed, not RGBA/base64.
const NAME='mv-reader-chapters-v1',LIMIT=1024*1024*1024,MAX_AGE=7*86400_000;
let opening;const keys=new Map();
const request=r=>new Promise((resolve,reject)=>{r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
const done=tx=>new Promise((resolve,reject)=>{tx.oncomplete=resolve;tx.onerror=tx.onabort=()=>reject(tx.error);});
async function database(){if(!opening)opening=new Promise((resolve,reject)=>{const r=indexedDB.open(NAME,1);r.onupgradeneeded=()=>{r.result.createObjectStore('pages',{keyPath:'id'});r.result.createObjectStore('keys');};r.onsuccess=()=>resolve(r.result);r.onerror=()=>{opening=null;reject(r.error);};});return opening;}
async function key(db,scope){
 if(!keys.has(scope))keys.set(scope,(async()=>{let value=await request(db.transaction('keys').objectStore('keys').get(scope));if(!value){value=await crypto.subtle.generateKey({name:'AES-GCM',length:256},false,['encrypt','decrypt']);const tx=db.transaction('keys','readwrite');const store=tx.objectStore('keys'),existing=await request(store.get(scope));if(existing)return existing;store.put(value,scope);await done(tx);}return value;})());return keys.get(scope);
}
async function identity(scope,chapter,index,stage){const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode([scope,chapter,index,stage].join('\n')));return [...new Uint8Array(bytes)].map(v=>v.toString(16).padStart(2,'0')).join('');}
export async function readChapterBlob(scope,chapter,index,stage='source'){
 try{const db=await database(),id=await identity(scope,chapter,index,stage),row=await request(db.transaction('pages').objectStore('pages').get(id));if(!row||row.scope!==scope||Date.now()-row.time>MAX_AGE)return null;
  const value=await crypto.subtle.decrypt({name:'AES-GCM',iv:row.iv,additionalData:new TextEncoder().encode(id)},await key(db,scope),await row.data.arrayBuffer());return new Blob([value],{type:row.mime});
 }catch{return null;}
}
export async function writeChapterBlob(scope,chapter,index,stage,blob){
 try{const db=await database(),id=await identity(scope,chapter,index,stage),iv=crypto.getRandomValues(new Uint8Array(12)),encrypted=await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:new TextEncoder().encode(id)},await key(db,scope),await blob.arrayBuffer());
  let tx=db.transaction('pages','readwrite');tx.objectStore('pages').put({id,scope,iv,data:new Blob([encrypted]),mime:blob.type,bytes:encrypted.byteLength,time:Date.now()});await done(tx);
  const rows=await request(db.transaction('pages').objectStore('pages').getAll());let total=rows.reduce((n,r)=>n+r.bytes,0);tx=db.transaction('pages','readwrite');for(const row of rows.sort((a,b)=>a.time-b.time))if(total>LIMIT||Date.now()-row.time>MAX_AGE){tx.objectStore('pages').delete(row.id);total-=row.bytes;}await done(tx);return true;
 }catch{return false;}
}
export async function removeChapterBlob(scope,chapter,index,stage){try{const db=await database(),id=await identity(scope,chapter,index,stage),tx=db.transaction('pages','readwrite');tx.objectStore('pages').delete(id);await done(tx);}catch{}}
export function cachedChapterEntries(entries,scope,chapter,{read=readChapterBlob,write=writeChapterBlob}={}){
 const memory=new Map(),pending=new Map(),identity=chapter+':pages='+entries.length;
 return entries.map((entry,index)=>({...entry,async:()=>{
  if(memory.has(index)){const blob=memory.get(index);memory.delete(index);memory.set(index,blob);return Promise.resolve(blob);}
  if(!pending.has(index)){const task=(async()=>{let blob=await read(scope,identity,index);if(!blob){blob=await entry.async('blob');await write(scope,identity,index,'source',blob);}memory.set(index,blob);while(memory.size>9)memory.delete(memory.keys().next().value);return blob;})();pending.set(index,task);task.finally(()=>pending.delete(index)).catch(()=>{});}
  return pending.get(index);
 }}));
}
export async function encodeCleanPage(value){const{cleanedImage,...meta}=value,json=new TextEncoder().encode(JSON.stringify(meta)),length=new ArrayBuffer(4);new DataView(length).setUint32(0,json.length,true);return new Blob([length,json,cleanedImage],{type:'application/x-mediavault-clean-page'});}
export async function decodeCleanPage(blob){const bytes=await blob.arrayBuffer(),length=new DataView(bytes).getUint32(0,true);if(length>bytes.byteLength-4)throw Error('Повреждён кэш очистки');return {...JSON.parse(new TextDecoder().decode(bytes.slice(4,4+length))),cleanedImage:bytes.slice(4+length)};}
