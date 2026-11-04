import {useEffect,useState} from 'react';
import {TITLE_UPSCALE} from './title-upscale-model.js';
let worker,sequence=0;const waiting=new Map();
function infer(bitmap,modelUrl){
 if(!worker){worker=new Worker(new URL('./title-upscale.worker.js',import.meta.url),{type:'module'});worker.onmessage=({data})=>{const pending=waiting.get(data.id);if(!pending)return;waiting.delete(data.id);if(data.type==='error')pending.reject(Error(data.message));else pending.resolve(data);};worker.onerror=()=>{for(const p of waiting.values())p.reject(Error('Обработчик фона недоступен.'));waiting.clear();worker.terminate();worker=null;};}
 const id=++sequence;return new Promise((resolve,reject)=>{waiting.set(id,{resolve,reject});worker.postMessage({id,bitmap,modelUrl},[bitmap]);});
}
export default function useTitleUpscale(source,original,server,enabled,privateImage=false){
 const [result,setResult]=useState(null);
 useEffect(()=>{
  setResult(null);if(!source||!enabled||!server||!globalThis.OffscreenCanvas||navigator.connection?.saveData)return;
  const abort=new AbortController();let own='',timer;
  async function run(){
   try{
    const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(original+'|'+TITLE_UPSCALE.sha256+'|384')))).map(v=>v.toString(16).padStart(2,'0')).join(''),key=location.origin+'/__mv_artwork/'+digest;let cache;
    if(!privateImage)try{cache=await caches.open('mv-public-backgrounds-v1');const hit=await cache.match(key);if(hit){const blob=await hit.blob();if(abort.signal.aborted)return;own=URL.createObjectURL(blob);const image=new Image();image.src=own;await image.decode();if(!abort.signal.aborted)setResult({source:own,cached:true});return;}}catch{}
    const target=source.startsWith('blob:')?source:server+'/artwork?'+new URLSearchParams({url:original});
    const response=await fetch(target,{signal:abort.signal,credentials:'omit'});if(!response.ok||Number(response.headers.get('Content-Length'))>8*1024*1024)throw Error();
    const blob=await response.blob();if(blob.size>8*1024*1024)throw Error();const bitmap=await createImageBitmap(blob);if(abort.signal.aborted){bitmap.close();return;}
    const value=await infer(bitmap,server+'/models/'+TITLE_UPSCALE.file);if(value.type!=='result'||abort.signal.aborted)return;
    own=URL.createObjectURL(value.blob);const image=new Image();image.src=own;await image.decode();if(abort.signal.aborted)return;setResult({...value,source:own});
    if(cache){try{const keys=await cache.keys();for(const old of keys.slice(0,Math.max(0,keys.length-15)))await cache.delete(old);await cache.put(key,new Response(value.blob));}catch{}}
   }catch{}
  }
  timer=setTimeout(run,450);return()=>{clearTimeout(timer);abort.abort();if(own)URL.revokeObjectURL(own);};
 },[source,original,server,enabled,privateImage]);
 return result;
}
