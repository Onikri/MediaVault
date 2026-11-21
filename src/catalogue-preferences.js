import {useSyncExternalStore} from 'react';

const key='mediavault_catalogue_announcements_v1';
const eventName='mediavault:catalogue-preferences';
let fallback=false;

function includeAnnouncements(){
 try{return localStorage.getItem(key)==='1';}catch{return fallback;}
}

function subscribe(listener){
 addEventListener(eventName,listener);
 addEventListener('storage',listener);
 return ()=>{
  removeEventListener(eventName,listener);
  removeEventListener('storage',listener);
 };
}

export function useCatalogueAnnouncements(){
 return useSyncExternalStore(subscribe,includeAnnouncements,()=>false);
}

export function setCatalogueAnnouncements(visible){
 fallback=visible;
 try{localStorage.setItem(key,visible?'1':'0');}catch{}
 dispatchEvent(new Event(eventName));
}
