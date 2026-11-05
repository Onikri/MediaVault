import {useEffect,useRef,useState} from 'react';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import './chapter-scrub.css';

export function chapterPreviewSamples(total,connection=globalThis.navigator?.connection){
 const limit=connection?.saveData||/2g/.test(connection?.effectiveType||'')?0:connection?.effectiveType==='3g'||Number(connection?.downlink)>0&&connection.downlink<3?5:8;
 const count=Math.min(Math.max(0,total),limit);
 return Array.from({length:count},(_,i)=>count<2?0:Math.round(i*(total-1)/(count-1)));
}
// Motion's keyed slideshow/AnimatePresence pattern (MIT):
// https://motion.dev/docs/react-animate-presence. Only two sheets animate.
const empty=Object.freeze([]);
export default function ChapterScrubPreview({pages=empty,fallback,loadPage,loadedPage,formatLabel=n=>'Страница '+(n+1)}){
 const [position,setPosition]=useState(0),[current,setCurrent]=useState(null),[direction,setDirection]=useState(1),previous=useRef(null),reduce=useReducedMotion(),generation=useRef(0),cache=useRef(new Map()),loader=useRef(loadPage);loader.current=loadPage;
 const target=pages[Math.min(pages.length-1,Math.max(0,Math.floor(position*pages.length)))];
 useEffect(()=>{generation.current++;cache.current.clear();setCurrent(null);},[pages]);
 useEffect(()=>{if(target===undefined)return;let closed=false;const request=++generation.current;
  const resolve=async()=>{try{let value=cache.current.get(target);if(!value){value=await (loader.current?loader.current(target):target);if(typeof value!=='string')return;const image=new Image();image.referrerPolicy='no-referrer';image.src=value;await image.decode();if(closed)return;cache.current.set(target,value);}if(!closed&&request===generation.current){setDirection(pages.indexOf(target)>=pages.indexOf(previous.current)?1:-1);previous.current=target;setCurrent({page:target,source:value});}}catch{}};
  const timer=setTimeout(resolve,65);return()=>{closed=true;clearTimeout(timer);};
 },[target,pages]);
 return <span className="chapter-scrub-preview" onPointerMove={event=>{if(event.pointerType==='touch')return;const r=event.currentTarget.getBoundingClientRect();setPosition(Math.max(0,Math.min(.999,(event.clientX-r.left)/r.width)));}} onPointerLeave={()=>setPosition(0)}>
 {fallback}<AnimatePresence initial={false} custom={direction}>{current&&<motion.img key={current.source} className="chapter-scrub-sheet" src={current.source} alt={formatLabel(current.page)} custom={direction} initial={reduce?false:{opacity:0,x:direction*12,y:5,rotate:direction*.8,scale:.98}} animate={{opacity:1,x:0,y:0,rotate:0,scale:1}} exit={reduce?{opacity:0}:{opacity:0,x:-direction*8,y:-12,scale:.98}} transition={{type:'spring',stiffness:390,damping:32}}/>}</AnimatePresence>
 {current&&<small className="chapter-scrub-page">{loadedPage?loadedPage(current.page):formatLabel(current.page)}</small>}
 </span>;
}
