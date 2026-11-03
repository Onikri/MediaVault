import {useEffect,useState} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {Play,X,Film,ExternalLink} from 'lucide-react';
import MediaVaultPlayer from './MediaVaultPlayer.jsx';
import {extractYouTubeId} from './blossom/utils/trailer.ts';

function TrailerVideo({video,profile,server,userId,onPlaybackChange}){
 const [data,setData]=useState(null),[error,setError]=useState(''),[retry,setRetry]=useState(0);
 useEffect(()=>{
  const abort=new AbortController();let timer;setData(null);setError('');
  const id=String(video.id||extractYouTubeId(video.url)||'');
  async function status(job){
   if(abort.signal.aborted)return;
   if(job.status==='ready'){setData({url:server+'/trailers/stream/'+job.id});return;}
   if(job.status==='unavailable')throw Error(job.message||'Источник не отдал ролик.');
   timer=setTimeout(()=>fetch(server+'/trailers/status/'+job.id,{signal:abort.signal}).then(r=>r.ok?r.json():Promise.reject(Error('Подготовка ролика истекла.'))).then(status).catch(failed),1000);
  }
  function failed(e){if(!abort.signal.aborted)setError(e.message||'Не удалось подготовить ролик.');}
  if(!server||!/^\d+$/.test(String(profile.sourceId||''))){setError('Для этого ролика не удалось подтвердить тайтл в каталоге.');return;}
  fetch(server+'/trailers/prepare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({anime_id:String(profile.sourceId),video_id:id}),signal:abort.signal}).then(async r=>{const value=await r.json();if(!r.ok)throw Error(typeof value.detail==='string'?value.detail:'Сервер пока готовит другие ролики.');return value;}).then(status).catch(failed);
  return()=>{abort.abort();clearTimeout(timer);};
 },[video.id,video.url,profile.sourceId,server,retry]);
 const item={id:'trailer:'+profile.sourceId+':'+video.id,name:video.title,category:'video',section:'anime',onlineType:'mp4',metadataId:profile.sourceId,preview:video.image};
 return data?<MediaVaultPlayer item={item} source={data.url} userId={userId} libraryId="trailers" autoPlay catalog={{items:[item]}} onPlaybackChange={onPlaybackChange}/>:<div className="trailer-preparation" role="status"><Film size={28}/><p>{error||'Готовим проморолик…'}</p>{error&&<button className="btn btn-secondary" onClick={()=>setRetry(n=>n+1)}>Повторить</button>}</div>;
}
export default function Trailers({profile,renderArtwork,onPlaybackChange,server=window.MEDIA_VAULT_CONFIG?.importServerUrl,userId}){
 const[selected,setSelected]=useState(null);
 if(!profile.trailers?.length)return null;
 return <section className="title-trailers"><div className="section-heading"><h2><Film size={17}/>Трейлеры и проморолики</h2></div><div className="trailer-grid">{profile.trailers.map((v,i)=><button key={v.id||v.url} onClick={()=>{document.querySelectorAll('video.mv-player-media').forEach(v=>v.pause());setSelected(v);}}><span className="trailer-cover">{renderArtwork(v)}<span className="trailer-play"><Play size={23} fill="currentColor"/></span><small>{String(i+1).padStart(2,'0')}</small></span><strong>{v.title}</strong></button>)}</div>
 <Dialog.Root open={!!selected} onOpenChange={open=>{if(!open){setSelected(null);onPlaybackChange?.(false);}}}><Dialog.Portal><Dialog.Overlay className="dialog-overlay"/><Dialog.Content className="trailer-dialog"><header className="entity-dialog-heading"><div><Dialog.Title>{selected?.title}</Dialog.Title><Dialog.Description>{profile.title}</Dialog.Description></div><Dialog.Close className="circle-button" aria-label="Закрыть трейлер"><X size={19}/></Dialog.Close></header>{selected&&<TrailerVideo video={selected} profile={profile} server={server} userId={userId} onPlaybackChange={onPlaybackChange}/>}<footer className="entity-sources">{selected?.url&&<a href={selected.url} target="_blank" rel="noopener noreferrer">Страница ролика<ExternalLink size={12}/></a>}</footer></Dialog.Content></Dialog.Portal></Dialog.Root></section>;
}
