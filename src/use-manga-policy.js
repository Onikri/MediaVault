import {useEffect,useSyncExternalStore} from 'react';
import {subscribeMangaPolicy,policyVersion,setMangaPolicy} from './manga-tag-policy.js';

const connections=new Map();
export default function useMangaPolicy(service,enabled=true){
 const version=useSyncExternalStore(subscribeMangaPolicy,policyVersion,policyVersion);
 useEffect(()=>{
  if(!enabled||!service?.server||!service.request)return;
  const key=service.server;let connection=connections.get(key);
  if(!connection){
   connection={users:0,service,abort:new AbortController(),revision:''};connections.set(key,connection);
   const update=async()=>{
    if(connection.busy||document.hidden)return;connection.busy=true;
    try{const value=await connection.service.request('/manga/tag-policy?'+new URLSearchParams({revision:connection.revision}),{auth:false,signal:connection.abort.signal});
     if(!connection.abort.signal.aborted&&value?.policy){setMangaPolicy(value.policy,value.revision,value.scope||'manga');connection.revision=value.revision;}
    }catch{}finally{connection.busy=false;}
   };
   connection.update=update;connection.timer=setInterval(update,60000);addEventListener('focus',update);update();
  }
  connection.service=service;connection.users++;
  return()=>{connection.users--;if(!connection.users){connection.abort.abort();clearInterval(connection.timer);removeEventListener('focus',connection.update);connections.delete(key);}};
 },[service?.server,enabled]);
 return version;
}
