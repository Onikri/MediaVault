import {useEffect,useRef,useState} from 'react';
import {openChapter,openRangeArchive} from './zip-reader.js';
export default function HoverPreview({item,actions,children}){
 const host=useRef(null),[active,setActive]=useState(false),[sources,setSources]=useState([]),[index,setIndex]=useState(0),held=useRef(false),touch=useRef(null),timer=useRef(null);
 const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches,saveData=navigator.connection?.saveData===true;
 const enabled=!reduced&&!saveData&&(item.motionArtwork||item.category==='manga'&&(item.chunks?.length||item.onlinePages));
 useEffect(()=>{if(!active||!enabled)return;const abort=new AbortController();let urls=[],closed=false;setSources([]);setIndex(0);
  (async()=>{if(item.motionArtwork){const blob=await actions.readArtwork(item.motionArtwork,{signal:abort.signal});if(closed)return;urls=[URL.createObjectURL(blob)];setSources(urls);}
   else{const entries=item.onlinePages?await openChapter(item,actions.readWhole,actions.readRange,abort.signal):await openRangeArchive(item,actions.readRange,abort.signal);for(const e of entries.slice(0,6)){const b=await e.async('blob');if(closed)return;if(b.size>5*1024*1024)break;urls.push(URL.createObjectURL(b));}setSources([...urls]);}})().catch(()=>{});
  return()=>{closed=true;abort.abort();for(const url of urls)URL.revokeObjectURL(url);};
 },[active,enabled,item.id,actions.readArtwork,actions.readRange,actions.readWhole]);
 useEffect(()=>{if(!active||sources.length<2)return;const interval=setInterval(()=>setIndex(n=>(n+1)%sources.length),750);return()=>clearInterval(interval);},[sources,active]);
 useEffect(()=>()=>clearTimeout(timer.current),[]);
 return <span ref={host} className={'hover-preview'+(active&&sources.length?' is-previewing':'')} onPointerEnter={e=>{if(enabled&&e.pointerType!=='touch')timer.current=setTimeout(()=>setActive(true),260);}} onPointerLeave={()=>{clearTimeout(timer.current);setActive(false);}} onPointerDown={e=>{held.current=false;if(enabled&&e.pointerType==='touch'){touch.current={x:e.clientX,y:e.clientY};timer.current=setTimeout(()=>{held.current=true;setActive(true);},450);}}} onPointerMove={e=>{if(e.pointerType==='touch'&&!held.current&&touch.current&&Math.hypot(e.clientX-touch.current.x,e.clientY-touch.current.y)>10)clearTimeout(timer.current);}} onPointerUp={()=>{clearTimeout(timer.current);setActive(false);}} onPointerCancel={()=>{clearTimeout(timer.current);setActive(false);}} onClickCapture={e=>{if(held.current){e.preventDefault();e.stopPropagation();held.current=false;}}} onContextMenu={e=>{if(held.current)e.preventDefault();}}>{children}{active&&sources.length>0&&(item.motionArtwork?<video className="hover-motion" src={sources[0]} autoPlay muted loop playsInline/>:<span className="manga-page-stack" aria-hidden="true"><i/><i/><img key={index} src={sources[index]} alt=""/><b className="page-curl"/></span>)}</span>;
}
