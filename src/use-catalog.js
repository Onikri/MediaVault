import {useCallback,useEffect,useState} from 'react';
import {BROWSE_KINDS,catalogProviders,fetchBrowsePage,fetchCatalog,mergeCatalog,rankCatalog} from './catalog.js';

const cache=new Map();
const emptyItems=Object.freeze([]),emptyStatuses=Object.freeze({});
// browse: {sort, perPage} pages one ordered list when there is no query;
// off: the page has another spine (the manga index), so nothing is fetched.
export function useCatalog(query,kind,year,server,page=1,composing=false,filters={},{sort='popular',perPage=24,off=false}={}){
  const text=query.trim(),browse=!text&&BROWSE_KINDS.includes(kind);
  const cacheKey=JSON.stringify([text,kind,year,server,page,filters.genre,filters.tag,...(browse?[filters.format,sort,perPage]:[]),off]);
  const [revision,setRevision]=useState(0),[snapshot,setSnapshot]=useState(null);
  const key=cacheKey+':'+revision+':'+composing;
  const retry=useCallback(()=>{cache.delete(cacheKey);setRevision(value=>value+1);},[cacheKey]);
  useEffect(()=>{
    if(composing)return;
    const abort=new AbortController(),names=off?[]:browse?['anilist']:catalogProviders(kind,text,server);
    const cached=cache.get(cacheKey);
    if(cached&&cached.expires>Date.now()){
      setSnapshot({key,...cached,loading:false});return;
    }
    const states=Object.fromEntries(names.map(name=>[name,'loading'])),results={},pages={};
    const items=()=>browse?[...(results.anilist||[])]:rankCatalog(mergeCatalog(names.flatMap(name=>results[name]||[])),text);
    const total=()=>Math.max(0,...Object.values(pages))||null;
    if(off){setSnapshot({key,items:[],statuses:{},pages:null,loading:false,browse});return;}
    setSnapshot({key,items:[],statuses:{...states},pages:null,loading:names.length>0});
    const timer=setTimeout(()=>{
      Promise.allSettled(names.map(async provider=>{
        try{
          let found=null;
          if(browse){
            try{found=await fetchBrowsePage({kind,page,perPage,sort,year,genre:filters.genre,tag:filters.tag,format:filters.format,signal:abort.signal});}catch(error){if(abort.signal.aborted)return;}
            // AniList down or empty: page through Shikimori alone, still one list.
            if(!found?.length){found=await fetchCatalog('shikimori',{query:'',kind,year,genre:filters.genre,tag:filters.tag,server,page,signal:abort.signal});states.anilist='unavailable';states.shikimori='ok';}
          }else found=await fetchCatalog(provider,{query:text,kind,year,genre:filters.genre,tag:filters.tag,server,page,signal:abort.signal});
          if(abort.signal.aborted)return;
          results[provider]=found;if(states[provider]==='loading')states[provider]='ok';if(browse&&found.russian)states.shikimori='ok';if(found.pages)pages[provider]=found.pages;
        }catch(error){
          if(abort.signal.aborted)return;
          states[provider]='unavailable';
        }
        if(!abort.signal.aborted)setSnapshot({key,items:items(),statuses:{...states},pages:total(),browse,loading:Object.values(states).includes('loading')});
      })).then(()=>{
        if(abort.signal.aborted)return;
        const complete={items:items(),statuses:{...states},pages:total(),browse};
        setSnapshot({key,...complete,loading:false});
        // Do not make temporary provider outages persist for three minutes.
        if(names.length&&names.every(name=>states[name]==='ok')){
          cache.set(cacheKey,{...complete,expires:Date.now()+180000});
          while(cache.size>60)cache.delete(cache.keys().next().value);
        }
      });
    },text?350:0);
    return()=>{clearTimeout(timer);abort.abort();};
  },[key]);
  // Clear old choices in the same render as input/type/page changes, before
  // effects run. IME composition never dispatches intermediate search terms.
  const current=snapshot?.key===key?snapshot:{items:emptyItems,statuses:emptyStatuses,pages:null,loading:!composing};
  return {...current,retry};
}
