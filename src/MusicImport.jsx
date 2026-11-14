import {useEffect,useState,useSyncExternalStore} from 'react';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {ArrowLeft,LoaderCircle,Play,Trash2} from 'lucide-react';
import {connectSpotify,connectYouTube,configuredSpotifyClient} from './music-connectors.js';
import {importMusicLibrary,importedPlaylists,subscribeMusicLibrary,forgetImportedPlaylist} from './music-import.js';
import {playMusic} from './music-player.js';
import './music-import.css';

const PROVIDERS=[['youtube','YouTube Music','Плейлисты и понравившиеся песни'],['spotify','Spotify','Плейлисты твоего аккаунта']];
// «Импортировать библиотеку»: one press opens the service's own sign-in, then
// every playlist lands here and plays right away.
export default function MusicImport(){
 const reduce=useReducedMotion(),lists=useSyncExternalStore(subscribeMusicLibrary,()=>localSnapshot(),()=>'[]');
 const playlists=JSON.parse(lists),[busy,setBusy]=useState(''),[progress,setProgress]=useState(''),[error,setError]=useState(''),[open,setOpen]=useState(null),[client,setClient]=useState(configuredSpotifyClient()),[askClient,setAskClient]=useState(false);
 useEffect(()=>{if(open&&!playlists.some(p=>p.id===open))setOpen(null);},[lists]);
 async function start(provider){
  if(provider==='spotify'&&!/^[a-f\d]{32}$/i.test(client)){setAskClient(true);return;}
  setBusy(provider);setError('');setProgress('Открываем вход '+(provider==='spotify'?'Spotify':'Google')+'…');
  try{
   if(provider==='spotify')await connectSpotify(client);else await connectYouTube();
   const count=await importMusicLibrary(provider,(n,total,name)=>setProgress('Плейлист '+n+' из '+total+': '+name));
   setProgress(count?'Готово: '+count+' '+(count%10===1&&count%100!==11?'плейлист':count%10>=2&&count%10<=4&&(count%100<12||count%100>14)?'плейлиста':'плейлистов')+'.':'В аккаунте не нашлось плейлистов с песнями.');
  }catch(e){setError(e.message||'Импорт не удался.');setProgress('');}
  finally{setBusy('');}
 }
 const current=playlists.find(p=>p.id===open);
 return <section className="music-import" aria-labelledby="music-import-title">
  <header className="music-import-head"><h2 id="music-import-title">Моя музыка</h2><p>Перенеси плейлисты из своего аккаунта — песни сразу можно слушать здесь.</p></header>
  <div className="music-import-providers">{PROVIDERS.map(([id,name,text])=><button key={id} type="button" className={'music-import-provider is-'+id} disabled={!!busy} onClick={()=>start(id)}>
   <span className="music-import-mark" aria-hidden="true">{id==='youtube'?<svg viewBox="0 0 24 24" width="22" height="22"><circle cx="12" cy="12" r="10" fill="currentColor"/><path d="M10 8.5v7l6-3.5z" fill="#fff"/></svg>:<svg viewBox="0 0 24 24" width="22" height="22"><circle cx="12" cy="12" r="10" fill="currentColor"/><path d="M7 9.5c3.5-1 7.3-.7 10 .9M7.6 12.4c3-.8 6.1-.5 8.4.8M8.2 15.1c2.4-.6 4.8-.4 6.6.6" stroke="#000" strokeWidth="1.5" strokeLinecap="round" fill="none"/></svg>}</span>
   <span><strong>{busy===id?'Импортируем…':'Импорт из '+name}</strong><small>{text}</small></span>
   {busy===id&&<LoaderCircle className="music-import-spin" size={18} aria-hidden="true"/>}
  </button>)}</div>
  {askClient&&<form className="music-import-client" onSubmit={event=>{event.preventDefault();localStorage.setItem('mediavault_spotify_client',client.trim());setAskClient(false);start('spotify');}}>
   <p>Spotify пускает сайты только через своё приложение. Вставь публичный Client ID приложения Spotify (секрет не нужен) — это нужно сделать один раз.</p>
   <input value={client} onChange={event=>setClient(event.target.value)} placeholder="Client ID, 32 символа" aria-label="Client ID приложения Spotify" autoComplete="off"/><button type="submit" className="btn btn-primary">Продолжить</button>
  </form>}
  {(progress||error)&&<p className={'music-import-status'+(error?' is-error':'')} role={error?'alert':'status'}>{error||progress}</p>}
  <AnimatePresence mode="wait" initial={false}>
   {current?<motion.div key="list" className="music-import-tracks" initial={reduce?false:{opacity:0,x:24}} animate={{opacity:1,x:0}} exit={{opacity:0,x:-24}}>
    <div className="music-import-tracks-head"><button type="button" className="circle-button" aria-label="Ко всем плейлистам" onClick={()=>setOpen(null)}><ArrowLeft size={18}/></button><div><h3>{current.name}</h3><small>{current.tracks.length} песен · {current.provider==='spotify'?'Spotify':'YouTube'}</small></div><button type="button" className="btn btn-primary" onClick={()=>playMusic(current.tracks[0],current.tracks)}><Play size={16} fill="currentColor"/>Слушать</button><button type="button" className="circle-button" aria-label="Убрать плейлист" title="Убрать плейлист" onClick={()=>forgetImportedPlaylist(current.id)}><Trash2 size={16}/></button></div>
    <ol>{current.tracks.map((track,i)=><li key={track.id+i}><button type="button" onClick={()=>playMusic(track,current.tracks)}><span className="music-import-index">{i+1}</span>{track.cover?<img src={track.cover} alt="" loading="lazy" referrerPolicy="no-referrer"/>:<span className="music-import-cover-empty"/>}<span className="music-import-track"><strong>{track.title}</strong>{track.artists?.length>0&&<small>{track.artists.join(', ')}</small>}</span></button></li>)}</ol>
   </motion.div>
   :playlists.length>0&&<motion.div key="grid" className="music-import-grid" initial={reduce?false:{opacity:0}} animate={{opacity:1}} exit={{opacity:0}}>{playlists.map(list=><button key={list.id} type="button" className="music-import-playlist" onClick={()=>setOpen(list.id)}>
    <span className="music-import-art">{list.cover?<img src={list.cover} alt="" loading="lazy" referrerPolicy="no-referrer"/>:null}<span className="music-import-play" aria-hidden="true"><Play size={18} fill="currentColor"/></span></span>
    <strong>{list.name}</strong><small>{list.tracks.length} песен · {list.provider==='spotify'?'Spotify':'YouTube'}</small>
   </button>)}</motion.div>}
  </AnimatePresence>
 </section>;
}
const localSnapshot=()=>JSON.stringify(importedPlaylists());
