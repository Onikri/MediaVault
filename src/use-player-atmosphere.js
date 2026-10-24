import {useEffect,useRef,useState} from 'react';

// Read only decoded frames already held by the player. No extra media requests.
export default function usePlayerAtmosphere(videoRef,source,playing,rootRef){
  const [scene,setScene]=useState({image:'',color:'218 139 91'});
  const raf=useRef(0),target=useRef([0,0]),isPlaying=useRef(playing);isPlaying.current=playing;
  useEffect(()=>{
    const video=videoRef.current;if(!video||!source)return;
    let cancelled=false,timer,frame;
    const sample=()=>{
      if(cancelled||video.readyState<2||!video.videoWidth)return;
      try{
        const canvas=document.createElement('canvas');canvas.width=Math.min(video.videoWidth,video.paused?1280:320);canvas.height=Math.round(canvas.width*video.videoHeight/video.videoWidth);
        const ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(video,0,0,canvas.width,canvas.height);
        const pixels=ctx.getImageData(0,0,canvas.width,canvas.height).data;
        let r=0,g=0,b=0,weight=0;
        for(let i=0;i<pixels.length;i+=64){
          const max=Math.max(pixels[i],pixels[i+1],pixels[i+2]),min=Math.min(pixels[i],pixels[i+1],pixels[i+2]);
          if(max<35||min>225)continue;
          const w=(max-min)/255+.05;r+=pixels[i]*w;g+=pixels[i+1]*w;b+=pixels[i+2]*w;weight+=w;
        }
        // Black opening frames keep the last usable preview instead of replacing it.
        if(weight>30){
          const color=[r,g,b].map(v=>Math.round(Math.min(235,Math.max(65,v/weight*1.25)))).join(' ');
          setScene(previous=>({image:video.paused?canvas.toDataURL('image/jpeg',.82):previous.image,color}));
        }
      }catch{} // Tainted cross-origin video keeps native playback and the default palette.
    };
    const deferred=()=>{clearTimeout(timer);timer=setTimeout(sample,80);};
    // Throttle continuous sampling; pause/seek always get a fresh still.
    let last=0;
    const tick=()=>{const now=performance.now();if(now-last>3500){sample();last=now;}if(!cancelled)frame=video.requestVideoFrameCallback(tick);};
    if(video.requestVideoFrameCallback)frame=video.requestVideoFrameCallback(tick);
    video.addEventListener('loadeddata',deferred);video.addEventListener('pause',deferred);video.addEventListener('seeked',deferred);
    deferred();
    return()=>{cancelled=true;clearTimeout(timer);if(frame)video.cancelVideoFrameCallback?.(frame);video.removeEventListener('loadeddata',deferred);video.removeEventListener('pause',deferred);video.removeEventListener('seeked',deferred);};
  },[source,videoRef]);
  useEffect(()=>{
    const root=rootRef.current;if(!root||matchMedia('(prefers-reduced-motion: reduce)').matches)return;
    let x=0,y=0;
    const move=event=>{if(event.pointerType==='touch')return;const box=root.getBoundingClientRect();if(!isPlaying.current)target.current=[(event.clientX-box.left)/box.width*2-1,(event.clientY-box.top)/box.height*2-1];};
    const reset=()=>{target.current=[0,0];};
    const animate=()=>{if(isPlaying.current)target.current=[0,0];x+=(target.current[0]-x)*.065;y+=(target.current[1]-y)*.065;root.style.setProperty('--pan-x',x*8+'px');root.style.setProperty('--pan-y',y*5+'px');raf.current=requestAnimationFrame(animate);};
    root.addEventListener('pointermove',move);root.addEventListener('pointerleave',reset);raf.current=requestAnimationFrame(animate);
    return()=>{cancelAnimationFrame(raf.current);root.removeEventListener('pointermove',move);root.removeEventListener('pointerleave',reset);root.style.setProperty('--pan-x','0px');root.style.setProperty('--pan-y','0px');};
  },[rootRef]);
  return scene;
}
