import {useSyncExternalStore} from 'react';
let current=null;
const listeners=new Set();
export function publishTitleNavigation(value){current=value;for(const fn of listeners)fn();}
export const useTitleNavigation=()=>useSyncExternalStore(fn=>{listeners.add(fn);return()=>listeners.delete(fn);},()=>current,()=>null);
export function jumpTitleSection(id){const target=document.getElementById(id)||(id==='titlePlayback'?document.getElementById('titleMaterials'):null);if(!target)return;const header=document.querySelector('.blossom-navbar')?.getBoundingClientRect();scrollTo({top:Math.max(0,scrollY+target.getBoundingClientRect().top-(header?.bottom||78)-22),behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth'});}
