import {useEffect,useRef,useState} from 'react';

// Navigation metadata arrives before the separate real-image availability check.
export default function useMangaSourceInfo(sources,title,service,revision,{enabled=true,priority=''}={}){
 const [info,setInfo]=useState({}),cache=useRef({}),run=useRef(null),pump=useRef(()=>{}),live=useRef();live.current={sources,title,service,enabled,priority};
 const urls=sources.map(s=>s.url).join('\n');
 useEffect(()=>{
  cache.current={};setInfo({});const current={active:0,cancelled:false,controllers:new Map(),metadata:0};run.current=current;
  const emit=()=>{if(!current.cancelled)setInfo({...cache.current});};
  pump.current=()=>{
   const v=live.current;if(current.cancelled||!v.enabled||Number(v.service.session?.serverVersion||0)<29)return;
   while(current.active<2){
    const candidates=[...v.sources].sort((a,b)=>Number(b.url===v.priority)-Number(a.url===v.priority));
    const source=candidates.find(s=>!cache.current[s.url]||cache.current[s.url].state==='pending');if(!source)return;
    const prior=cache.current[source.url],abort=new AbortController();let reserved=false,metadataReceived=false;current.active++;current.controllers.set(source.url,abort);cache.current[source.url]={...prior,state:prior?.inspection?'verifying':'loading'};emit();
    (async()=>{
     let inspection=prior?.inspection;
     if(inspection||current.metadata<2||source.url===live.current.priority){
      if(!inspection){current.metadata++;reserved=true;inspection=await live.current.service.request('/manga/inspect',{method:'POST',body:{url:source.url,title:live.current.title,verifyPages:false,refresh:!!revision},signal:AbortSignal.any([abort.signal,AbortSignal.timeout(45000)])});}
      if(current.cancelled||abort.signal.aborted)return;
      metadataReceived=true;
      cache.current[source.url]={...inspection,readable:undefined,inspection:{...inspection,readable:undefined},state:'verifying'};
      const full=Object.keys(cache.current).filter(k=>cache.current[k].inspection&&k!==source.url&&k!==live.current.priority);for(const old of full.slice(0,Math.max(0,full.length-3)))delete cache.current[old].inspection;
      emit();
     }
     const value=await live.current.service.request('/manga/summary',{method:'POST',body:{url:source.url,title:live.current.title,...(Number(live.current.service.session?.serverVersion)>=47?{verifyPages:true,refresh:!!revision}:{})},signal:AbortSignal.any([abort.signal,AbortSignal.timeout(75000)])});
     if(current.cancelled||abort.signal.aborted)return;
     cache.current[source.url]={...cache.current[source.url],...value,state:value.readable===false?'error':'ready',...(value.readable===false?{error:value.readabilityError||'Источник не отдал страницу.'}:{})};emit();
    })().catch(error=>{if(current.cancelled||abort.signal.aborted)return;cache.current[source.url]={...cache.current[source.url],state:'error',error:error.message};emit();}).finally(()=>{if(reserved&&!metadataReceived&&abort.signal.aborted)current.metadata--;if(!current.cancelled&&abort.signal.aborted){const saved=cache.current[source.url];if(saved?.inspection)cache.current[source.url]={...saved,state:'pending'};else delete cache.current[source.url];emit();}current.active--;current.controllers.delete(source.url);pump.current();});
   }
  };
  pump.current();return()=>{current.cancelled=true;for(const controller of current.controllers.values())controller.abort();};
 },[title?.id,service.server,revision]);
 // A language/provider switch must release slots held by now-hidden readers.
 // Keep completed results cached so switching back needs no repeat image probe.
 useEffect(()=>{const wanted=new Set(sources.map(s=>s.url));for(const [url,controller]of run.current?.controllers||[])if(!enabled||!wanted.has(url))controller.abort();if(enabled)pump.current();},[urls,enabled,priority,service.session?.serverVersion]);
 return info;
}
