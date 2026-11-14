import {useEffect,useRef,useState} from 'react';
import {loadMangaTaxonomy,mangaCatalogParams} from './manga-catalog.js';
import {acceptContentPolicy,contentPolicyRevision} from './manga-tag-policy.js';

const empty={results:[],candidates:[],facets:[],total:0,hasMore:false,loading:false,enriching:false,ready:false,error:''};
export default function useMangaCatalog({query,kind,filters,language,sourceIds,service,page,sort='',limit=30,paused=false,revision=0,composing=false}){
 const [snapshot,setSnapshot]=useState(empty),[taxonomy,setTaxonomy]=useState(null),[taxonomyError,setTaxonomyError]=useState('');
 const [retryGeneration,setRetryGeneration]=useState(0);
 const attempted=useRef(new Set());
 const live=useRef(service);live.current=service;
 const capable=Number(service.session?.serverVersion)>=72;
 const params=mangaCatalogParams({query,filters,language,sourceIds,page,sort,limit}).toString();
 const facetParams=new URLSearchParams({language,sourceIds:[...sourceIds].sort().join(','),limit:'500'}).toString();
 const key=JSON.stringify([params,service.server,kind]);
 useEffect(()=>{if(kind!=='manga')return;let active=true;loadMangaTaxonomy().then(value=>{if(active){setTaxonomy(value);setTaxonomyError('');}}).catch(error=>{if(active)setTaxonomyError(error.message);});return()=>{active=false;};},[kind]);
 useEffect(()=>{
  const abort=new AbortController();if(kind!=='manga'||!capable||paused||composing){setSnapshot({...empty,key});return()=>abort.abort();}
  setSnapshot(old=>old.key===key?{...old,loading:true,error:''}:{...empty,key,loading:true});
  const timer=setTimeout(async()=>{
   const filtered=!!(filters.genre||filters.tag||filters.year||filters.format||filters.age);
   const candidateParams=mangaCatalogParams({query,language,sourceIds,page,filters:{}}).toString();
   async function read(enriching=false){
    const [titles,facets,candidates]=await Promise.allSettled([
     live.current.request('/manga/catalog?'+params+'&tagPolicyRevision='+encodeURIComponent(contentPolicyRevision()),{signal:abort.signal}),
     live.current.request('/manga/catalog/tags?'+facetParams,{signal:abort.signal}),
     filtered?live.current.request('/manga/catalog?'+candidateParams,{signal:abort.signal}):Promise.resolve({items:[]})
    ]);
    if(abort.signal.aborted)return null;
    if(titles.status==='rejected'){setSnapshot({...empty,key,error:titles.reason.message});return null;}
    const data=acceptContentPolicy(titles.value),rows=data.items||[],context=candidates.status==='fulfilled'?candidates.value.items||[]:[];
    setSnapshot({key,results:rows,candidates:context,facets:facets.status==='fulfilled'?facets.value.tags||[]:[],total:data.total||0,workTotal:Number(data.workTotal??data.total??0),hasMore:Number(data.offset||0)+Number(data.works??rows.length)<Number(data.workTotal??data.total??0),loading:false,enriching,ready:true,error:facets.status==='rejected'?facets.reason.message:''});
    return context;
   }
   const context=await read();if(!context||!filtered)return;
   const pending=context.filter(row=>!row.metadataChecked&&!attempted.current.has(service.server+':'+row.catalogId)).slice(0,12);
   for(let i=0;i<pending.length&&!abort.signal.aborted;i+=2){
    setSnapshot(old=>({...old,enriching:true}));
    await Promise.allSettled(pending.slice(i,i+2).map(row=>{
     const key=service.server+':'+row.catalogId;attempted.current.add(key);
     if(attempted.current.size>4000)attempted.current.delete(attempted.current.values().next().value);
     return live.current.request('/manga/catalog/enrich',{method:'POST',body:{ids:[row.catalogId]},signal:AbortSignal.any([abort.signal,AbortSignal.timeout(90000)])});
    }));
    if(!abort.signal.aborted)await read(i+2<pending.length);
   }
  },query.trim()?220:0);
  return()=>{clearTimeout(timer);abort.abort();};
 },[key,capable,paused,composing,revision,facetParams,retryGeneration]);
 useEffect(()=>{
  if(kind!=='manga'||Number(service.session?.serverVersion)<74||paused||composing)return;
  const abort=new AbortController();let busy=false;
  const refresh=async()=>{if(document.hidden||busy)return;busy=true;try{const [rows,facets]=await Promise.all([live.current.request('/manga/catalog?'+params+'&tagPolicyRevision='+encodeURIComponent(contentPolicyRevision()),{signal:abort.signal}),live.current.request('/manga/catalog/tags?'+facetParams,{signal:abort.signal})]);if(!abort.signal.aborted)setSnapshot(old=>old.key===key?{...old,results:acceptContentPolicy(rows).items||[],facets:facets.tags||[],total:rows.total||0,workTotal:Number(rows.workTotal??rows.total??0),hasMore:Number(rows.offset||0)+Number(rows.works??(rows.items||[]).length)<Number(rows.workTotal??rows.total??0),ready:true}:old);}catch{}finally{busy=false;}};
  const timer=setInterval(refresh,15000);addEventListener('focus',refresh);return()=>{clearInterval(timer);removeEventListener('focus',refresh);abort.abort();};
 },[key,facetParams,paused,composing,service.session?.serverVersion]);
 return {...(snapshot.key===key?snapshot:empty),taxonomy,taxonomyError,capable,retry:()=>{attempted.current.clear();setRetryGeneration(v=>v+1);}};
}
