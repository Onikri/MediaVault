import {hasCatalogFilters} from './catalog-taxonomy.js';
import {useEffect,useRef,useState} from 'react';
import {loadMangaTaxonomy,mangaCatalogParams} from './manga-catalog.js';
import {acceptContentPolicy,contentPolicyRevision} from './manga-tag-policy.js';

// Tag facets are expensive on the server (seconds over the whole index) and
// change slowly: load them once per source set, apart from the cards.
const facetCache=new Map();
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
 const facetKey=service.server+'|'+facetParams+'|'+contentPolicyRevision(),[facets,setFacets]=useState(()=>facetCache.get(facetKey)||null),[facetError,setFacetError]=useState('');
 useEffect(()=>{
  if(kind!=='manga'||!capable||paused)return;
  const cached=facetCache.get(facetKey);if(cached&&Date.now()-cached.at<600000){setFacets(cached);return;}
  const abort=new AbortController();
  live.current.request('/manga/catalog/tags?'+facetParams,{signal:abort.signal}).then(value=>{const next={tags:value.tags||[],at:Date.now()};facetCache.set(facetKey,next);setFacets(next);setFacetError('');}).catch(error=>{if(!abort.signal.aborted)setFacetError(error.message);});
  return()=>abort.abort();
 },[facetKey,kind,capable,paused]);
 useEffect(()=>{if(kind!=='manga')return;let active=true;loadMangaTaxonomy().then(value=>{if(active){setTaxonomy(value);setTaxonomyError('');}}).catch(error=>{if(active)setTaxonomyError(error.message);});return()=>{active=false;};},[kind]);
 useEffect(()=>{
  const abort=new AbortController();if(kind!=='manga'||!capable){setSnapshot({...empty,key});return()=>abort.abort();}
  if(paused||composing)return()=>abort.abort();
  setSnapshot(old=>old.key===key?{...old,loading:true,error:''}:{...empty,key,loading:true});
  const timer=setTimeout(async()=>{
   const filtered=hasCatalogFilters(filters);
   const candidateParams=mangaCatalogParams({query,language,sourceIds,page,filters:{}}).toString();
   const pause=delay=>new Promise(resolve=>{const done=()=>{clearTimeout(timer);abort.signal.removeEventListener('abort',done);resolve();};const timer=setTimeout(done,delay);abort.signal.addEventListener('abort',done,{once:true});if(abort.signal.aborted)done();});
   async function read(enriching=false){
    for(let attempt=0;attempt<4&&!abort.signal.aborted;attempt++){
    const [titles,candidates]=await Promise.allSettled([
     live.current.request('/manga/catalog?'+params+'&tagPolicyRevision='+encodeURIComponent(contentPolicyRevision()),{signal:AbortSignal.any([abort.signal,AbortSignal.timeout(20000)])}),
     filtered?live.current.request('/manga/catalog?'+candidateParams,{signal:AbortSignal.any([abort.signal,AbortSignal.timeout(20000)])}):Promise.resolve({items:[]})
    ]);
    if(abort.signal.aborted)return null;
    if(titles.status==='rejected'){
     const error=titles.reason,retry=attempt<3&&(error.status>=500||[408,429].includes(error.status)||['TypeError','TimeoutError','NetworkError','AbortError'].includes(error.name));
     setSnapshot(old=>({...((old.key===key&&old.ready)?old:{...empty,key}),loading:retry&&!old.ready,retrying:retry,error:error.message,errorStatus:error.status||0}));
     if(retry){await pause([1000,3000,8000][attempt]);continue;}return null;
    }
    const data=acceptContentPolicy(titles.value),rows=data.items||[],context=candidates.status==='fulfilled'?candidates.value.items||[]:[];
    setSnapshot({key,results:rows,candidates:context,total:data.total||0,workTotal:Number(data.workTotal??data.total??0),hasMore:Number(data.offset||0)+Number(data.works??rows.length)<Number(data.workTotal??data.total??0),loading:false,enriching,ready:true,retrying:false,error:'',errorStatus:0});
    return context;
    }return null;
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
    if(!abort.signal.aborted&&await read(i+2<pending.length)===null)break;
   }
  },query.trim()?220:0);
  return()=>{clearTimeout(timer);abort.abort();};
 },[key,capable,paused,composing,revision,facetParams,retryGeneration,service.status]);
 useEffect(()=>{
  if(kind!=='manga'||Number(service.session?.serverVersion)<74||paused||composing)return;
  const abort=new AbortController();let busy=false;
  const refresh=async(event)=>{if(document.hidden||busy)return;busy=true;try{
   // Coming back to the tab also re-reads the facets (a new tag rule may have
   // landed); the timer only refreshes the cards.
   if(event?.type==='focus')live.current.request('/manga/catalog/tags?'+facetParams,{signal:abort.signal}).then(value=>{const next={tags:value.tags||[],at:Date.now()};facetCache.set(facetKey,next);setFacets(next);}).catch(()=>{});
   const rows=await live.current.request('/manga/catalog?'+params+'&tagPolicyRevision='+encodeURIComponent(contentPolicyRevision()),{signal:AbortSignal.any([abort.signal,AbortSignal.timeout(20000)])});if(!abort.signal.aborted){const data=acceptContentPolicy(rows);setSnapshot(old=>old.key===key?{...old,results:data.items||[],error:'',errorStatus:0,loading:false,retrying:false,total:rows.total||0,workTotal:Number(rows.workTotal??rows.total??0),hasMore:Number(rows.offset||0)+Number(rows.works??(rows.items||[]).length)<Number(rows.workTotal??rows.total??0),ready:true}:old);}}catch{}finally{busy=false;}};
  const timer=setInterval(()=>refresh(),30000);addEventListener('focus',refresh);return()=>{clearInterval(timer);removeEventListener('focus',refresh);abort.abort();};
 },[key,facetParams,paused,composing,service.session?.serverVersion]);
 const current=snapshot.key===key?snapshot:empty;
 return {...current,facets:facets?.tags||[],taxonomy,taxonomyError,capable,retry:()=>{attempted.current.clear();setRetryGeneration(v=>v+1);}};
}
