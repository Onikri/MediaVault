import {useEffect,useRef,useState} from 'react';
const empty={results:[],progress:null,state:'idle',error:''};
export default function useGlobalManga(query,kind,language,sourceIds,service,composing=false,revision=0,title=null){
 const [snapshot,setSnapshot]=useState(empty),live=useRef(service);live.current=service;
 const capable=Number(service.session?.serverVersion)>=16;
 const titleKey=title?JSON.stringify([title.id,title.ids,title.titles,title.aliases]):'';
 const key=JSON.stringify([query.trim(),kind,language,[...sourceIds].sort(),service.server,revision,titleKey]);
 useEffect(()=>{
  const controller=new AbortController();let job,timer,pollTimer,closed=false;
  setSnapshot({...empty,key});
  if(composing||kind!=='manga'||query.trim().length<2||!capable)return()=>controller.abort();
  let failures=0;
  const receive=data=>{if(!closed){failures=0;setSnapshot(old=>({...data,key,error:'',results:[...new Map([...(old.key===key?old.results:[]),...(data.results||[])].map(v=>[v.id||v.url,v])).values()]}));}};
  async function poll(){
   try{const data=await live.current.request('/discovery/manga/search/'+job,{signal:controller.signal});receive(data);if(data.state==='running')pollTimer=setTimeout(poll,1000);}
   catch(error){if(!closed){failures++;setSnapshot(old=>({...old,error:error.message,state:failures<4?'running':'error'}));if(failures<4)pollTimer=setTimeout(poll,Math.min(5000,failures*1000));}}
  }
  // Let creation return its job ID even after navigation so cleanup can cancel
  // the server queue. Aborting this POST can leave an unknown job running.
  timer=setTimeout(async()=>{
   try{const data=await live.current.request('/discovery/manga/search',{method:'POST',body:{query:query.trim(),language,...(sourceIds.length?{sourceIds}:{}),...(title&&Number(live.current.session?.serverVersion)>=29?{title}:{}),...(revision?{refresh:true}:{})},signal:AbortSignal.timeout(20000)});job=data.id;if(closed){live.current.request('/discovery/manga/search/'+job,{method:'DELETE'}).catch(()=>{});return;}receive(data);if(data.state==='running')pollTimer=setTimeout(poll,750);}
   catch(error){if(!closed)setSnapshot({...empty,key,error:error.message,state:'error'});}
  },650);
  return()=>{closed=true;clearTimeout(timer);clearTimeout(pollTimer);controller.abort();if(job)live.current.request('/discovery/manga/search/'+job,{method:'DELETE'}).catch(()=>{});};
 },[key,composing,capable]);
 return snapshot.key===key?snapshot:empty;
}
