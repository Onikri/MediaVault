import {useEffect,useRef,useState} from 'react';
import useVideoStream from './use-video-stream.js';
const frames=new Map();
addEventListener('mediavault-locked',()=>frames.clear());
const clock=t=>Math.floor(t/60)+':'+String(Math.floor(t%60)).padStart(2,'0');
export default function TimelinePreview({source,type,point,left}){
 const video=useRef(null),[image,setImage]=useState(''),[failed,setFailed]=useState(false),target=Math.max(0,Math.floor(point)),key=source+'|'+target;
 useVideoStream(video,source,type,()=>setFailed(true),{preview:true});
 useEffect(()=>{let closed=false,timer;setImage(frames.get(key)||'');if(frames.has(key))return;const v=video.current;if(!v)return;
  function seek(){try{if(Number.isFinite(v.duration)&&v.duration>0)v.currentTime=Math.min(target,v.duration-.05);}catch{}}
  function capture(){if(closed||Math.abs(v.currentTime-target)>.35||v.readyState<2)return;try{const c=document.createElement('canvas');c.width=176;c.height=99;c.getContext('2d').drawImage(v,0,0,176,99);const value=c.toDataURL('image/jpeg',.65);frames.set(key,value);while(frames.size>120)frames.delete(frames.keys().next().value);setImage(value);}catch{setFailed(true);}}
  v.addEventListener('loadedmetadata',seek);v.addEventListener('seeked',capture);timer=setTimeout(()=>{seek();capture();},160);return()=>{closed=true;clearTimeout(timer);v.removeEventListener('loadedmetadata',seek);v.removeEventListener('seeked',capture);};
 },[target,source]);
 return <output className="mv-timeline-frame" style={{left:left+'%'}}><video ref={video} src={type==='hls'?undefined:source} crossOrigin="anonymous" playsInline muted preload="metadata" hidden style={{display:'none'}} aria-hidden="true"/>{image?<img src={image} alt="Кадр при перемотке"/>:<span>{failed?'Кадр недоступен':'Загружаем кадр…'}</span>}<small>{clock(point)}</small></output>;
}
