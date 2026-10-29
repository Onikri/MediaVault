import {useEffect,useState} from 'react';
export default function useSourceTitles(query,kind,service,composing=false){
 const [snapshot,setSnapshot]=useState({results:[],loading:false}),key=JSON.stringify([query.trim(),kind,service.server]);
 useEffect(()=>{const abort=new AbortController();setSnapshot({key,results:[],loading:false});if(composing||kind!=='anime'||query.trim().length<2||!service.session?.serverVersion)return()=>abort.abort();
  const timer=setTimeout(async()=>{setSnapshot({key,results:[],loading:true});try{const data=await service.request('/sources/search?'+new URLSearchParams({q:query.trim(),kind}),{signal:abort.signal});if(!abort.signal.aborted)setSnapshot({key,loading:false,results:(data.results||[]).map(r=>({...r,id:r.provider+':'+r.url,kind,language:r.language||'ru',sourceOnly:true,sourceId:r.provider,sourceURL:r.url}))});}catch(e){if(!abort.signal.aborted)setSnapshot({key,results:[],loading:false,error:e.message});}},650);
  return()=>{clearTimeout(timer);abort.abort();};
 },[key,composing,!!service.session?.serverVersion]);
 return snapshot.key===key?snapshot:{results:[],loading:false};
}
