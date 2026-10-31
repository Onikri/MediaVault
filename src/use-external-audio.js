import {useEffect,useRef,useState} from 'react';
import useVideoStream from './use-video-stream.js';
export default function useExternalAudio(main,source,type,volume,muted,offset=0,onError){
 const ref=useRef(null),[ready,setReady]=useState(false),report=useRef(onError);report.current=onError;
 useVideoStream(ref,source,type,error=>report.current?.(error),{preview:true});
 useEffect(()=>{const video=main.current,audio=ref.current;setReady(false);if(!source||!video||!audio)return;
  let closed=false;
  const seek=()=>{if(Number.isFinite(audio.duration)&&Math.abs(audio.currentTime-video.currentTime-offset)>.4)try{audio.currentTime=Math.max(0,Math.min(audio.duration,video.currentTime+offset));}catch{}};
  const play=()=>{seek();if(!video.paused&&audio.paused)audio.play().catch(e=>{if(!closed&&e.name!=='AbortError')report.current?.(Error('Не удалось включить отдельную озвучку. Включён исходный звук.'));});};
  const pause=()=>audio.pause(),rate=()=>{audio.playbackRate=video.playbackRate;},loaded=()=>{setReady(true);rate();play();};
  const sync=()=>{if(Math.abs(audio.currentTime-video.currentTime-offset)>.4)seek();if(video.paused!==audio.paused){if(video.paused)pause();else play();}};
  video.addEventListener('play',play);video.addEventListener('pause',pause);video.addEventListener('seeking',seek);video.addEventListener('ratechange',rate);video.addEventListener('timeupdate',sync);audio.addEventListener('loadedmetadata',loaded);audio.addEventListener('canplay',play);
  return()=>{closed=true;audio.pause();video.removeEventListener('play',play);video.removeEventListener('pause',pause);video.removeEventListener('seeking',seek);video.removeEventListener('ratechange',rate);video.removeEventListener('timeupdate',sync);audio.removeEventListener('loadedmetadata',loaded);audio.removeEventListener('canplay',play);};
 },[source,offset]);
 useEffect(()=>{if(ref.current){ref.current.volume=Math.max(0,Math.min(1,volume));ref.current.muted=muted;}},[source,volume,muted]);
 return {ref,ready};
}
