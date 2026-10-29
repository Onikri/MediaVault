import {useEffect,useRef,useState} from 'react';
const empty={results:[],progress:null,state:'idle',error:''};
export default function useGlobalManga(query,kind,language,sourceIds,service,composing=false,revision=0){
 const [snapshot,setSnapshot]=useState(empty),live=useRef(service);live.current=service;
 const key=JSON.stringify([query.trim(),kind,language,[...sourceIds].sort(),service.server,service.status,revision]);
 useEffect(()=>{
  const controller=new AbortController();let job,timer,pollTimer,closed=false;
  setSnapshot({...empty,key});
  if(composing||kind!=='manga'||query.trim().length<2||service.status!=='connected'||Number(service.session?.serverVersion)<16)return()=>controller.abort();
  const receive=data=>{if(!closed)setSnapshot({...data,key,error:''});};
  async function poll(){
   try{const data=await live.current.request('/discovery/manga/search/'+job,{signal:controller.signal});receive(data);if(data.state==='running')pollTimer=setTimeout(poll,1000);}
   catch(error){if(!closed)setSnapshot(old=>({...old,error:error.message,state:'error'}));}
  }
  timer=setTimeout(async()=>{
   try{const data=await live.current.request('/discovery/manga/search',{method:'POST',body:{query:query.trim(),language,...(sourceIds.length?{sourceIds}:{}),...(revision?{refresh:true}:{})},signal:AbortSignal.timeout(20000)});job=data.id;if(closed){live.current.request('/discovery/manga/search/'+job,{method:'DELETE'}).catch(()=>{});return;}receive(data);if(data.state==='running')pollTimer=setTimeout(poll,750);}
   catch(error){if(!closed)setSnapshot({...empty,key,error:error.message,state:'error'});}
  },650);
  return()=>{closed=true;clearTimeout(timer);clearTimeout(pollTimer);controller.abort();if(job)live.current.request('/discovery/manga/search/'+job,{method:'DELETE'}).catch(()=>{});};
 },[key,composing,service.session?.serverVersion]);
 return snapshot.key===key?snapshot:empty;
}
