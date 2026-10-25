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
  if(!images.has(url))images.set(url,(async()=>{
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
  })().catch(error=>{images.delete(url);throw error;}));
  const blob=await images.get(url);signal?.throwIfAborted();return blob;
}
export function useArtwork(url,profile,readArtwork,libraryId){
  const asset=profile?.artwork?.[url],key=asset?.fileId;
  const [source,setSource]=useState('');
  useEffect(()=>{
    let closed=false;setSource('');
    if(!asset){
      const remote=imageURL(url);setSource(remote);if(!remote)return;
      let local='';externalImage(remote).then(blob=>{if(!closed){local=URL.createObjectURL(blob);setSource(local);}}).catch(()=>{});
      return()=>{closed=true;if(local)URL.revokeObjectURL(local);};
    }
    if(!blobs.has(key)){
      const generation=scope;
      const entry={promise:readArtwork(asset).then(blob=>{
        if(generation!==scope)return '';entry.url=URL.createObjectURL(blob);return entry.url;
      })};blobs.set(key,entry);entry.promise.catch(()=>blobs.delete(key));
    }
    blobs.get(key).promise.then(value=>{if(!closed)setSource(value);}).catch(()=>{});
    return()=>{closed=true;};
  },[url,key,libraryId,readArtwork,!!profile?.savedAt]);
  return source;
}
export async function fetchArtwork(profile,{signal}={}){
  const images=[],failed=[];
  for(const url of profileArtwork(profile).slice(0,48)){
    if(profile.artwork?.[url])continue;signal?.throwIfAborted();
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
