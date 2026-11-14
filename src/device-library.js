// «Папка на устройстве»: where saves land unencrypted and what the collection
// can open without a network. On a computer (Chrome/Edge) it is a real folder
// the person picks; elsewhere it is the site's private browser storage (OPFS).
// Only Google Drive keeps the encrypted copy.
const DB='mediavault-device-library',STORE='settings',KEY='directory';
export const KIND_FOLDERS={anime:'Аниме',manga:'Манга',ranobe:'Ранобэ',book:'Книги',music:'Музыка',movie:'Фильмы',tv:'Сериалы',video:'Видео',image:'Фото',translation:'Переводы'};
const MEDIA=/\.(mp4|m4v|webm|mkv|mov|mp3|m4a|aac|ogg|opus|flac|wav|jpg|jpeg|png|webp|gif|avif|pdf|epub|fb2|cbz|zip|txt|srt|vtt)$/i;
export const fileKind=name=>/\.(mp4|m4v|webm|mkv|mov)$/i.test(name)?'video':/\.(mp3|m4a|aac|ogg|opus|flac|wav)$/i.test(name)?'audio':/\.(jpg|jpeg|png|webp|gif|avif)$/i.test(name)?'image':/\.pdf$/i.test(name)?'pdf':'file';

function database(){
 return new Promise((resolve,reject)=>{const r=indexedDB.open(DB,1);r.onupgradeneeded=()=>r.result.createObjectStore(STORE);r.onerror=()=>reject(r.error);r.onsuccess=()=>resolve(r.result);});
}
async function stored(value){
 if(!globalThis.indexedDB)return null;const db=await database();
 try{return await new Promise((resolve,reject)=>{const write=value!==undefined,tx=db.transaction(STORE,write?'readwrite':'readonly'),store=tx.objectStore(STORE);const r=write?(value===null?store.delete(KEY):store.put(value,KEY)):store.get(KEY);let out;r.onsuccess=()=>{out=r.result;};tx.oncomplete=()=>resolve(write?value:out||null);tx.onerror=()=>reject(tx.error);});}
 finally{db.close();}
}
export const canPickFolder=()=>typeof globalThis.showDirectoryPicker==='function';
const browserStorage=()=>!!navigator.storage?.getDirectory;

// The chosen folder, or the browser's own storage when no folder can be picked.
async function root({ask=false}={}){
 const handle=await stored().catch(()=>null);
 if(handle){
  let permission=await handle.queryPermission({mode:'readwrite'}).catch(()=>'denied');
  if(permission!=='granted'&&ask)permission=await handle.requestPermission({mode:'readwrite'}).catch(()=>'denied');
  return permission==='granted'?handle:null;
 }
 if(!canPickFolder()&&browserStorage()&&localStorage.getItem('mediavault_device_storage')==='browser'){
  const base=await navigator.storage.getDirectory();return base.getDirectoryHandle('MediaVault',{create:true});
 }
 return null;
}
export async function deviceFolderState(){
 const handle=await stored().catch(()=>null);
 if(handle)return {mode:'folder',name:handle.name,ready:await handle.queryPermission({mode:'readwrite'}).catch(()=>'denied')==='granted'};
 if(!canPickFolder()&&browserStorage()&&localStorage.getItem('mediavault_device_storage')==='browser')return {mode:'browser',name:'Память браузера',ready:true};
 return {mode:'none',name:'',ready:false,canPick:canPickFolder(),canStore:browserStorage()};
}
export async function chooseDeviceFolder(){
 if(canPickFolder()){const handle=await showDirectoryPicker({id:'mediavault-library',mode:'readwrite'});await stored(handle);return deviceFolderState();}
 if(!browserStorage())throw Error('Этот браузер не умеет хранить файлы для сайта.');
 await navigator.storage.persist?.().catch(()=>false);
 localStorage.setItem('mediavault_device_storage','browser');return deviceFolderState();
}
export async function reconnectDeviceFolder(){await root({ask:true});return deviceFolderState();}
export async function forgetDeviceFolder(){await stored(null).catch(()=>{});localStorage.removeItem('mediavault_device_storage');}

