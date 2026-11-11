import {useEffect,useState} from 'react';
import {startupBufferReady} from './watch-quality.js';

export default function usePlaybackHealth(ref,source,onError,autoPlay=false,startBuffer=0){
 const [phase,setPhase]=useState('loading'),[delayed,setDelayed]=useState(false),[dismissed,setDismissed]=useState(false);
 useEffect(()=>{
  const video=ref.current;if(!video||!source)return;
  let closed=false,lastTime=-1,lastProgress=performance.now(),started=performance.now(),attempted=false,reported=false,bufferWaitStart=null;
  setPhase('loading');setDelayed(false);setDismissed(false);
  const recovered=()=>{reported=false;lastProgress=performance.now();setDismissed(false);};
  const update=()=>{if(closed)return;if(video.readyState>=2){if(!video.paused)recovered();setPhase(video.paused?'paused':'playing');}};
  const ready=()=>{update();if(autoPlay&&!attempted){bufferWaitStart??=performance.now();if(!startupBufferReady(video,startBuffer,performance.now()-bufferWaitStart)){setPhase('loading');return;}attempted=true;video.play().catch(e=>{if(!closed&&e.name==='NotAllowedError')setPhase('blocked');});}};
  const waiting=()=>{if(!video.paused)setPhase('buffering');};
  const seeking=()=>{lastProgress=performance.now();};
  const visible=()=>{if(!document.hidden){lastProgress=performance.now();started=lastProgress;}};
  document.addEventListener('visibilitychange',visible);
  const events={loadeddata:ready,canplay:ready,...(startBuffer?{progress:ready}:{}),playing:update,pause:update,waiting,stalled:waiting,seeking,seeked:update};
  for(const [name,fn] of Object.entries(events))video.addEventListener(name,fn);
  const show=setTimeout(()=>!closed&&setDelayed(true),450);
  const timer=setInterval(()=>{
   if(document.hidden)return;
   const now=performance.now();if(Math.abs(video.currentTime-lastTime)>.05){const resumed=reported;lastTime=video.currentTime;lastProgress=now;reported=false;if(resumed&&!video.paused){setPhase('playing');setDismissed(false);}}
   if(autoPlay&&!attempted&&video.readyState>=2)ready();
   if(video.readyState>=2&&!video.paused&&now-lastProgress>1500)setPhase('buffering');
   const initial=video.readyState<2&&now-started>25000,stalled=!video.paused&&!video.seeking&&now-lastProgress>25000;
   // A temporary stall must not make the resolver replace a healthy stream.
   if(!reported&&(initial||stalled)){reported=true;setDismissed(false);setPhase('failed');}
  },1000);
  if(video.readyState>=2)ready();
  return()=>{closed=true;clearTimeout(show);clearInterval(timer);document.removeEventListener('visibilitychange',visible);for(const [name,fn] of Object.entries(events))video.removeEventListener(name,fn);};
 },[ref,source,autoPlay,startBuffer]);
 return {phase,visible:!dismissed&&delayed&&['loading','buffering','blocked','failed'].includes(phase),dismiss:()=>setDismissed(true),retry:()=>{setDismissed(false);const v=ref.current;if(v)v.play().then(()=>setPhase('playing')).catch(()=>setPhase('blocked'));}};
}
