import {useEffect,useRef,useState} from 'react';
import {frame} from './OnlineEpisodePreviews.jsx';
import {readEpisodeFrames,saveEpisodeFrames} from './episode-preview-cache.js';
export default function EpisodeMotionPreview({prepare,cacheKey,onActive,children}){
 const [active,setActive]=useState(false),[images,setImages]=useState([]),[index,setIndex]=useState(0),timer=useRef(),live=useRef({prepare,onActive});live.current={prepare,onActive};
 const [motion,setMotion]=useState(()=>!matchMedia('(prefers-reduced-motion: reduce)').matches);
 useEffect(()=>{const query=matchMedia('(prefers-reduced-motion: reduce)'),update=()=>setMotion(!query.matches);query.addEventListener('change',update);return()=>query.removeEventListener('change',update);},[]);
 const enabled=!navigator.connection?.saveData&&motion;
 useEffect(()=>{if(!active||!enabled)return;const abort=new AbortController();let stream;live.current.onActive?.(true);
  (async()=>{const cached=cacheKey?await readEpisodeFrames(cacheKey):images;if(cached.length>1){setImages(cached);return;}stream=await live.current.prepare(abort.signal);if(abort.signal.aborted)return;const frames=await frame(stream.url,stream.type,abort.signal,true,values=>{if(!abort.signal.aborted){setImages(values);if(cacheKey)saveEpisodeFrames(cacheKey,values);}});if(frames?.length>1&&!abort.signal.aborted){setImages(frames);if(cacheKey)saveEpisodeFrames(cacheKey,frames);}})().catch(()=>{}).finally(()=>stream?.close?.());
  return()=>{abort.abort();stream?.close?.();live.current.onActive?.(false);};
 },[active,cacheKey,enabled]);
 useEffect(()=>{if(!active||images.length<2)return;const id=setInterval(()=>setIndex(n=>(n+1)%images.length),850);return()=>clearInterval(id);},[active,images]);
 useEffect(()=>()=>clearTimeout(timer.current),[]);
 return <span className="episode-motion" onPointerEnter={e=>{if(enabled&&e.pointerType!=='touch')timer.current=setTimeout(()=>setActive(true),220);}} onPointerLeave={()=>{clearTimeout(timer.current);setActive(false);}} onFocus={()=>enabled&&setActive(true)} onBlur={()=>setActive(false)}>{children}{active&&images.length>1&&<><img className="episode-motion-frame" src={images[index%images.length]} alt="Кадры серии"/><span className="episode-motion-dots">{images.map((_,i)=><i key={i} data-active={i===index%images.length}/>)}</span></>}</span>;
}
