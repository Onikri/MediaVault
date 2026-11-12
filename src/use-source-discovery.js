import {useEffect,useState} from 'react';
import {guestLocked,GUEST_LOCKED} from './guest-session.js';

// One discovery per work at a time. Every view of the same title (the player
// on the page and the save window) follows the same search and shares its
// snapshots, and a finished search is reused for a few minutes, so opening the
// save window never repeats a full discovery on the server. Retry refreshes.
const searches=new Map(),FRESH=5*60*1000;
function share(key){
 let search=searches.get(key);
 if(!search){search={data:null,error:'',done:false,at:0,listeners:new Set(),controller:null};searches.set(key,search);}
 return search;
}
function publish(search){for(const listener of search.listeners)listener(search);}
function prune(){for(const [key,search] of searches)if(!search.listeners.size&&(!search.done||Date.now()-search.at>FRESH))searches.delete(key);while(searches.size>20)searches.delete(searches.keys().next().value);}

export default function useSourceDiscovery(item,service){
  const [data,setData]=useState(null),[loading,setLoading]=useState(false),[error,setError]=useState(''),[revision,setRevision]=useState(0);
  const sourceURL=item?.provider==='hentaichan-video'?(item.sourceURL||item.sourceUrl):undefined;
  useEffect(()=>{
    setData(null);setError('');setLoading(false);
    if(!item||!['anime','tv','movie'].includes(item.kind)||(!service.session?.serverVersion&&service.status!=='connected'))return;
    if(guestLocked(service.session,item)){setError(GUEST_LOCKED);return;}
    if(service.session?.serverVersion&&service.session.serverVersion<7){setError('Сервер импорта нужно обновить для полного списка озвучек и качеств.');return;}
    const title=Object.fromEntries(['id','ids','title','titles','aliases','year','kind','format'].map(key=>[key,item[key]]));
    if(sourceURL){title.provider=item.provider;title.sourceURL=sourceURL;}
    // Keyed like the effect: the same work, not its (late-arriving) aliases.
    const key=String(service.server||'')+'|'+JSON.stringify([item.id,item.kind,item.ids||{},item.year||null,sourceURL||'']);
    if(revision){const old=searches.get(key);old?.controller?.abort();searches.delete(key);}
    const search=share(key);
    const listener=value=>{setData(value.data);setError(value.error);setLoading(!value.done);};
    search.listeners.add(listener);
    if(search.done&&!search.error&&Date.now()-search.at<FRESH){listener(search);return()=>{search.listeners.delete(listener);prune();};}
    if(search.controller&&!search.done){listener(search);setLoading(true);return()=>leave();}
    // This view starts the search; the others follow it.
    const controller=new AbortController();Object.assign(search,{data:null,error:'',done:false,controller});setLoading(true);
    const run=async()=>{
      let value,continuing=false,previousProgress=-1,stalled=0;
      do{
        value=await service.request('/sources/discover',{method:'POST',body:{title,refresh:revision>0||continuing,continuing},signal:AbortSignal.any([controller.signal,AbortSignal.timeout(90000)])});
        if(controller.signal.aborted)return;
        // Each response contains the complete accumulated snapshot for this search.
        // Keeping earlier variants here resurrects expired Alloha links after refresh.
        search.data=value;publish(search);continuing=!!value.pending;
        stalled=continuing&&value.progress===previousProgress?stalled+1:0;previousProgress=value.progress;
        if(stalled>=90)throw Error('Часть источников перестала отвечать. Найденные переводы сохранены; можно повторить проверку позже.');
        if(continuing)await new Promise(resolve=>{const timer=setTimeout(done,600);function done(){clearTimeout(timer);controller.signal.removeEventListener('abort',done);resolve();}controller.signal.addEventListener('abort',done,{once:true});});
      }while(continuing);
    };
    run().catch(cause=>{if(!controller.signal.aborted)search.error=cause.message;})
      .finally(()=>{if(controller.signal.aborted)return;search.done=true;search.at=Date.now();search.controller=null;publish(search);});
    function leave(){
      search.listeners.delete(listener);
      // The last view leaving stops an unfinished search; while another view
      // still follows it, the search keeps running for that view.
      if(!search.listeners.size&&search.controller&&!search.done){search.controller.abort();searches.delete(key);}
      prune();
    }
    return leave;
  },[item?.id,item?.year,sourceURL,service.server,service.session?.serverVersion||service.status==='connected',revision]);
  return {data,loading,error,retry:()=>setRevision(r=>r+1)};
}
