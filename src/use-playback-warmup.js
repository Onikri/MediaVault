import {useCallback,useEffect,useRef} from 'react';
// Warm only the selected episode's resolver/manifests, never its media segments.
// The short preview capability is closed immediately; playback gets its own lease.
export default function usePlaybackWarmup({entry,sourceUrl,quality,service,enabled,anchor}){
 const live=useRef(null),pending=useRef(null),done=useRef(new Map());live.current={entry,sourceUrl,quality,service,enabled};
 const signature=[service.server,entry?.url,sourceUrl,quality].join('|');
 const warm=useCallback(()=>{
  const v=live.current;if(document.hidden||!v.enabled||!v.entry?.url||!v.service?.request||Number(v.service.session?.serverVersion||0)<49||navigator.connection?.saveData)return;
  if((done.current.get(signature)||0)>Date.now()||pending.current?.key===signature)return;
  const abort=new AbortController(),work={key:signature,abort};pending.current?.abort.abort();pending.current=work;
  v.service.request('/online/prepare',{method:'POST',body:{url:v.entry.url,referer:v.sourceUrl,kind:'video',quality:v.quality||'best',purpose:'preview',clientId:'watch-warm-'+crypto.randomUUID()},signal:AbortSignal.any([abort.signal,AbortSignal.timeout(15000)])}).then(async data=>{done.current.set(signature,Date.now()+45000);while(done.current.size>8)done.current.delete(done.current.keys().next().value);await v.service.request('/online/'+encodeURIComponent(data.id),{method:'DELETE',keepalive:true}).catch(()=>{});}).catch(()=>{}).finally(()=>{if(pending.current===work)pending.current=null;});
 },[signature]);
 useEffect(()=>{if(!enabled||!entry?.url)return;let timer;const idle=setTimeout(warm,1500);const node=anchor?.current;if(!node)return()=>{clearTimeout(idle);pending.current?.abort.abort();};const observer=new IntersectionObserver(entries=>{clearTimeout(timer);if(entries.some(e=>e.isIntersecting))timer=setTimeout(warm,800);},{rootMargin:'180px'});observer.observe(node);return()=>{clearTimeout(timer);clearTimeout(idle);observer.disconnect();pending.current?.abort.abort();};},[signature,enabled,warm,anchor]);
 useEffect(()=>()=>pending.current?.abort.abort(),[]);
 return warm;
}
