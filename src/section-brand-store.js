import {useEffect,useRef,useSyncExternalStore} from 'react';

// The library section shown in the navbar once its rail scrolls away.
let current=null,activeOwner=null;
const listeners=new Set();
export function publishSectionBrand(value,owner=null){if(!value&&owner&&activeOwner!==owner)return;activeOwner=owner;current=value;for(const fn of listeners)fn();}
export const useSectionBrand=()=>useSyncExternalStore(fn=>{listeners.add(fn);return()=>listeners.delete(fn);},()=>current,()=>null);

/** Publishes {sections, active, onPick} while the `rail` element is scrolled above the navbar. */
export function useSectionBrandFor(rail,{sections,active,onPick,enabled=true}){
 const owner=useRef(Symbol()).current;
 const latest=useRef(null),hidden=useRef(false),handler=useRef(onPick),pick=useRef(id=>handler.current?.(id)).current;
 handler.current=onPick;latest.current={sections,active,onPick:pick};
 const key=sections.map(([id,label])=>id+':'+label).join('|')+'#'+active;
 useEffect(()=>{if(hidden.current)publishSectionBrand({...latest.current},owner);},[key]);
 useEffect(()=>{
  const node=rail;
  if(!enabled||!node){publishSectionBrand(null,owner);return;}
  const observer=new IntersectionObserver(([entry])=>{
   hidden.current=node.getClientRects().length>0&&entry.boundingClientRect.height>0&&!entry.isIntersecting&&entry.boundingClientRect.bottom<=(entry.rootBounds?.top??80);
   publishSectionBrand(hidden.current?{...latest.current}:null,owner);
  },{rootMargin:'-80px 0px 0px 0px'});
  observer.observe(node);
  return()=>{observer.disconnect();hidden.current=false;publishSectionBrand(null,owner);};
 },[rail,enabled]);
}
