import {useEffect,useRef,useSyncExternalStore} from 'react';

// The library section shown in the navbar once its rail scrolls away.
let current=null;
const listeners=new Set();
export function publishSectionBrand(value){current=value;for(const fn of listeners)fn();}
export const useSectionBrand=()=>useSyncExternalStore(fn=>{listeners.add(fn);return()=>listeners.delete(fn);},()=>current,()=>null);

/** Publishes {sections, active, onPick} while the `rail` element is scrolled above the navbar. */
export function useSectionBrandFor(rail,{sections,active,onPick,enabled=true}){
 const latest=useRef(null),hidden=useRef(false),handler=useRef(onPick),pick=useRef(id=>handler.current?.(id)).current;
 handler.current=onPick;latest.current={sections,active,onPick:pick};
 const key=sections.map(([id,label])=>id+':'+label).join('|')+'#'+active;
 useEffect(()=>{if(hidden.current)publishSectionBrand({...latest.current});},[key]);
 useEffect(()=>{
  const node=rail;
  if(!enabled||!node){publishSectionBrand(null);return;}
  const observer=new IntersectionObserver(([entry])=>{
   hidden.current=!entry.isIntersecting&&entry.boundingClientRect.top<0;
   publishSectionBrand(hidden.current?{...latest.current}:null);
  },{rootMargin:'-80px 0px 0px 0px'});
  observer.observe(node);
  return()=>{observer.disconnect();hidden.current=false;publishSectionBrand(null);};
 },[rail,enabled]);
}
