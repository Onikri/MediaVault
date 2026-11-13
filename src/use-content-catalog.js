import {useEffect,useState} from 'react';
import {acceptContentPolicy,contentPolicyRevision} from './manga-tag-policy.js';
const sent=new Map();
const empty=Object.freeze([]);
export default function useContentCatalog({service,state,kind,query,filters,rows,revision,page=1}){
 const [result,setResult]=useState({items:empty});
 const enabled=!!service?.server&&Number(service.session?.serverVersion)>=74;
 useEffect(()=>{
  if(!enabled||!state?.admin||!rows?.length)return;
  const abort=new AbortController(),timer=setTimeout(async()=>{
   const pending=rows.map(row=>({row,key:service.server+':'+row.kind+':'+row.id,raw:JSON.stringify(row)})).filter(value=>sent.get(value.key)!==value.raw);
   for(let i=0;i<pending.length&&!abort.signal.aborted;i+=10){const batch=pending.slice(i,i+10);try{await service.request('/catalog/content/facts',{method:'POST',body:{items:batch.map(value=>value.row)},signal:abort.signal});for(const value of batch)sent.set(value.key,value.raw);while(sent.size>1500)sent.delete(sent.keys().next().value);}catch{break;}}
  },450);return()=>{clearTimeout(timer);abort.abort();};
 },[enabled,rows,service.server,state?.admin]);
 useEffect(()=>{
  if(!enabled){setResult({items:empty});return;}
  const abort=new AbortController();let busy=false;
  const read=async()=>{if(busy||document.hidden)return;busy=true;try{const value=await service.request('/catalog/content?'+new URLSearchParams({q:query,kind,tag:filters.tag||'',genre:filters.genre||'',tagPolicyRevision:contentPolicyRevision(),limit:'30',offset:String((page-1)*30)}),{signal:abort.signal});if(!abort.signal.aborted){acceptContentPolicy(value);setResult({items:value.items||empty,query,kind,server:service.server,page,hasMore:Number(value.offset||0)+(value.items||[]).length<Number(value.total||0)});}}catch{}finally{busy=false;}};
  const timer=setTimeout(read,150),poll=setInterval(read,15000);addEventListener('focus',read);
  return()=>{clearTimeout(timer);clearInterval(poll);removeEventListener('focus',read);abort.abort();};
 },[enabled,kind,query,filters.tag,filters.genre,revision,service.server,page]);
 return result.query===query&&result.kind===kind&&result.server===service.server&&result.page===page?result:{items:empty};
}
