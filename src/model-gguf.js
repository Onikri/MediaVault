import {createSHA256} from 'hash-wasm';
import {readModelFile,writeModelFile,removeModelFile,writableModelFolder} from './model-folder.js';

// Files/Blobs stream to the verifier and runtime; a two-GB GGUF is never
// converted into a second full ArrayBuffer just to copy it to a chosen disk.
export async function cachedGguf(url,model,manager,progress=()=>{},{read=readModelFile,write=writeModelFile,remove=removeModelFile,writable=writableModelFolder}={}){
 const disk=await read(url);let source;
 if(disk)source={size:disk.size,open:async()=>[disk],remove:()=>remove(url)};
 else source=await manager.downloadModel(url,{progressCallback:({loaded,total})=>progress('Загрузка весов · '+Math.round(loaded/1e6)+' / '+Math.round((total||model.bytes)/1e6)+' МБ · '+Math.round(loaded/(total||model.bytes)*100)+'%',{loaded,total:total||model.bytes})});
 if(source.size!==model.bytes){await source.remove();throw Error('Размер весов не совпадает с манифестом. Повтори загрузку модели.');}
 progress('Проверка SHA-256 весов на диске');const blobs=await source.open(),hash=await createSHA256();hash.init();
 for(const blob of blobs){const reader=blob.stream().getReader();try{for(;;){const{done,value}=await reader.read();if(done)break;hash.update(value);}}finally{reader.releaseLock();}}
 if(hash.digest()!==model.sha){await source.remove();throw Error('Веса не прошли проверку SHA-256. Повтори загрузку выбранной модели.');}
 if(!disk&&await writable())await write(url,new Blob(blobs));
 return {size:source.size,open:async()=>blobs,remove:()=>source.remove()};
}
