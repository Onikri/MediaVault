import {useEffect,useRef,useState,useSyncExternalStore} from 'react';
import {X,Play,Pause,Music2,Heart,ExternalLink} from 'lucide-react';
import {musicSnapshot,subscribeMusic,closeMusic} from './music-player.js';
import {toggleTrack,tracks,spotifySearch,youtubeSearch} from './music-library.js';
import YouTubeEmbed from './YouTubeEmbed.jsx';
export default function MiniMusicPlayer({userId}){
 const state=useSyncExternalStore(subscribeMusic,musicSnapshot),track=state?.track;
 const [results,setResults]=useState([]),[selected,setSelected]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[playing,setPlaying]=useState(false),[saved,setSaved]=useState(false),controller=useRef(null),scope=useRef(userId);
 useEffect(()=>{if(scope.current!==userId){scope.current=userId;closeMusic();}},[userId]);
 useEffect(()=>{if(!track)return;const abort=new AbortController();setResults([]);setSelected('');setError('');setPlaying(false);setSaved(tracks(userId).some(t=>t.id===track.id));setBusy(true);
  const server=window.MEDIA_VAULT_CONFIG?.importServerUrl;
  if(!server){setError('Сервер поиска музыки не подключён.');setBusy(false);return;}
  fetch(server+'/music/search?'+new URLSearchParams({title:track.title,artist:(track.artists||[]).join(' ')}),{signal:AbortSignal.any([abort.signal,AbortSignal.timeout(25000)])}).then(async r=>{const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'Поиск YouTube временно недоступен.');return d;}).then(d=>{if(abort.signal.aborted)return;setResults(d.results||[]);const best=d.results?.[0];if(best?.match)setSelected(best.id);else if(!d.results?.length)setError('Запись не найдена. Открой поиск YouTube Music или выбери другую песню.');}).catch(e=>{if(!abort.signal.aborted)setError(e.message);}).finally(()=>{if(!abort.signal.aborted)setBusy(false);});return()=>abort.abort();
 },[state?.request,track?.id,userId]);
 if(!track)return null;
 function toggle(){const p=controller.current;if(p){try{playing?p.pauseVideo():p.playVideo();}catch{}}}
 return <aside className="mini-music" aria-label="Музыкальный мини-плеер"><header><span className="mini-music-disc"><Music2 size={19}/></span><div><strong>{track.title}</strong><small>{track.artists?.join(', ')||'Музыка из аниме'}</small></div><button aria-label="Закрыть музыкальный плеер" onClick={closeMusic}><X size={18}/></button></header>
 {selected?<YouTubeEmbed key={selected} videoId={selected} title={track.title} autoplay controller={controller} onState={s=>{setPlaying(s===1);if(s===1)dispatchEvent(new Event('mediavault-music-playing'));}} onError={setError}/>:<div className="mini-music-search" role="status">{busy?<><span className="loading-ring"/>Ищем запись на YouTube…</>:error||'Выбери запись'}</div>}
 {results.length>0&&<label className="mini-recording-label">Запись<select aria-label="Запись YouTube" value={selected} onChange={e=>{setSelected(e.target.value);setError('');}}><option value="">Выбрать запись</option>{results.map(r=><option value={r.id} key={r.id}>{r.title} · {r.author}</option>)}</select></label>}
 <footer><button aria-label={playing?'Пауза музыки':'Продолжить музыку'} onClick={toggle} disabled={!selected}>{playing?<Pause size={18}/>:<Play size={18}/>}</button><button aria-label="Музыку в избранное" aria-pressed={saved} onClick={()=>{toggleTrack(userId,track);setSaved(v=>!v);}}><Heart size={18} fill={saved?'currentColor':'none'}/></button><a href={youtubeSearch(track)} target="_blank" rel="noopener noreferrer">YouTube Music <ExternalLink size={12}/></a><a href={spotifySearch(track)} target="_blank" rel="noopener noreferrer">Spotify</a></footer>{selected&&error&&<p role="status" className="fine">{error}</p>}<small className="mini-music-attribution">Воспроизведение YouTube · доступность зависит от региона и автора</small></aside>;
}
