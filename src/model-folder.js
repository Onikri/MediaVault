// Directory handles, unlike cookies or file paths, carry browser-granted access.
// Workers on this origin read the same handle. They never display permission UI.
const DB='mediavault-model-folder',STORE='settings';
export async function sharedArtifactResult(pending,noReturn,reload){
 const result=await pending;
 if(result===undefined&&!noReturn)return reload();
 return result instanceof Response?result.clone():result;
}
async function database(){
 if(!globalThis.indexedDB)return null;
 return new Promise((resolve,reject)=>{const r=indexedDB.open(DB,1);r.onupgradeneeded=()=>r.result.createObjectStore(STORE);r.onerror=()=>reject(r.error);r.onsuccess=()=>resolve(r.result);});
}
async function savedHandle(value){
 const db=await database();if(!db)return null;
 try{return await new Promise((resolve,reject)=>{
  const write=value!==undefined,tx=db.transaction(STORE,write?'readwrite':'readonly'),store=tx.objectStore(STORE);
  const r=write?(value===null?store.delete('directory'):store.put(value,'directory')):store.get('directory');
  let result;r.onsuccess=()=>{result=r.result;};tx.oncomplete=()=>resolve(write?value:result||null);tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error);
 });}finally{db.close();}
}
export async function modelFileName(url){
 const parsed=new URL(url);if(parsed.protocol!=='https:'||parsed.username||parsed.password||parsed.search||parsed.hash)throw Error('Некорректный адрес модели.');
 const name=parsed.pathname.split('/').at(-1);
 if(!name||!/\.(?:onnx|bin|safetensors|gguf|json|txt)$/.test(name))throw Error('Неподдерживаемый файл модели.');
 const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(url)))).map(v=>v.toString(16).padStart(2,'0')).join('');
 return hash.slice(0,24)+'-'+name.replace(/[^A-Za-z0-9_.-]/g,'_');
}
export function folderClient(load=savedHandle){
 async function directory(mode){
  try{const handle=await load();return handle&&await handle.queryPermission({mode})==='granted'?handle:null;}catch{return null;}
 }
 return {
  async read(url){try{const dir=await directory('read');if(!dir)return null;const h=await dir.getFileHandle(await modelFileName(url));const file=await h.getFile();return file.size?file:null;}catch{return null;}},
  async write(url,bytes){
   const dir=await directory('readwrite');if(!dir)return false;
   const name=await modelFileName(url),file=await dir.getFileHandle(name,{create:true}),writer=await file.createWritable();
   try{await writer.write(bytes);await writer.close();return true;}catch(error){await writer.abort().catch(()=>{});throw error;}
  },
  async remove(url){const dir=await directory('readwrite');if(dir)await dir.removeEntry(await modelFileName(url)).catch(()=>{});},
 };
}
const client=folderClient();
export const readModelFile=url=>client.read(url);
export async function writableModelFolder(){try{const handle=await savedHandle();return !!handle&&await handle.queryPermission({mode:'readwrite'})==='granted';}catch{return false;}}
export const writeModelFile=(url,bytes)=>client.write(url,bytes);
export const removeModelFile=url=>client.remove(url);
export async function modelFolderState(){
 let handle;try{handle=await savedHandle();}catch{}
 return {supported:typeof globalThis.showDirectoryPicker==='function',name:handle?.name||'',permission:handle?await handle.queryPermission({mode:'readwrite'}).catch(()=>'denied'):'none'};
}
export async function chooseModelFolder(){
 if(!globalThis.showDirectoryPicker)throw Error('Выбор папки доступен в Chrome/Edge на компьютере. На этом устройстве используется кэш браузера.');
 const handle=await showDirectoryPicker({id:'mediavault-models',mode:'readwrite'});
 await savedHandle(handle);return modelFolderState();
}
export async function restoreModelFolder(){
 const handle=await savedHandle();if(handle)await handle.requestPermission({mode:'readwrite'});return modelFolderState();
}
export async function forgetModelFolder(){await savedHandle(null);return modelFolderState();}
export async function requestModelPersistence(){
 try{return await navigator.storage?.persist?.()||false;}catch{return false;}
}
export async function readModelResponse(response,onProgress){
 const total=Number(response.headers.get('content-length'))||0;
 if(!response.body?.getReader){const bytes=await response.arrayBuffer();onProgress(bytes.byteLength,total||bytes.byteLength);return bytes;}
 const reader=response.body.getReader(),parts=[];let loaded=0;
 try{for(;;){const{done,value}=await reader.read();if(done)break;parts.push(value);loaded+=value.byteLength;onProgress(loaded,total);}}
 finally{reader.releaseLock();}
 if(total&&loaded!==total)throw Error('Загрузка модели оборвалась: получен неполный файл.');
 return await new Blob(parts).arrayBuffer();
}
