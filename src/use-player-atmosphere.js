import {useEffect,useRef,useState} from 'react';

// Ambient samples are tiny and infrequent. Paused motion moves the actual video:
// no JPEG copies, segmentation edges, duplicate frames or a second decoder.
export default function usePlayerAtmosphere(videoRef,source,playing,rootRef,enabled=true,ambient=true){
 const [scene,setScene]=useState({color:'150 157 166'}),isPlaying=useRef(playing);isPlaying.current=playing;
 useEffect(()=>{
  const video=videoRef.current;if(!video||!source||!ambient)return;
  let timer,closed=false;const canvas=document.createElement('canvas');canvas.width=16;canvas.height=9;
  const context=canvas.getContext('2d',{willReadFrequently:true});
  const sample=()=>{if(closed||document.hidden||video.readyState<2||!video.videoWidth)return;
   try{context.drawImage(video,0,0,16,9);const p=context.getImageData(0,0,16,9).data;let r=0,g=0,b=0,n=0;
    for(let i=0;i<p.length;i+=4){if(Math.max(p[i],p[i+1],p[i+2])<28)continue;r+=p[i];g+=p[i+1];b+=p[i+2];n++;}
    if(n){const color=[r,g,b].map(v=>Math.round(Math.max(45,Math.min(215,v/n)))).join(' ');setScene(old=>old.color===color?old:{color});}
   }catch{clearInterval(timer);}
  };
  const defer=()=>{if(!closed)sample();};video.addEventListener('loadeddata',defer);video.addEventListener('pause',defer);video.addEventListener('seeked',defer);
  timer=setInterval(sample,5000);sample();return()=>{closed=true;clearInterval(timer);video.removeEventListener('loadeddata',defer);video.removeEventListener('pause',defer);video.removeEventListener('seeked',defer);};
 },[source,videoRef,ambient]);
 useEffect(()=>{
  const root=rootRef.current;if(!root||!enabled||matchMedia('(prefers-reduced-motion: reduce), (pointer: coarse)').matches)return;
  let frame=0,target=[0,0],x=0,y=0,box;
  const draw=()=>{frame=0;if(isPlaying.current)target=[0,0];x+=(target[0]-x)*.16;y+=(target[1]-y)*.16;root.style.setProperty('--pan-x',x*2+'px');root.style.setProperty('--pan-y',y*1.2+'px');if(Math.abs(target[0]-x)+Math.abs(target[1]-y)>.01)frame=requestAnimationFrame(draw);};
  const schedule=()=>{if(!frame)frame=requestAnimationFrame(draw);};
  const enter=()=>{box=root.getBoundingClientRect();};
  const move=e=>{if(isPlaying.current||e.pointerType==='touch')return;if(!box)enter();target=[Math.max(-1,Math.min(1,(e.clientX-box.left)/box.width*2-1)),Math.max(-1,Math.min(1,(e.clientY-box.top)/box.height*2-1))];schedule();};
  const reset=()=>{target=[0,0];box=null;schedule();};
  const video=videoRef.current;root.addEventListener('pointerenter',enter);root.addEventListener('pointermove',move);root.addEventListener('pointerleave',reset);video?.addEventListener('play',reset);
  return()=>{cancelAnimationFrame(frame);root.removeEventListener('pointerenter',enter);root.removeEventListener('pointermove',move);root.removeEventListener('pointerleave',reset);video?.removeEventListener('play',reset);root.style.setProperty('--pan-x','0px');root.style.setProperty('--pan-y','0px');};
 },[rootRef,enabled]);
 return scene;
}
