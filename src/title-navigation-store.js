import {useSyncExternalStore} from 'react';
let current=null;
const listeners=new Set();
export const TITLE_SECTION_JUMP='mediavault:title-section-jump';
export function publishTitleNavigation(value){current=value;for(const fn of listeners)fn();}
export const useTitleNavigation=()=>useSyncExternalStore(fn=>{listeners.add(fn);return()=>listeners.delete(fn);},()=>current,()=>null);
export function titleSectionTarget(id){
 return document.getElementById(id)||(id==='titlePlayback'?document.getElementById('titleMaterials'):null);
}

export function titleDockBoundary(){
 const header=document.querySelector('.blossom-navbar');
 const dock=header?.querySelector('.title-dock');
 return Math.max(header?.getBoundingClientRect().bottom||78,dock?.getBoundingClientRect().bottom||0)+12;
}

export function jumpTitleSection(id){
 const target=titleSectionTarget(id);
 if(!target)return;
 dispatchEvent(new CustomEvent(TITLE_SECTION_JUMP,{detail:id}));
 scrollTo({
  top:Math.max(0,scrollY+target.getBoundingClientRect().top-titleDockBoundary()),
  behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth'
 });
}
