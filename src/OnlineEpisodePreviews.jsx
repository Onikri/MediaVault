import {useEffect,useRef} from 'react';
import {captureEpisodePreview,readEpisodePreview} from './episode-preview-cache.js';
import {onlineEpisodeId} from './watch-session.js';

// One low-quality decoder and one short-lived lease at a time. Starting actual
// playback aborts this work immediately, so thumbnails never compete with it.
export async function frame(source,type,signal,multiple=false,onPartial){
 const video=document.createElement('video');video.muted=true;video.playsInline=true;video.crossOrigin='anonymous';video.preload='auto';
 let hls,timer,abortListener,stopped=false;
 try{
  return await new Promise((resolve,reject)=>{
   let target=0,index=0,targets=[],images=[];
   const fail=()=>resolve('');
   const capture=()=>{if(video.readyState<2||Math.abs(video.currentTime-target)>=1)return;const image=captureEpisodePreview(video);if(!image)return;images.push(image);if(images.length>1)onPartial?.([...images]);if(++index>=targets.length)resolve(multiple?images:images[0]);else{target=targets[index];video.currentTime=target;}};
   video.onloadedmetadata=()=>{targets=(multiple?[.08,.27,.47,.68]:[.08]).map(f=>Math.max(0,Math.min((video.duration||0)-.1,(video.duration||0)*f)));target=targets[0];if(target>0)video.currentTime=target;};
   video.onseeked=capture;video.onloadeddata=capture;video.onerror=fail;
   abortListener=fail;signal.addEventListener('abort',fail,{once:true});timer=setTimeout(fail,multiple?30000:15000);
   if(signal.aborted){fail();return;}
   if(type==='hls')import('hls.js').then(({default:Hls})=>{
    if(signal.aborted||stopped){fail();return;}
    if(!Hls.isSupported()){video.src=source;return;}
    hls=new Hls({autoStartLoad:false,startLevel:0,maxBufferLength:4,maxMaxBufferLength:8,backBufferLength:0});
    hls.on(Hls.Events.MANIFEST_PARSED,()=>{hls.autoLevelCapping=0;hls.startLoad();});
    hls.on(Hls.Events.ERROR,(_,data)=>{if(data.fatal)fail();});hls.loadSource(source);hls.attachMedia(video);
   }).catch(reject);
   else video.src=source;
  });
 }finally{stopped=true;clearTimeout(timer);signal.removeEventListener('abort',abortListener);hls?.destroy();video.pause();video.removeAttribute('src');video.load();}
}

export default function OnlineEpisodePreviews({entries,active,service,sourceUrl,identity,season,userId,onPreview}){
 const client=useRef('previews-'+crypto.randomUUID()),publish=useRef(onPreview);publish.current=onPreview;
 useEffect(()=>{
  if(!active||!sourceUrl||navigator.connection?.saveData)return;
  const abort=new AbortController();
  (async()=>{for(const entry of entries){
   if(abort.signal.aborted)return;
   const key=onlineEpisodeId(identity,entry.season||season,entry.number)+':'+(userId||'anonymous');
   const cached=await readEpisodePreview(key);if(cached){publish.current(entry.number,cached);continue;}
   let lease;
   try{
    const data=await service.request('/online/prepare',{method:'POST',body:{url:entry.url,referer:sourceUrl,kind:'video',quality:'best',clientId:client.current},signal:abort.signal});lease=data.id;
    if(abort.signal.aborted)continue;
    const image=await frame(service.server.replace(/\/$/,'')+data.url,data.type,abort.signal);
    if(image&&!abort.signal.aborted)publish.current(entry.number,image);
   }catch{if(abort.signal.aborted)return;}
   finally{if(lease)service.request('/online/'+lease,{method:'DELETE',keepalive:true}).catch(()=>{});}
  }})();
  return()=>abort.abort();
 },[entries,active,sourceUrl,identity,season,userId,service.server]);
 return null;
}
