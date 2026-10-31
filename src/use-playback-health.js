import {useEffect,useRef,useState} from 'react';

export default function usePlaybackHealth(ref,source,onError,autoPlay=false){
 const [phase,setPhase]=useState('loading'),[delayed,setDelayed]=useState(false),report=useRef(onError);report.current=onError;
 useEffect(()=>{
  const video=ref.current;if(!video||!source)return;
  let closed=false,lastTime=-1,lastProgress=performance.now(),started=performance.now(),attempted=false,reported=false;
  setPhase('loading');setDelayed(false);
  const update=()=>{if(closed)return;if(video.readyState>=2)setPhase(video.paused?'paused':'playing');};
  const ready=()=>{update();if(autoPlay&&!attempted){attempted=true;video.play().catch(e=>{if(!closed&&e.name==='NotAllowedError')setPhase('blocked');});}};
  const waiting=()=>{if(!video.paused)setPhase('buffering');};
  const seeking=()=>{lastProgress=performance.now();};
  const visible=()=>{if(!document.hidden){lastProgress=performance.now();started=lastProgress;}};
  document.addEventListener('visibilitychange',visible);
  const events={loadeddata:ready,canplay:ready,playing:update,pause:update,waiting,stalled:waiting,seeking,seeked:update};
  for(const [name,fn] of Object.entries(events))video.addEventListener(name,fn);
  const show=setTimeout(()=>!closed&&setDelayed(true),450);
  const timer=setInterval(()=>{
   if(document.hidden)return;
   const now=performance.now();if(Math.abs(video.currentTime-lastTime)>.05){lastTime=video.currentTime;lastProgress=now;}
   if(video.readyState>=2&&!video.paused&&now-lastProgress>1500)setPhase('buffering');
   const initial=video.readyState<2&&now-started>25000,stalled=!video.paused&&!video.seeking&&now-lastProgress>25000;
   if(!reported&&(initial||stalled)){reported=true;setPhase('failed');report.current?.(Error('Источник не начал воспроизведение. Повтори подключение или выбери другую озвучку.'));}
  },1000);
  if(video.readyState>=2)ready();
  return()=>{closed=true;clearTimeout(show);clearInterval(timer);document.removeEventListener('visibilitychange',visible);for(const [name,fn] of Object.entries(events))video.removeEventListener(name,fn);};
 },[ref,source,autoPlay]);
 return {phase,visible:delayed&&['loading','buffering','blocked','failed'].includes(phase),retry:()=>{const v=ref.current;if(v)v.play().then(()=>setPhase('playing')).catch(()=>setPhase('blocked'));}};
}
