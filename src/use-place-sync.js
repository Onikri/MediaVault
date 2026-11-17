import {useEffect,useState} from 'react';
import {createPlaceSync,PLACES_EVENT} from './place-sync.js';

// A signed-in profile shares its places with its other devices once the
// MediaVault server that keeps them (version 76+) is connected. Guests keep
// their places on the device, as before.
export function usePlaceSync(user,service,workspace){
 const ready=!!user&&service?.status==='connected'&&service.session?.role!=='guest'&&Number(service.session?.serverVersion)>=76;
 useEffect(()=>{
  if(!ready)return;
  const sync=createPlaceSync({user,request:service.request});
  sync.start();
  return()=>sync.stop();
 },[ready,user,service?.request]);
 useEffect(()=>{
  const changed=event=>{if(event.detail?.keys?.some(k=>k.startsWith('h:')))workspace?.reload?.(event.detail.user);};
  addEventListener(PLACES_EVENT,changed);return()=>removeEventListener(PLACES_EVENT,changed);
 },[workspace]);
}
// A component that shows a saved place reads it again when another device
// changed one of its places (keys starting with prefix, e.g. 'r:' or 'w:12345').
export function usePlaceRevision(prefix){
 const [revision,setRevision]=useState(0);
 useEffect(()=>{
  if(!prefix)return;
  const changed=event=>{if(event.detail?.keys?.some(k=>k.startsWith(prefix)))setRevision(v=>v+1);};
  addEventListener(PLACES_EVENT,changed);return()=>removeEventListener(PLACES_EVENT,changed);
 },[prefix]);
 return revision;
}
