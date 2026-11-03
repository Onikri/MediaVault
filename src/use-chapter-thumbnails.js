import {useEffect,useRef,useState} from 'react';
import {readEpisodePreview,saveEpisodePreview} from './episode-preview-cache.js';
import useVisibleCards from './use-visible-cards.js';

export default function useChapterThumbnails(root,entries,service,userId,enabled){
 const [images,setImages]=useState({}),[retry,setRetry]=useState(0),live=useRef(service);live.current=service;
 const signature=entries.map(e=>e.url+':'+(e.thumbnail||'')).join('\n'),visible=useVisibleCards(root,signature);
 useEffect(()=>{
  if(!enabled||Number(service.session?.serverVersion||0)<43||service.status!=='connected'||navigator.connection?.saveData)return;
  const abort=new AbortController();let timer;
  (async()=>{
   let failed=false;
   for(const entry of entries){
    if(abort.signal.aborted)return;if(!visible.has(entry.url)||images[entry.url]||entry.thumbnail)continue;
    const key='chapter-thumb-v1:'+service.server+':'+(userId||'anonymous')+':'+entry.url;
    try{
     let image=await readEpisodePreview(key);abort.signal.throwIfAborted();
     if(!image){const data=await live.current.request('/manga/thumbnail',{method:'POST',body:{url:entry.url},signal:AbortSignal.any([abort.signal,AbortSignal.timeout(45000)])});image=data.image;if(image?.startsWith('data:image/jpeg;base64,')&&image.length<=150000)await saveEpisodePreview(key,image);else continue;}
     if(!abort.signal.aborted)setImages(old=>({...old,[entry.url]:image}));
    }catch{if(abort.signal.aborted)return;failed=true;}
   }
   if(failed&&!abort.signal.aborted)timer=setTimeout(()=>setRetry(n=>n+1),15000);
  })();
  return()=>{abort.abort();clearTimeout(timer);};
 },[signature,visible,enabled,service.status,service.session?.serverVersion,service.server,userId,retry]);
 return images;
}