const clean=value=>String(value||'').replace(/[\\/:*?"<>|\u0000-\u001f]+/g,' ').replace(/\s+/g,' ').trim().slice(0,120)||'Без названия';
// Saves into <folder>/<Kind>/<Title>/<file>. A Blob or a URL; URLs stream
// straight to disk. Returns false when no folder is set, so callers can fall
// back to the browser's ordinary download.
export async function saveToDevice(source,name,{kind='video',title=''}={}){
 const base=await root().catch(()=>null);if(!base)return false;
 let dir=await base.getDirectoryHandle(KIND_FOLDERS[kind]||'Разное',{create:true});
 if(title)dir=await dir.getDirectoryHandle(clean(title),{create:true});
 const file=await dir.getFileHandle(clean(name),{create:true}),writer=await file.createWritable();
 try{
  if(typeof source==='string'){const response=await fetch(source,{credentials:'omit'});if(!response.ok||!response.body)throw Error('Источник не отдал файл.');await response.body.pipeTo(writer);}
  else{await writer.write(source);await writer.close();}
  dispatchEvent(new Event('mediavault-device-library'));return true;
 }catch(error){await writer.abort?.().catch(()=>{});throw error;}
}
// Two levels deep: kind folders, then title folders (or loose files).
export async function listDeviceLibrary(){
 const base=await root().catch(()=>null);if(!base)return [];
 const titles=[];
 for await (const [kindName,kindHandle] of base.entries()){
  if(kindHandle.kind!=='directory')continue;
  const kind=Object.entries(KIND_FOLDERS).find(([,label])=>label===kindName)?.[0]||'video';
  const loose=[];
  for await (const [name,handle] of kindHandle.entries()){
   if(handle.kind==='file'){if(MEDIA.test(name))loose.push({name,handle});continue;}
   const files=[];for await (const [fileName,fileHandle] of handle.entries())if(fileHandle.kind==='file'&&MEDIA.test(fileName))files.push({name:fileName,handle:fileHandle});
   if(files.length)titles.push({id:kindName+'/'+name,kind,folder:kindName,title:name,files:files.sort((a,b)=>a.name.localeCompare(b.name,'ru',{numeric:true}))});
  }
  if(loose.length)titles.push({id:kindName+'/',kind,folder:kindName,title:kindName,files:loose.sort((a,b)=>a.name.localeCompare(b.name,'ru',{numeric:true}))});
 }
 return titles.sort((a,b)=>a.title.localeCompare(b.title,'ru'));
}

const kindOf=name=>/\.(mp4|m4v|webm|mkv|mov)$/i.test(name)?'video':/\.(mp3|m4a|aac|ogg|opus|flac|wav)$/i.test(name)?'music':/\.(jpg|jpeg|png|webp|gif|avif)$/i.test(name)?'image':/\.cbz$/i.test(name)?'manga':/\.(epub|fb2|pdf|txt)$/i.test(name)?'book':'video';
function download(source,name){
 const url=typeof source==='string'?source:URL.createObjectURL(source),a=document.createElement('a');
 a.href=url;a.download=name||'';a.rel='noreferrer';document.body.append(a);a.click();a.remove();
 if(typeof source!=='string')setTimeout(()=>URL.revokeObjectURL(url),120000);
}
// Every «На устройство» save goes through here: into the chosen folder when
// there is one, otherwise the browser's ordinary download.
export async function deliverFile(source,name,{kind,title=''}={}){
 try{if(await saveToDevice(source,name,{kind:kind||kindOf(name),title}))return 'folder';}catch(error){console.warn('Папка на устройстве недоступна:',error);}
 download(source,name);return 'download';
}
