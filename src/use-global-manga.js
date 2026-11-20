import {useEffect,useRef,useState} from 'react';
const empty={results:[],progress:null,state:'idle',error:''};
const searchError=error=>error?.name==='TimeoutError'?'Сервер не успел ответить на поиск источников.':error.message;
const CACHE_TTL=12*60*1000;
export default function useGlobalManga(query,kind,language,sourceIds,service,composing=false,revision=0,title=null){
 const [snapshot,setSnapshot]=useState(empty),live=useRef(service),cached=useRef(new Map());live.current=service;
 const capable=service.status==='connected'&&Number(service.session?.serverVersion)>=16;
 const titleKey=title?JSON.stringify([title.id,title.ids,title.titles,title.aliases]):'';
 const scope=JSON.stringify([query.trim(),kind,service.server,titleKey]);
 const key=JSON.stringify([scope,language,[...sourceIds].sort(),revision]);
 useEffect(()=>{
  const controller=new AbortController();let job,timer,pollTimer,closed=false;
  if(composing||kind!=='manga'||query.trim().length<2||!capable){setSnapshot({...empty,key});return()=>controller.abort();}
  const now=Date.now(),previous=cached.current.get(key);
  if(previous?.expires>now&&previous.snapshot.state==='done'){
   setSnapshot(previous.snapshot);
   return()=>controller.abort();
  }
  const accepted=row=>(language==='all'||row.language===language)
    &&(!sourceIds.length||sourceIds.includes(String(row.sourceId)));
  const collected=new Map();
  for(const [entry,value] of cached.current){
   if(value.expires<=now)cached.current.delete(entry);
   else if(value.scope===scope)for(const row of value.snapshot.results)if(accepted(row))collected.set(row.id||row.url,row);
  }
  setSnapshot({...empty,key,state:'running',results:[...collected.values()]});
  let failures=0;
  const receive=data=>{
   if(closed)return;
   failures=0;
   for(const row of data.results||[])collected.set(row.id||row.url,row);
   const current={...data,key,error:'',results:[...collected.values()]};
   cached.current.set(key,{scope,snapshot:current,expires:Date.now()+CACHE_TTL});
   while(cached.current.size>24)cached.current.delete(cached.current.keys().next().value);
   setSnapshot(current);
  };
  async function poll(){
   try{const data=await live.current.request('/discovery/manga/search/'+job,{signal:AbortSignal.any([controller.signal,AbortSignal.timeout(12000)])});receive(data);if(data.state==='running')pollTimer=setTimeout(poll,1000);}
   catch(error){if(!closed){failures++;setSnapshot(old=>({...old,error:failures<4?'':searchError(error),state:failures<4?'running':'error'}));if(failures<4)pollTimer=setTimeout(poll,Math.min(5000,failures*1000));}}
  }
  // Let creation return its job ID even after navigation so cleanup can cancel
  // the server queue. Aborting this POST can leave an unknown job running.
  timer=setTimeout(async()=>{
   try{const data=await live.current.request('/discovery/manga/search',{method:'POST',body:{query:query.trim(),language,...(sourceIds.length?{sourceIds}:{}),...(title&&Number(live.current.session?.serverVersion)>=29?{title}:{}),...(revision?{refresh:true}:{})},signal:AbortSignal.timeout(20000)});job=data.id;if(closed){live.current.request('/discovery/manga/search/'+job,{method:'DELETE'}).catch(()=>{});return;}receive(data);if(data.state==='running')pollTimer=setTimeout(poll,750);}
   catch(error){if(!closed)setSnapshot(old=>({...old,error:searchError(error),state:'error'}));}
  },650);
  return()=>{closed=true;clearTimeout(timer);clearTimeout(pollTimer);controller.abort();if(job)live.current.request('/discovery/manga/search/'+job,{method:'DELETE'}).catch(()=>{});};
 },[key,composing,capable]);
 return snapshot.key===key?snapshot:empty;
}
