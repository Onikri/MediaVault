import {useEffect,useRef,useState} from 'react';

// Two metadata requests at a time; no chapter images or library files are loaded.
export default function useMangaSourceInfo(sources,title,service,revision){
 const [info,setInfo]=useState({}),cache=useRef({}),generation=useRef(0),active=useRef(0),pump=useRef(()=>{}),live=useRef();
 live.current={sources,title,service};
 useEffect(()=>{generation.current++;cache.current={};setInfo({});return()=>{generation.current++;};},[title?.id,service.server,revision]);
 const urls=sources.map(s=>s.url).join('\n');
 useEffect(()=>{
  if(Number(service.session?.serverVersion)<29)return;
  const current=generation.current;
  pump.current=()=>{
   if(current!==generation.current)return;
   while(active.current<2){
    const source=live.current.sources.find(s=>!cache.current[s.url]);if(!source)return;
    cache.current[source.url]={state:'loading'};active.current++;setInfo({...cache.current});
    live.current.service.request('/manga/summary',{method:'POST',body:{url:source.url,title:live.current.title},signal:AbortSignal.timeout(75000)})
     .then(value=>{if(current===generation.current)cache.current[source.url]={...value,state:'ready'};})
     .catch(error=>{if(current===generation.current)cache.current[source.url]={state:'error',error:error.message};})
     .finally(()=>{active.current--;if(current===generation.current)setInfo({...cache.current});pump.current();});
   }
  };
  pump.current();
 },[urls,title?.id,service.server,service.session?.serverVersion,revision]);
 return info;
}
