import {useEffect,useState} from 'react';
import {imageURL,profileArtwork} from './title-metadata.js';

// Shared per unlocked library. Never persist decrypted images or keys in storage.
const blobs=new Map();
const images=new Map();
let scope='';
export function clearArtworkCache(next=''){
  if(scope===next)return;scope=next;
  for(const value of blobs.values())if(value.url)URL.revokeObjectURL(value.url);
  blobs.clear();
  images.clear();
}
async function externalImage(url,{signal}={}){
  if(!images.has(url))images.set(url,boundedRead(async()=>{
    const server=globalThis.window?.MEDIA_VAULT_CONFIG?.importServerUrl;
    const current=url.replace(/^https:\/\/(?:desu\.)?shikimori\.one\//,match=>match.replace('.one/','.io/'));
    const targets=server?[server+'/artwork?'+new URLSearchParams({url:current}),current]:[current];
    for(const target of targets){
      try{
        const response=await fetch(target,{signal:AbortSignal.timeout(8000),credentials:'omit',referrerPolicy:'no-referrer'});
        if(!response.ok||!/^image\/(?:jpeg|png|webp|avif)/i.test(response.headers.get('content-type')||'')||Number(response.headers.get('content-length'))>8*1024*1024)throw Error();
        const reader=response.body.getReader(),parts=[];let size=0;
        try{for(;;){const {done,value}=await reader.read();if(done)break;size+=value.byteLength;if(size>8*1024*1024)throw Error();parts.push(value);}}finally{await reader.cancel().catch(()=>{});}
        return new Blob(parts,{type:response.headers.get('content-type').split(';')[0]});
      }catch{}
    }
    throw Error('Изображение пока недоступно.');
  }).catch(error=>{images.delete(url);throw error;}));
  const blob=await images.get(url);signal?.throwIfAborted();return blob;
}
let activeReads=0;const waiting=[];
async function boundedRead(work){
  if(activeReads>=4)await new Promise(resolve=>waiting.push(resolve));else activeReads++;
  try{return await work();}finally{const next=waiting.shift();if(next)next();else activeReads--;}
}
export function useArtwork(url,profile,readArtwork,libraryId,enabled=true){
  const asset=profile?.artwork?.[url],key=asset?.fileId,remote=imageURL(url);
  const identity=String(libraryId||'')+':'+(key||remote),[result,setResult]=useState({identity:'',source:''}),[retry,setRetry]=useState(0);
  useEffect(()=>{
    if(!enabled)return;
    let closed=false,local='',timer;const generation=scope;
    const publish=source=>{if(!closed)setResult({identity,source});};
    if(!asset){
      publish(remote);if(!remote)return;
      externalImage(remote).then(blob=>{if(!closed){local=URL.createObjectURL(blob);publish(local);}}).catch(()=>{});
      return()=>{closed=true;if(local)URL.revokeObjectURL(local);};
    }
    if(!blobs.has(key)){
      const entry={promise:boundedRead(async()=>{
        if(generation!==scope)throw new DOMException('Library changed','AbortError');
        const blob=await readArtwork(asset);if(generation!==scope)return '';entry.url=URL.createObjectURL(blob);return entry.url;
      })};blobs.set(key,entry);entry.promise.catch(()=>{if(blobs.get(key)===entry)blobs.delete(key);});
    }
    const cached=blobs.get(key);if(cached.url)publish(cached.url);
    cached.promise.then(publish).catch(()=>{
      if(closed)return;
      if(remote){publish(remote);externalImage(remote).then(blob=>{if(!closed){local=URL.createObjectURL(blob);publish(local);}}).catch(()=>{});}
      if(retry<2)timer=setTimeout(()=>setRetry(n=>n+1),retry?1800:500);
    });
    return()=>{closed=true;clearTimeout(timer);if(local)URL.revokeObjectURL(local);};
  },[identity,readArtwork,retry,enabled]);
  if(!enabled)return '';
  return result.identity===identity?result.source:asset?blobs.get(key)?.url||'':remote;
}
export async function fetchArtwork(profile,{signal}={}){
  const images=[],failed=[];
  for(const url of profileArtwork(profile).filter(url=>!profile.artwork?.[url]).slice(0,48)){
    signal?.throwIfAborted();
    try{
      let blob=await externalImage(url,{signal});
      // Keep original high-resolution stills when small; bound very large art
      // to 2560px with a high-quality WebP copy before encrypting it in Drive.
      if(blob.size>2*1024*1024){
        const bitmap=await createImageBitmap(blob);
        try{
          const width=Math.min(2560,bitmap.width),height=Math.round(bitmap.height*width/bitmap.width),canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;
          canvas.getContext('2d',{alpha:false}).drawImage(bitmap,0,0,width,height);
          blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/webp',.9));
        }finally{bitmap.close();}
        if(!blob||blob.size>2*1024*1024)throw Error();
      }
      if(blob.size)images.push({url,blob});
    }catch(error){signal?.throwIfAborted();failed.push(url);}
  }
  return {images,failed};
}
