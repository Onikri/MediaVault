import {useEffect,useMemo,useState} from 'react';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {ExternalLink,Play} from 'lucide-react';
import {playMusic} from './music-player.js';
import {loadEpisodeOst,ostTrack,spotifyTrackUrl} from './use-episode-ost.js';
import './episode-soundtrack.css';

// "What plays in which episode": WTAS.moe's recognised background music, with a
// timeline of the episode and the official Spotify track where it is known.
const clock=v=>{v=Math.max(0,Math.floor(v||0));return Math.floor(v/60)+':'+String(v%60).padStart(2,'0');};
const hue=text=>{let h=0;for(const c of String(text))h=(h*31+c.charCodeAt(0))%360;return h;};
export default function EpisodeSoundtrack({identity}){
 const server=window.MEDIA_VAULT_CONFIG?.importServerUrl,reduce=useReducedMotion();
 const [title,setTitle]=useState(null),[episode,setEpisode]=useState(1),[data,setData]=useState(null),[error,setError]=useState(''),[uncertain,setUncertain]=useState(false);
 useEffect(()=>{setTitle(null);if(!/^\d+$/.test(String(identity||''))||!server)return;const abort=new AbortController();
  fetch(server+'/music/ost/'+identity,{signal:AbortSignal.any([abort.signal,AbortSignal.timeout(15000)])}).then(r=>r.ok?r.json():null).then(v=>{if(!abort.signal.aborted&&v?.available){setTitle(v);setEpisode(v.episodes[0]);}}).catch(()=>{});
  return()=>abort.abort();},[identity,server]);
 useEffect(()=>{setData(null);setError('');if(!title)return;const abort=new AbortController();
  loadEpisodeOst(server,identity,episode,AbortSignal.any([abort.signal,AbortSignal.timeout(20000)])).then(v=>{if(!abort.signal.aborted)setData(v);}).catch(e=>{if(!abort.signal.aborted)setError(e.message);});
  return()=>abort.abort();},[title,episode]);
 const tracks=(data?.tracks||[]).filter(t=>uncertain||!t.uncertain);
 const groups=useMemo(()=>{const map=new Map();for(const t of tracks){if(!map.has(t.title))map.set(t.title,{...t,segments:[]});map.get(t.title).segments.push(t);}return [...map.values()].sort((a,b)=>a.segments[0].start-b.segments[0].start);},[data,uncertain]);
 const hidden=(data?.tracks||[]).filter(t=>t.uncertain).length;
 if(!title)return null;
 const length=Number(data?.episodeDuration)||Math.max(1,...(data?.tracks||[]).map(t=>t.end));
 const queue=groups.map(g=>ostTrack(g));
 return <div className="episode-ost">
  <div className="episode-ost-head"><h3>Саундтрек по сериям</h3><span>Какая фоновая музыка звучит в каждой серии</span></div>
  <div className="episode-ost-episodes" role="tablist" aria-label="Серия">{title.episodes.map(n=><button key={n} type="button" role="tab" aria-selected={n===episode} onClick={()=>setEpisode(n)}>{n===episode&&<motion.span layoutId="episode-ost-active" className="episode-ost-active" transition={reduce?{duration:0}:{type:'spring',stiffness:420,damping:36}}/>}<span>{n}</span></button>)}</div>
  {error?<p className="fine" role="alert">{error}</p>:!data?<p className="fine" role="status">Загружаем музыку {episode} серии…</p>:<>
   <div className="episode-ost-timeline" aria-hidden="true">{tracks.map(t=><i key={t.title+t.start} title={t.title+' · '+clock(t.start)+'–'+clock(t.end)} style={{left:t.start/length*100+'%',width:Math.max(.6,(t.end-t.start)/length*100)+'%','--track-hue':hue(t.title),opacity:t.uncertain?.45:1}}/>)}<span>{[0,.25,.5,.75,1].map(f=><small key={f} style={{left:f*100+'%'}}>{clock(f*length)}</small>)}</span></div>
   <ul className="episode-ost-list"><AnimatePresence initial={false}>{groups.map(g=><motion.li key={g.title} layout={!reduce} initial={reduce?false:{opacity:0,y:6}} animate={{opacity:1,y:0}} exit={{opacity:0}}>
    <span className="episode-ost-swatch" style={{'--track-hue':hue(g.title)}}/>
    <div className="episode-ost-text"><strong>{g.title}</strong><small>{g.album||'Саундтрек'}{g.segments.some(s=>s.uncertain)?' · неуверенно':''}</small><span>{g.segments.map(s=><em key={s.start}>≈ {clock(s.start)}–{clock(s.end)}</em>)}</span></div>
    <div className="episode-ost-actions">
     <button type="button" aria-label={'Слушать '+g.title} title="Слушать" onClick={()=>playMusic(ostTrack(g),queue)}><Play size={15} fill="currentColor" strokeWidth={0}/></button>
     {spotifyTrackUrl(g.spotify)&&<a href={spotifyTrackUrl(g.spotify)} target="_blank" rel="noopener noreferrer" aria-label={'Официальный трек в Spotify: '+g.title} title="Официальный трек в Spotify"><ExternalLink size={15}/></a>}
    </div>
   </motion.li>)}</AnimatePresence></ul>
   {!groups.length&&<p className="fine">В этой серии уверенных совпадений нет.</p>}
   {hidden>0&&<button type="button" className="episode-ost-toggle" onClick={()=>setUncertain(v=>!v)}>{uncertain?'Скрыть неуверенные совпадения':'Показать неуверенные совпадения · '+hidden}</button>}
  </>}
  <p className="soundtrack-note">Данные: <a href={data?.url||title.url} target="_blank" rel="noopener noreferrer">WTAS.moe</a> — автоматическое распознавание музыки, время приблизительное и возможны ошибки.{title.albums?.length>0&&<> Альбомы: {title.albums.map((a,i)=><span key={a.url}>{i?', ':''}<a href={a.url} target="_blank" rel="noopener noreferrer">{a.name}</a></span>)}.</>}</p>
 </div>;
}
