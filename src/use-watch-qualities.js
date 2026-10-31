import {useEffect,useRef,useState} from 'react';
import {variantsFor} from './watch-session.js';
export default function useWatchQualities({voices,voiceId,episode,season,server,inspect,service,attempt,scope=''}){
 const cache=useRef(new Map()),[state,setState]=useState({key:'',rows:[],done:0,total:0,busy:false});
 const key=server+':'+season+':'+episode+':'+voiceId;
 useEffect(()=>{
  const abort=new AbortController(),signal=abort.signal;
  if(!scope)return()=>abort.abort();
  const groups=(scope==='selected'?voices.filter(v=>v.id===voiceId):[...voices]).sort((a,b)=>Number(b.id===voiceId)-Number(a.id===voiceId));
  const tasks=groups.flatMap(group=>variantsFor(group,episode).map(variant=>({group,variant}))),rows=[];
  setState({key,rows:[],done:0,total:tasks.length,busy:!!tasks.length});
  // One discovery probe at a time: dynamic public players share a bounded VM browser.
  // Playback, audio and preview requests remain independent of this metadata queue.
  (async()=>{let done=0;for(const {group,variant} of tasks){
   try{
    signal.throwIfAborted();const value=await inspect(variant,signal),entry=value.entries.find(e=>Number(e.number)===Number(episode));
    if(entry){const id=server+'|'+variant.sourceUrl+'|'+entry.url,old=cache.current.get(id);
     const data=old&&Date.now()-old.at<300000?old.data:await service.request('/sources/qualities',{method:'POST',body:{url:entry.url,referer:variant.sourceUrl},signal:AbortSignal.any([signal,AbortSignal.timeout(45000)])});
     signal.throwIfAborted();if(Array.isArray(data.qualities)){cache.current.set(id,{data,at:Date.now()});rows.push({...value,voiceId:group.id,qualities:data.qualities.map(Number).filter(n=>Number.isInteger(n)&&n>0&&n<=8640).sort((a,b)=>b-a),original:!!data.original});}
    }
   }catch{if(signal.aborted)return;/* Unknown is not the same as unavailable. */}
   done++;setState({key,rows:[...rows],done,total:tasks.length,busy:done<tasks.length});
  }})();return()=>abort.abort();
 },[voices,voiceId,episode,season,server,attempt,scope]);
 return state.key===key?state:{key,rows:[],done:0,total:0,busy:true};
}
