import {useEffect} from 'react';
import {contiguousBufferEnd} from './watch-quality.js';

// The small moving control updates on the compositor clock; the episode shelf,
// menus and metadata do not need a React render for every animation frame.
export default function useSmoothTimeline(media,input,source){
 useEffect(()=>{
  const video=media.current,node=input.current;if(!video||!node)return;
  let frame=0,dragging=false,last=0;
  const draw=now=>{frame=0;if(now-last>=32&&!dragging&&Number.isFinite(video.duration)&&video.duration>0){last=now;const p=Math.min(100,video.currentTime/video.duration*100),b=contiguousBufferEnd(video.buffered,video.currentTime)/video.duration*100;node.value=String(video.currentTime);node.style.setProperty('--played',p+'%');node.style.setProperty('--buffered',Math.max(p,b)+'%');}if(!video.paused&&!document.hidden)frame=requestAnimationFrame(draw);};
  const schedule=()=>{if(!frame)frame=requestAnimationFrame(draw);},down=()=>{dragging=true;},up=()=>{dragging=false;schedule();};
  for(const name of ['play','pause','timeupdate','progress','seeked','loadedmetadata'])video.addEventListener(name,schedule);
  node.addEventListener('pointerdown',down);window.addEventListener('pointerup',up);window.addEventListener('pointercancel',up);document.addEventListener('visibilitychange',schedule);schedule();
  return()=>{cancelAnimationFrame(frame);for(const name of ['play','pause','timeupdate','progress','seeked','loadedmetadata'])video.removeEventListener(name,schedule);node.removeEventListener('pointerdown',down);window.removeEventListener('pointerup',up);window.removeEventListener('pointercancel',up);document.removeEventListener('visibilitychange',schedule);};
 },[media,input,source]);
}
