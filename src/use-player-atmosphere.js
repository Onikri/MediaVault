import {useEffect,useState} from 'react';

// Tiny ambient sampling only. Pause effects live in their isolated component.
export default function usePlayerAtmosphere(videoRef,source,ambient=true){
 const [scene,setScene]=useState({color:'150 157 166'});
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
 return scene;
}
