import {filterParam,taxonomyFacts} from './catalog-taxonomy.js';
import {useEffect,useState} from 'react';
import {acceptContentPolicy,contentPolicyRevision} from './manga-tag-policy.js';
const sent=new Map();
const empty=Object.freeze([]);
export function contentCatalogParams({kind,query,filters,page=1,limit=30,sort=''}){
 return new URLSearchParams({q:query,kind,tag:filterParam(filters.tag),genre:filterParam(filters.genre),excludeGenre:filterParam(filters.excludeGenre),excludeTag:filterParam(filters.excludeTag),format:filters.format||'',age:filters.age||'',year:filters.year||'',limit:String(limit),offset:String((page-1)*limit),sort});
}

export default function useContentCatalog({service,state,kind,query,filters,rows,revision,page=1,limit=30,sort=''}){
 const params=contentCatalogParams({kind,query,filters,page,limit,sort}).toString();
 const key=JSON.stringify([service.server,params]);
 const [result,setResult]=useState({items:empty}),[retryCount,setRetryCount]=useState(0);
 const enabled=!!service?.server&&Number(service.session?.serverVersion)>=74;
 useEffect(()=>{
  if(!enabled||!state?.admin||!rows?.length)return;
  const abort=new AbortController(),timer=setTimeout(async()=>{
   const pending=rows.map(row=>row.kind==='book'?taxonomyFacts(row):row).map(row=>({row,key:service.server+':'+row.kind+':'+row.id,raw:JSON.stringify(row)})).filter(value=>sent.get(value.key)!==value.raw);
   for(let i=0;i<pending.length&&!abort.signal.aborted;i+=10){const batch=pending.slice(i,i+10);try{await service.request('/catalog/content/facts',{method:'POST',body:{items:batch.map(value=>value.row)},signal:abort.signal});for(const value of batch)sent.set(value.key,value.raw);while(sent.size>1500)sent.delete(sent.keys().next().value);dispatchEvent(new Event('mediavault:catalog-facts-updated'));}catch{break;}}
  },450);return()=>{clearTimeout(timer);abort.abort();};
 },[enabled,rows,service.server,state?.admin]);
 useEffect(()=>{
  if(!enabled)return;
  const abort=new AbortController();let busy=false;
  const read=async()=>{
   if(busy||document.hidden)return;
   busy=true;
   try{
    const value=await service.request('/catalog/content?'+params+'&tagPolicyRevision='+encodeURIComponent(contentPolicyRevision()),{signal:AbortSignal.any([abort.signal,AbortSignal.timeout(20000)])});
    if(abort.signal.aborted)return;
    acceptContentPolicy(value);
    const items=value.items||empty,total=Number(value.total)||0;
    setResult({items,key,ready:true,total,hasMore:Number(value.offset||0)+items.length<total,pages:total?Math.ceil(total/limit):null});
   }catch(error){
    if(!abort.signal.aborted)setResult(old=>({...(old.key===key?old:{items:empty}),key,error:error.message}));
   }finally{busy=false;}
  };
  const timer=setTimeout(read,150),poll=setInterval(read,15000);addEventListener('focus',read);addEventListener('mediavault:catalog-facts-updated',read);
  return()=>{clearTimeout(timer);clearInterval(poll);removeEventListener('focus',read);removeEventListener('mediavault:catalog-facts-updated',read);abort.abort();};
 },[enabled,key,revision,retryCount]);
 const current=enabled&&result.key===key?result:{items:empty};
 return {...current,loading:enabled&&!current.ready&&!current.error,retry:()=>{setResult(old=>old.key===key?{...old,error:''}:old);setRetryCount(value=>value+1);}};
}
