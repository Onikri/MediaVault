import {hasCatalogFilters} from './catalog-taxonomy.js';
import {useEffect,useRef,useState} from 'react';
import {loadMangaTaxonomy,mangaCatalogParams} from './manga-catalog.js';
import {acceptContentPolicy,contentPolicyRevision} from './manga-tag-policy.js';

const facetCache=new Map();
const pageCache=new Map();
const PAGE_TTL=45000;
const FACET_TTL=600000;
const empty={results:[],candidates:[],facets:[],total:0,hasMore:false,loading:false,enriching:false,ready:false,error:''};

function remember(cache,key,value,max){
 cache.delete(key);
 cache.set(key,value);
 while(cache.size>max)cache.delete(cache.keys().next().value);
}

function pause(delay,signal){
 return new Promise(resolve=>{
  const done=()=>{clearTimeout(timer);signal.removeEventListener('abort',done);resolve();};
  const timer=setTimeout(done,delay);
  signal.addEventListener('abort',done,{once:true});
  if(signal.aborted)done();
 });
}

export default function useMangaCatalog({query,kind,filters,language,sourceIds,service,page,sort='',limit=30,paused=false,revision=0,composing=false}){
 const [snapshot,setSnapshot]=useState(empty),[taxonomy,setTaxonomy]=useState(null),[taxonomyError,setTaxonomyError]=useState('');
 const [retryGeneration,setRetryGeneration]=useState(0),[facets,setFacets]=useState(null),[facetReadyScope,setFacetReadyScope]=useState('');
 const attempted=useRef(new Set()),refreshPage=useRef(null),lastRevision=useRef(revision);
 const live=useRef(service);live.current=service;
 const capable=Number(service.session?.serverVersion)>=72;
 const canRead=kind==='manga'&&capable&&!paused&&!composing;
 const params=mangaCatalogParams({query,filters,language,sourceIds,page,sort,limit}).toString();
 const facetParams=new URLSearchParams({language,sourceIds:[...sourceIds].sort().join(','),limit:'500'}).toString();
 const facetScope=service.server+'|'+facetParams;
 const facetKey=facetScope+'|'+contentPolicyRevision();
 const key=JSON.stringify([params,service.server,service.session?.role,kind]);
 const cached=pageCache.get(key);
 const recent=cached&&Date.now()-cached.at<PAGE_TTL?cached.page:null;

 useEffect(()=>{
  if(!canRead||facetReadyScope!==facetScope)return;
  const abort=new AbortController();
  const refresh=()=>{
   if(document.hidden)return;
   const hit=facetCache.get(facetKey);
   if(hit&&Date.now()-hit.at<FACET_TTL){setFacets(hit);return;}
   if(loading)return;
   loading=true;
   live.current.request('/manga/catalog/tags?'+facetParams,{signal:AbortSignal.any([abort.signal,AbortSignal.timeout(20000)])})
    .then(value=>{
     if(abort.signal.aborted)return;
     const next={key:facetKey,tags:value.tags||[],at:Date.now()};
     remember(facetCache,facetKey,next,24);setFacets(next);
    }).catch(()=>{}).finally(()=>{loading=false;});
  };
  let loading=false;
  // The first card page gets the catalogue lock before uncached facets.
  const timer=setTimeout(refresh,1000);
  addEventListener('focus',refresh);
  return()=>{clearTimeout(timer);removeEventListener('focus',refresh);abort.abort();};
 },[canRead,facetKey,facetReadyScope,facetScope]);

 useEffect(()=>{if(kind!=='manga')return;let active=true;loadMangaTaxonomy().then(value=>{if(active){setTaxonomy(value);setTaxonomyError('');}}).catch(error=>{if(active)setTaxonomyError(error.message);});return()=>{active=false;};},[kind]);

 useEffect(()=>{
  if(!canRead)return;
  const abort=new AbortController(),{signal}=abort;
  const filtered=hasCatalogFilters(filters);
  const candidateParams=mangaCatalogParams({query,language,sourceIds,page,sort,limit,filters:{}}).toString();
  let initial=true,busy=false,enriching=false,refreshAfterRead=false;
  let candidates=recent?.candidates||empty.candidates;
  if(recent)setFacetReadyScope(facetScope);
  setSnapshot(old=>old.key===key?{...old,error:'',loading:!old.ready}:recent||{...empty,key,loading:true});

  function publish(value){
   const data=acceptContentPolicy(value),results=data.items||[];
   const workTotal=Number(data.workTotal??data.total??0);
   const next={...empty,key,results,candidates,total:data.total||0,workTotal,
    hasMore:Number(data.offset||0)+Number(data.works??results.length)<workTotal,ready:true,enriching};
   remember(pageCache,key,{at:Date.now(),page:{...next,enriching:false}},24);
   setSnapshot(next);
   setFacetReadyScope(facetScope);
  }
  const requestPage=()=>live.current.request('/manga/catalog?'+params+'&tagPolicyRevision='+encodeURIComponent(contentPolicyRevision()),{signal:AbortSignal.any([signal,AbortSignal.timeout(20000)])});

  async function read({retry=false,report=false}={}){
   if(busy||signal.aborted)return false;
   busy=true;
   try{
    for(let attempt=0;!signal.aborted;attempt++){
     try{
      const value=await requestPage();
      if(signal.aborted)return false;
      publish(value);
      return true;
     }catch(error){
      if(signal.aborted)return false;
      const again=retry&&attempt<3&&(error.status>=500||[408,429].includes(error.status)||['TypeError','TimeoutError','NetworkError','AbortError'].includes(error.name));
      if(report)setSnapshot(old=>({...old,error:error.message,errorStatus:error.status||0,loading:again&&!old.ready,retrying:again}));
      if(!again)return false;
      await pause([1000,3000,8000][attempt],signal);
     }
    }
   }finally{
    busy=false;
    if(refreshAfterRead&&!signal.aborted){refreshAfterRead=false;void read();}
   }
   return false;
  }

  async function enhance(){
   try{
    const value=await live.current.request('/manga/catalog?'+candidateParams,{signal:AbortSignal.any([signal,AbortSignal.timeout(20000)])});
    if(signal.aborted)return;
    candidates=value.items||[];
    setSnapshot(old=>({...old,candidates}));
    const pending=candidates.filter(row=>!row.metadataChecked&&!attempted.current.has(service.server+':'+row.catalogId)).slice(0,12);
    for(let i=0;i<pending.length&&!signal.aborted;i+=2){
     await Promise.allSettled(pending.slice(i,i+2).map(row=>{
      attempted.current.add(service.server+':'+row.catalogId);
      if(attempted.current.size>4000)attempted.current.delete(attempted.current.values().next().value);
      return live.current.request('/manga/catalog/enrich',{method:'POST',body:{ids:[row.catalogId]},signal:AbortSignal.any([signal,AbortSignal.timeout(90000)])});
     }));
    }
    if(pending.length&&!signal.aborted){
     enriching=false;
     if(busy)refreshAfterRead=true;
     else await read();
    }
   }catch{}finally{
    enriching=false;
    if(!signal.aborted)setSnapshot(old=>({...old,enriching:false}));
   }
  }

  const start=setTimeout(async()=>{
   enriching=filtered;
   const loaded=await read({retry:true,report:true});
   initial=false;
   if(loaded&&filtered)void enhance();
  },query.trim()&&!recent?220:0);
  const revalidate=()=>{if(!document.hidden&&!initial)void read();};
  const refresh=()=>{if(Number(live.current.session?.serverVersion)>=74)revalidate();};
  refreshPage.current=revalidate;
  const interval=setInterval(refresh,30000);
  addEventListener('focus',refresh);
  return()=>{clearTimeout(start);clearInterval(interval);removeEventListener('focus',refresh);abort.abort();refreshPage.current=null;};
 },[key,canRead,facetScope,retryGeneration,service.status]);

 useEffect(()=>{
  if(lastRevision.current===revision)return;
  lastRevision.current=revision;
  const timer=setTimeout(()=>refreshPage.current?.(),500);
  return()=>clearTimeout(timer);
 },[revision]);

 const current=kind==='manga'&&capable?(snapshot.key===key?snapshot:recent||empty):empty;
 const matchingFacets=facets?.key===facetKey?facets:facetCache.get(facetKey);
 return {...current,facets:matchingFacets?.tags||[],taxonomy,taxonomyError,capable,retry:()=>{attempted.current.clear();setRetryGeneration(v=>v+1);}};
}
