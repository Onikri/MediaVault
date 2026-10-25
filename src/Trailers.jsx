import {useEffect,useRef,useState} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {Play,X,Film} from 'lucide-react';
import VideoPlayer from './VideoPlayer.jsx';
export default function Trailers({profile,userId,libraryId,renderArtwork,onPlaybackChange}){
  const [selected,setSelected]=useState(null),[status,setStatus]=useState(''),[error,setError]=useState(''),[source,setSource]=useState('');
  const generation=useRef(0),server=window.MEDIA_VAULT_CONFIG?.importServerUrl;
  useEffect(()=>{
    if(!selected)return;let closed=false,timer;const abort=new AbortController(),version=++generation.current;
    setSource('');setError('');setStatus('preparing');
    async function check(id){try{
      if(!server)throw Error('Для подготовки трейлера нужен сервер MediaVault.');
      const response=await fetch(server+(id?'/trailers/status/'+id:'/trailers/prepare'),{...(id?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({anime_id:String(profile.sourceId),video_id:String(selected.id)})}),signal:AbortSignal.any([abort.signal,AbortSignal.timeout(20000)])});
      const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Не удалось подготовить трейлер.');
      if(closed||version!==generation.current)return;setStatus(data.status);
      if(data.status==='ready')setSource(server+'/trailers/stream/'+data.id);
      else if(data.status==='preparing')timer=setTimeout(()=>check(data.id),2000);
      else setError(data.message||'Источник не предоставил этот ролик.');
    }catch(cause){if(!closed){setError(cause.message);setStatus('unavailable');}}}
    check();return()=>{closed=true;abort.abort();clearTimeout(timer);onPlaybackChange?.(false);};
  },[selected?.id,profile.sourceId,server]);
  if(!profile.trailers?.length)return null;
  const item=selected?{id:'trailer-'+profile.sourceId+'-'+selected.id,name:selected.title,category:'video',section:'video'}:null;
  return <section className="title-trailers"><div className="section-heading"><h2><Film size={17}/>Трейлеры и проморолики</h2><span className="fine">В плеере MediaVault</span></div><div className="trailer-grid">{profile.trailers.map((value,index)=><button key={value.id} onClick={()=>setSelected(value)}><span className="trailer-cover">{renderArtwork(value)}<span className="trailer-play"><Play size={23} fill="currentColor"/></span><small>{String(index+1).padStart(2,'0')}</small></span><strong>{value.title}</strong></button>)}</div>
    <Dialog.Root open={!!selected} onOpenChange={open=>{if(!open)setSelected(null);}}><Dialog.Portal><Dialog.Overlay className="dialog-overlay"/><Dialog.Content className="trailer-dialog"><div className="trailer-dialog-heading"><div><Dialog.Title>{selected?.title}</Dialog.Title><Dialog.Description>{profile.title} · Плеер MediaVault</Dialog.Description></div><Dialog.Close className="icon-button" aria-label="Закрыть трейлер"><X size={19}/></Dialog.Close></div>
      {source&&item?<VideoPlayer key={item.id} item={item} source={source} catalog={{items:[item]}} libraryId={libraryId+':trailers'} userId={userId} onError={cause=>setError(cause.message)} onPlaybackChange={onPlaybackChange}/>:<div className="trailer-preparing">{status==='preparing'&&<span className="loading-ring"/>}<p role="status">{status==='preparing'?'Подготавливаем ролик для нашего плеера…':error}</p><small>Ролик откроется здесь, как только будет готов.</small></div>}
      {source&&error&&<p className="inline-error">{error}</p>}
    </Dialog.Content></Dialog.Portal></Dialog.Root>
  </section>;
}
