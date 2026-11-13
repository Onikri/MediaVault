import {useEffect,useRef,useState} from 'react';
import {loadMangaTaxonomy,mangaCatalogParams} from './manga-catalog.js';

const empty={results:[],candidates:[],facets:[],total:0,hasMore:false,loading:false,enriching:false,ready:false,error:''};
export default function useMangaCatalog({query,kind,filters,language,sourceIds,service,page,paused=false,revision=0,composing=false}){
 const [snapshot,setSnapshot]=useState(empty),[taxonomy,setTaxonomy]=useState(null),[taxonomyError,setTaxonomyError]=useState('');
 const [retryGeneration,setRetryGeneration]=useState(0);
 const attempted=useRef(new Set());
 const live=useRef(service);live.current=service;
 const capable=Number(service.session?.serverVersion)>=72;
 const params=mangaCatalogParams({query,filters,language,sourceIds,page}).toString();
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
     live.current.request('/manga/catalog?'+params,{signal:abort.signal}),
     live.current.request('/manga/catalog/tags?'+facetParams,{signal:abort.signal}),
     filtered?live.current.request('/manga/catalog?'+candidateParams,{signal:abort.signal}):Promise.resolve({items:[]})
    ]);
    if(abort.signal.aborted)return null;
    if(titles.status==='rejected'){setSnapshot({...empty,key,error:titles.reason.message});return null;}
    const data=titles.value,rows=data.items||[],context=candidates.status==='fulfilled'?candidates.value.items||[]:[];
    setSnapshot({key,results:rows,candidates:context,facets:facets.status==='fulfilled'?facets.value.tags||[]:[],total:data.total||0,hasMore:Number(data.offset||0)+rows.length<Number(data.total||0),loading:false,enriching,ready:true,error:facets.status==='rejected'?facets.reason.message:''});
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
 return {...(snapshot.key===key?snapshot:empty),taxonomy,taxonomyError,capable,retry:()=>{attempted.current.clear();setRetryGeneration(v=>v+1);}};
}
