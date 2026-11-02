import {useEffect,useLayoutEffect,useMemo,useRef,useState,useSyncExternalStore} from 'react';
import {createPortal} from 'react-dom';
import {AnimatePresence,motion,useMotionValue,useReducedMotion} from 'motion/react';
import {X,Play,Pause,Music2,Heart,ExternalLink,SkipBack,SkipForward,Volume2,ListMusic,ChevronDown,Headphones,Settings2,ArrowLeft,Maximize2,Minimize2} from 'lucide-react';
import {musicSnapshot,subscribeMusic,closeMusic,stepMusic,playMusic} from './music-player.js';
import {toggleTrack,tracks} from './music-library.js';
import {disconnectMusic} from './music-connectors.js';
import MusicConnections from './MusicConnections.jsx';
import {openYouTubeAudio,openMusicAudio} from './youtube-audio.js';
import {musicIslandLayout} from './music-island.js';
import {cursorMusicTime} from './music-timeline.js';
import './music-dock.css';
import useLyrics from './use-lyrics.js';
import SyncedLyrics from './SyncedLyrics.jsx';
import {parseLrc,parseTtml} from './lyrics.js';
import './lyrics.css';
import './glass-popover.css';
import {musicIdentity} from './music-identity.js';
import {GLASS_ENTER,GLASS_HIDDEN,GLASS_VISIBLE} from './glass-motion.js';
const clock=value=>{const n=Math.max(0,Math.floor(Number(value)||0));return Math.floor(n/60)+':'+String(n%60).padStart(2,'0');};
const imageURL=value=>{try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password?u.href:'';}catch{return '';}};

export default function MiniMusicPlayer({userId,prepareStream,readWhole,resolveItem,placement='dock',service}){
 const reduce=useReducedMotion();
 const [audioRetry,setAudioRetry]=useState(0);
 const state=useSyncExternalStore(subscribeMusic,musicSnapshot),track=state?.track,native=!!track&&['library','file'].includes(track.source),remote=track?.source==='url',youtube=!!track&&!native&&!remote,nav=placement==='nav',serverAudio=(youtube||remote)&&!!service?.request,audioBacked=native||serverAudio;
 const [results,setResults]=useState([]),[selection,setSelection]=useState(null),[stream,setStream]=useState({request:null,url:''}),[busy,setBusy]=useState(false),[error,setError]=useState(''),[playing,setPlaying]=useState(false),[saved,setSaved]=useState(false),[time,setTime]=useState(0),[duration,setDuration]=useState(0),[volume,setVolume]=useState(.8),[queue,setQueue]=useState(false),[expanded,setExpanded]=useState(false),[connections,setConnections]=useState(false),[metadata,setMetadata]=useState(null),[failedCover,setFailedCover]=useState('');
 const source=stream.request===state?.request?stream.url:'';const setSource=url=>setStream({request:state?.request,url});
 const selected=selection&&selection.request===state?.request?selection.id:'';const setSelected=id=>setSelection({id,request:state?.request});
 const audio=useRef(null),scope=useRef(userId),gesture=useRef(null),methods=useRef({prepareStream,readWhole,resolveItem});methods.current={prepareStream,readWhole,resolveItem};
 const volumeKnob=useRef(null),volumeDrag=useRef(null),volumeMoved=useRef(false),previousVolume=useRef(.8);
 const [barHovered,setBarHovered]=useState(false),[barKeyboard,setBarKeyboard]=useState(false);
 const [navFull,setNavFull]=useState(false);
 const circle=useRef(null),circleGesture=useRef(null),circleSkipClick=useRef(false);
 const [scrubPreview,setScrubPreview]=useState(null);
 const scrubPosition=useMotionValue('0%');
 const [lyricsEnabled,setLyricsEnabled]=useState(()=>{try{return localStorage.getItem('mediavault_lyrics_enabled')!=='false';}catch{return true;}}),[manualLyrics,setManualLyrics]=useState(null),[lyricOffset,setLyricOffset]=useState(0),[lyricError,setLyricError]=useState(''),[lyricsOpen,setLyricsOpen]=useState(false),lyricFile=useRef(null);
 const identity=useMemo(()=>musicIdentity(track||{}),[track]);
 const lyricTrack=useMemo(()=>track?{...track,aliases:[...track.aliases||[],metadata?.title].filter(Boolean),artists:[...track.artists||[],...metadata?.artists||[]],album:metadata?.album||track.album,year:metadata?.date||track.year}:null,[track,metadata?.title,metadata?.artists,metadata?.album,metadata?.date]);
 const lyricKey=track?.id+':'+selected,automaticLyrics=useLyrics(lyricTrack,duration,lyricsEnabled&&audioBacked),lyricData=manualLyrics?.key===lyricKey?manualLyrics.data:automaticLyrics;
 useEffect(()=>{try{setLyricOffset(Number(localStorage.getItem('mv_lyric_offset:'+lyricKey))||0);}catch{setLyricOffset(0);}setLyricError('');},[lyricKey]);
 const shiftLyrics=value=>{setLyricOffset(value);try{localStorage.setItem('mv_lyric_offset:'+lyricKey,String(value));}catch{}};
 async function importLyrics(event){const file=event.target.files?.[0];event.target.value='';if(!file)return;try{if(file.size>1000000)throw Error('Файл текста превышает 1 МБ.');const text=await file.text(),parsed=/\.(ttml|xml)$/i.test(file.name)?parseTtml(text):parseLrc(text);if(!parsed.lines.length)throw Error('В файле нет временной разметки.');setManualLyrics({key:lyricKey,data:{...parsed,phase:'ready',source:'Твой файл'}});setLyricError('');}catch(e){setLyricError(e.message);}}
 const activeLyric=<SyncedLyrics data={lyricData} audioRef={audio} playing={playing} offset={lyricOffset} enabled={lyricsEnabled}/>;

 useEffect(()=>{if(!nav)return;dispatchEvent(new CustomEvent('mediavault:music-expanded',{detail:navFull&&!!track}));return()=>dispatchEvent(new CustomEvent('mediavault:music-expanded',{detail:false}));},[nav,navFull,!!track]);
 useEffect(()=>{const hide=()=>{setNavFull(false);setExpanded(false);};addEventListener('mediavault:search-open',hide);return()=>removeEventListener('mediavault:search-open',hide);},[]);
 useEffect(()=>{if(!track)setNavFull(false);},[!!track]);
 useEffect(()=>{if(!navFull)return;const key=e=>{if(e.key==='Escape'){e.preventDefault();setNavFull(false);}};window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key);},[navFull]);
 useEffect(()=>{const el=circle.current;if(!el||!navFull)return;const wheel=e=>{e.preventDefault();setVolume(v=>Math.max(0,Math.min(1,Math.round((v+(e.deltaY<0?.05:-.05))*100)/100)));};el.addEventListener('wheel',wheel,{passive:false});return()=>el.removeEventListener('wheel',wheel);},[navFull]);
 const onCircleDown=e=>{if(e.button!==0)return;circleSkipClick.current=false;circleGesture.current={id:e.pointerId,x:e.clientX,y:e.clientY,t:time,v:volume,rect:barElement.current?.getBoundingClientRect(),mode:null,preview:time};e.currentTarget.setPointerCapture(e.pointerId);};
 const onCircleMove=e=>{const g=circleGesture.current;if(!g||g.id!==e.pointerId)return;const dx=e.clientX-g.x,dy=e.clientY-g.y;
  if(!g.mode&&Math.hypot(dx,dy)>9)g.mode=Math.abs(dx)>=Math.abs(dy)?'seek':'volume';
  if(!g.mode)return;
  circleSkipClick.current=true;
  if(g.mode==='volume'){setVolume(Math.max(0,Math.min(1,Math.round((g.v-dy/130)*100)/100)));return;}
  if(duration>0){
   const next=cursorMusicTime(e.clientX,g.rect,duration);g.preview=next;
   scrubPosition.set((next/duration*100)+'%');
   const second=Math.floor(next);
   if(g.lastSecond!==second){g.lastSecond=second;setScrubPreview({time:next});}
  }
 };
 const onCircleUp=e=>{const g=circleGesture.current;if(!g||g.id!==e.pointerId)return;
  circleGesture.current=null;if(g.mode==='seek'&&duration>0&&e.type!=='pointercancel')seek(g.preview);
  setScrubPreview(null);
  if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId);
 };

 const barElement=useRef(null),keyboardNavigation=useRef(false);
 // A captured pointer may suppress React pointerleave, so determine hover from
 // global pointer coordinates rather than the button's event bubbling.
 useEffect(()=>{if(!track||!nav)return;
  const inside=(event)=>{const r=barElement.current?.getBoundingClientRect();return !!r&&event.clientX>=r.left&&event.clientX<r.right&&event.clientY>=r.top&&event.clientY<r.bottom;};
  const onMove=event=>{if(event.pointerType!=='mouse')return;const hovered=inside(event);setBarHovered(value=>value===hovered?value:hovered);if(!hovered&&barElement.current?.contains(document.activeElement))document.activeElement.blur();};
  const onDown=()=>{keyboardNavigation.current=false;setBarKeyboard(false);};
  const onKey=event=>{if(event.key==='Tab'||event.key.startsWith('Arrow'))keyboardNavigation.current=true;};
  document.addEventListener('pointermove',onMove,{capture:true,passive:true});
  document.addEventListener('pointerdown',onDown,{capture:true,passive:true});
  document.addEventListener('keydown',onKey,{capture:true});
  return()=>{document.removeEventListener('pointermove',onMove,true);document.removeEventListener('pointerdown',onDown,true);document.removeEventListener('keydown',onKey,true);};
 },[!!track,nav]);
 const trigger=useRef(null),island=useRef(null),content=useRef(null),[islandBox,setIslandBox]=useState(()=>musicIslandLayout(null,{width:innerWidth,height:innerHeight},180,placement));
 useLayoutEffect(()=>{let frame=0;const update=()=>{frame=0;const rect=(nav&&navFull?barElement.current:trigger.current)?.getBoundingClientRect();if(!rect)return;const next=musicIslandLayout(rect,{width:innerWidth,height:innerHeight},content.current?.scrollHeight||180,placement,nav&&navFull?rect.width:344);setIslandBox(old=>Object.keys(next).every(key=>old[key]===next[key])?old:next);};const schedule=()=>{if(!frame)frame=requestAnimationFrame(update);};update();const observer=new ResizeObserver(schedule);if(trigger.current)observer.observe(trigger.current);if(barElement.current)observer.observe(barElement.current);if(content.current)observer.observe(content.current);const header=trigger.current?.closest('.site-header');if(header)observer.observe(header);addEventListener('scroll',schedule,true);addEventListener('resize',schedule);return()=>{cancelAnimationFrame(frame);observer.disconnect();removeEventListener('scroll',schedule,true);removeEventListener('resize',schedule);};},[placement,expanded,connections,queue,!!track,navFull]);
 useEffect(()=>{if(!expanded)return;const outside=e=>{if(!island.current?.contains(e.target)&&!trigger.current?.contains(e.target))collapse();};document.addEventListener('pointerdown',outside);return()=>document.removeEventListener('pointerdown',outside);},[expanded]);
 useEffect(()=>{if(scope.current!==userId){scope.current=userId;closeMusic();disconnectMusic();setExpanded(false);}},[userId]);
 useEffect(()=>{if(!track){setPlaying(false);return;}const abort=new AbortController();let objectURL;setResults([]);setSelected('');setSource('');setError('');setPlaying(false);setTime(0);setDuration(0);setSaved(tracks(userId).some(t=>t.id===track.id));setBusy(true);setMetadata(null);setFailedCover('');setAudioRetry(0);setExpanded(false);
  (async()=>{
   if(native){let url=track.url;if(track.source==='library'){const item=track.item||methods.current.resolveItem?.(track.id);if(!item)throw Error('Открой коллекцию, в которой сохранена эта песня.');url=await methods.current.prepareStream?.(item);}if(track.source==='file'&&track.file){objectURL=URL.createObjectURL(track.file);url=objectURL;}if(!url)throw Error('Не удалось открыть аудиофайл.');if(!abort.signal.aborted)setSource(url);return;}
   if(!service?.request)throw Error('Подключи сервер Oracle в профиле для воспроизведения музыки.');
   if(remote){setSelected(track.url);return;}
   if(track.youtubeId){setSelected(track.youtubeId);return;}
   const server=window.MEDIA_VAULT_CONFIG?.importServerUrl;if(!server)throw Error('Сервер поиска музыки не подключён.');
   const response=await fetch(server+'/music/search?'+new URLSearchParams({title:identity.title,artist:identity.artist}),{signal:AbortSignal.any([abort.signal,AbortSignal.timeout(25000)])}),data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Поиск записи временно недоступен.');if(abort.signal.aborted)return;setResults(data.results||[]);if(data.results?.[0]?.match)setSelected(data.results[0].id);else if(!data.results?.length)throw Error('Запись не найдена. Попробуй другое название.');
  })().catch(e=>{if(!abort.signal.aborted)setError(e.message);}).finally(()=>{if(!abort.signal.aborted)setBusy(false);});return()=>{abort.abort();if(objectURL)URL.revokeObjectURL(objectURL);};
 },[state?.request,userId]);
 useEffect(()=>{if(!track||native)return;const server=window.MEDIA_VAULT_CONFIG?.importServerUrl;if(!server)return;const abort=new AbortController();fetch(server+'/music/metadata?'+new URLSearchParams({title:identity.title,artist:identity.artist}),{signal:AbortSignal.any([abort.signal,AbortSignal.timeout(12000)])}).then(async r=>r.ok?r.json():null).then(d=>{if(!abort.signal.aborted&&d?.found)setMetadata(old=>({...d,youtubeTitle:old?.youtubeTitle}));}).catch(()=>{});return()=>abort.abort();},[state?.request]);
 useEffect(()=>{if(!serverAudio||!selected)return;const abort=new AbortController();let lease;setSource('');setTime(0);setDuration(0);setBusy(true);setError('');
  (remote?openMusicAudio(service,selected,{signal:AbortSignal.any([abort.signal,AbortSignal.timeout(25000)]),remote:true}):openYouTubeAudio(service,selected,{signal:AbortSignal.any([abort.signal,AbortSignal.timeout(75000)]),refresh:audioRetry>0})).then(data=>{lease=data;if(abort.signal.aborted){data.close();return;}setSource(data.streamUrl);setDuration(data.duration||0);setMetadata(old=>({...old,youtubeTitle:data.title||track.title}));}).catch(e=>{if(!abort.signal.aborted){setSource('');setTime(0);setDuration(0);setPlaying(false);setError(e.message);}}).finally(()=>{if(!abort.signal.aborted)setBusy(false);});
  return()=>{abort.abort();lease?.close();};
 },[serverAudio,selected,state?.request,audioRetry,service?.server]);
 // React has already committed the next src when the previous effect cleans up.
 // Clearing that attribute here can erase the new song before metadata loads.
 useEffect(()=>{const node=audio.current;if(!audioBacked||!node||!source)return;node.volume=volume;node.play().catch(()=>setPlaying(false));return()=>node.pause();},[source,audioBacked,state?.request]);
 useEffect(()=>{if(audio.current)audio.current.volume=volume;},[volume]);
 function pause(){audio.current?.pause();setPlaying(false);}
 function collapse(restore=false){setExpanded(false);setConnections(false);setQueue(false);if(restore===true)requestAnimationFrame(()=>[...(trigger.current?.querySelectorAll('button')||[])].find(button=>button.getClientRects().length&&!button.disabled)?.focus({preventScroll:true}));}
 function toggleBarMode(){if(navFull)collapse();setNavFull(v=>!v);}
 function toggle(){if(!source){if(serverAudio&&selected&&!busy)setAudioRetry(v=>v+1);return;}const node=audio.current;if(!node)return;if(node.paused)node.play().catch(()=>setError('Нажми Play ещё раз, чтобы разрешить звук.'));else node.pause();}
 function seek(value){const n=Number(value);setTime(n);if(audio.current)audio.current.currentTime=n;}
 const clampVolume=value=>Math.max(0,Math.min(1,Math.round(value*100)/100));
 useEffect(()=>{const node=volumeKnob.current;if(!node||!track)return;const wheel=event=>{event.preventDefault();setVolume(value=>clampVolume(value+(event.deltaY<0?.05:-.05)));};node.addEventListener('wheel',wheel,{passive:false});return()=>node.removeEventListener('wheel',wheel);},[!!track,nav]);
 const handleVolumeKey=event=>{let value;if(event.key==='ArrowRight'||event.key==='ArrowUp'||event.key==='+')value=volume+.05;else if(event.key==='ArrowLeft'||event.key==='ArrowDown'||event.key==='-')value=volume-.05;else if(event.key==='Home')value=0;else if(event.key==='End')value=1;else return;event.preventDefault();setVolume(clampVolume(value));};
 const startVolumeDrag=event=>{if(event.button!==0)return;volumeMoved.current=false;volumeDrag.current={id:event.pointerId,x:event.clientX,value:volume};event.currentTarget.setPointerCapture(event.pointerId);};
 const moveVolumeDrag=event=>{const drag=volumeDrag.current;if(!drag||drag.id!==event.pointerId)return;const dx=event.clientX-drag.x;if(Math.abs(dx)>4)volumeMoved.current=true;setVolume(clampVolume(drag.value+dx/120));};
 const stopVolumeDrag=event=>{if(volumeDrag.current?.id!==event.pointerId)return;volumeDrag.current=null;if(event.currentTarget.hasPointerCapture(event.pointerId))event.currentTarget.releasePointerCapture(event.pointerId);};
 const toggleMute=()=>{if(volumeMoved.current){volumeMoved.current=false;return;}if(volume){previousVolume.current=volume;setVolume(0);}else setVolume(previousVolume.current||.8);};
 useEffect(()=>{if(!expanded)return;const key=e=>{if(e.key==='Escape'&&!e.defaultPrevented){e.preventDefault();collapse(true);}};addEventListener('keydown',key);return()=>removeEventListener('keydown',key);},[expanded,youtube]);
 useEffect(()=>{if(!track||!navigator.mediaSession||!audioBacked)return;try{navigator.mediaSession.metadata=new MediaMetadata({title:track.title,artist:track.artists?.join(', ')||'MediaVault',album:track.animeTitle||'Личная коллекция',artwork:imageURL(track.cover)?[{src:imageURL(track.cover)}]:[]});for(const [name,fn] of Object.entries({play:()=>audio.current?.play().catch(()=>{}),pause,previoustrack:()=>stepMusic(-1),nexttrack:()=>stepMusic(1)}))navigator.mediaSession.setActionHandler(name,fn);}catch{}return()=>{try{navigator.mediaSession.metadata=null;for(const name of ['play','pause','previoustrack','nexttrack'])navigator.mediaSession.setActionHandler(name,null);}catch{}};},[track?.id,audioBacked]);
 useEffect(()=>{const stop=e=>{if(e.target?.tagName==='VIDEO'&&!e.target.closest('.music-dock'))pause();};document.addEventListener('play',stop,true);return()=>document.removeEventListener('play',stop,true);},[]);
 const displayTitle=identity.title||metadata?.title||track?.title;
 const cover=imageURL(track?.cover||metadata?.cover||(youtube&&/^[\w-]{11}$/.test(selected)?'https://i.ytimg.com/vi/'+selected+'/hqdefault.jpg':'')),art=cover&&cover!==failedCover?<img src={cover} alt="" loading="lazy" referrerPolicy="no-referrer" onError={()=>setFailedCover(cover)}/>:<Music2 size={18}/>;
 const favorite=()=>{toggleTrack(userId,{...track,title:displayTitle,item:undefined,file:undefined,url:track.source==='url'?track.url:undefined,cover:cover||undefined});setSaved(v=>!v);};
 const playingEvent=()=>{setPlaying(true);dispatchEvent(new Event('mediavault-music-playing'));};
 const canPlay=!!track&&!busy&&(!!source||serverAudio&&!!selected);
 const timeline=(detail=false)=><div className="music-dock-timeline"><span>{clock(time)}</span><input type="range" min="0" max={duration||1} step="0.1" value={Math.min(time,duration||1)} disabled={!duration} style={{'--music-progress':(duration>0?Math.min(100,time/duration*100):0)+'%'}} aria-label={detail?'Позиция музыки в подробностях':'Позиция музыки'} onChange={e=>seek(e.target.value)}/><span>{clock(duration)}</span></div>;
 const controls=(detail=false)=><div className="music-dock-controls"><button aria-label="Предыдущая песня" disabled={!state?.index} onClick={()=>stepMusic(-1)}><SkipBack size={16}/></button><button className="music-play" aria-label={detail?(playing?'Пауза в подробностях':'Продолжить в подробностях'):(playing?'Пауза музыки':'Продолжить музыку')} onClick={toggle} disabled={!canPlay}>{playing?<Pause size={18}/>:<Play size={18}/>}</button><button aria-label="Следующая песня" disabled={!state||state.index>=state.queue.length-1} onClick={()=>stepMusic(1)}><SkipForward size={16}/></button></div>;
 const bar=track?<div ref={barElement} className={'music-bar'+(playing?' is-playing':'')+(barHovered?' is-hovered':'')+(barKeyboard?' is-keyboard-open':'')+(nav&&navFull?' is-nav-expanded':'')+(scrubPreview?' is-scrubbing':'')} onClick={event=>{if(nav&&!event.target.closest('button,input,a,[role=slider]'))toggleBarMode();}} onPointerLeave={event=>{if(event.pointerType==='mouse'){setBarHovered(false);setBarKeyboard(false);const focused=document.activeElement;if(focused&&event.currentTarget.contains(focused))focused.blur();}}} onFocusCapture={event=>{if(keyboardNavigation.current&&event.target.matches(':focus-visible'))setBarKeyboard(true);}} onBlurCapture={event=>{if(!event.currentTarget.contains(event.relatedTarget))setBarKeyboard(false);}}>
 <div className="music-bar-primary">
  <button className="music-disc" aria-label="Открыть музыкальный плеер" aria-expanded={nav&&track?navFull:expanded} onClick={()=>nav&&track?toggleBarMode():expanded?collapse():setExpanded(true)}>{art}</button>
  <div className="music-bar-middle">
   <button className="music-dock-title" onClick={()=>nav&&track?toggleBarMode():expanded?collapse():setExpanded(true)} aria-label={'О песне '+track.title}><strong>{displayTitle}</strong><small title={error||undefined}>{identity.artist||metadata?.artists?.join(', ')||(busy?'Подготавливаем аудио…':native?'Личная коллекция':'Аудио через Oracle')}</small></button>
   <div className="music-bar-transport">{timeline()}</div>
  </div>
  <div className="music-bar-actions">
   {controls()}
   <div className="music-bar-volume">
    <button ref={volumeKnob} className="music-volume-knob" role="slider" aria-label="Громкость музыки в шапке" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(volume*100)} aria-valuetext={Math.round(volume*100)+'%'} title="Громкость: колесо мыши или движение влево-вправо" onKeyDown={handleVolumeKey} onPointerDown={startVolumeDrag} onPointerMove={moveVolumeDrag} onPointerUp={stopVolumeDrag} onPointerCancel={stopVolumeDrag} onClick={toggleMute}>
     <svg viewBox="0 0 36 36" className="music-volume-ring" aria-hidden="true"><circle cx="18" cy="18" r="14" className="music-volume-ring-track"/><circle cx="18" cy="18" r="14" className="music-volume-ring-fill" pathLength="100" strokeDasharray={Math.round(volume*100)+' 100'} transform="rotate(-90 18 18)"/></svg><Volume2 size={14}/>
    </button>
   </div>
  </div>
 </div>
 <div className="music-bar-full" aria-hidden={!navFull}>
  <div className="music-progress-fill" aria-hidden="true" style={{transform:`scaleX(${duration?Math.max(0,Math.min(1,(scrubPreview?.time??time)/duration)):0})`}}/>
  <button ref={circle} className="music-full-play" aria-label={playing?'Пауза музыки':'Продолжить музыку'} disabled={!canPlay} onPointerDown={onCircleDown} onPointerMove={onCircleMove} onPointerUp={onCircleUp} onPointerCancel={onCircleUp} onClick={()=>{if(circleSkipClick.current){circleSkipClick.current=false;return;}toggle();}} title={'Громкость '+Math.round(volume*100)+'% · колесо или вертикальный жест'} style={{'--volume-percent':Math.round(volume*100)+'%'}}>
   <span className="music-full-art" aria-hidden="true">{art}</span><span className="music-full-ring" aria-hidden="true"/>{playing?<Pause size={24}/>:<Play size={24}/>}
  </button>
  <div className="music-full-copy"><span className="music-full-title">{displayTitle}</span><strong className="music-full-lyric" aria-live="off">{error?'Проблема с аудио · повтори Play':activeLyric}</strong></div>
  <button className="music-full-lyrics" aria-label={expanded?'Свернуть музыкальный плеер':'Развернуть музыкальный плеер'} title={expanded?'Свернуть музыкальный плеер':'Развернуть музыкальный плеер'} aria-expanded={expanded} onClick={()=>{if(expanded)collapse();else{setExpanded(true);setConnections(false);setQueue(false);setLyricsOpen(true);}}}><motion.span key={String(expanded)} initial={reduce?false:{opacity:0,scale:.65,rotate:-35}} animate={{opacity:1,scale:1,rotate:0}} transition={GLASS_ENTER}>{expanded?<Minimize2 size={16}/>:<Maximize2 size={16}/>}</motion.span></button>
  <button className="music-full-next" aria-label="Следующая песня" disabled={!state||state.index>=state.queue.length-1} onClick={()=>stepMusic(1)}><SkipForward size={21}/></button>
  <AnimatePresence initial={false}>
   {scrubPreview&&<motion.div key="seek" className="music-seek-surface" role="status" aria-label={'Перемотка '+clock(scrubPreview.time)} initial={{opacity:0,scaleY:.75}} animate={{opacity:1,scaleY:1}} exit={{opacity:0,scaleY:.78}} transition={{type:'spring',stiffness:420,damping:30,mass:.65}}>
    <motion.div className="music-seek-fill" style={{width:scrubPosition}}/>
    <motion.span className="music-seek-marker" style={{left:scrubPosition}}/>
    <motion.span className="music-seek-triangle" initial={{x:-18,scale:.85,opacity:1}} animate={{x:0,scale:.45,opacity:0}} transition={{type:'spring',stiffness:390,damping:28,mass:.55}}><Play size={19}/></motion.span>
    <motion.span className="music-seek-clock" initial={{opacity:0,scale:.64,filter:'blur(4px)'}} animate={{opacity:1,scale:1,filter:'blur(0px)'}} exit={{opacity:0,scale:.78,filter:'blur(4px)'}} transition={{type:'spring',stiffness:450,damping:30,delay:.1}}><span className="music-seek-time">{clock(scrubPreview.time)}</span></motion.span>
   </motion.div>}
  </AnimatePresence>
 </div>
</div>:null;
 const panel=<motion.aside ref={island} className={'music-dock music-panel music-island'+(expanded?' is-expanded':'')+(playing?' is-playing':'')+(native?' is-native':' is-youtube')+(nav?' is-nav-panel':'')} initial={false} animate={expanded?GLASS_VISIBLE:GLASS_HIDDEN} transition={reduce?{duration:0}:GLASS_ENTER} style={{left:islandBox.left,top:islandBox.top,width:islandBox.width,height:islandBox.height, '--island-content-width':islandBox.width+'px','--island-content-height':islandBox.maxHeight+'px'}} inert={!expanded} aria-hidden={!expanded} role="dialog" aria-modal="false" aria-label="Музыкальный мини-плеер" onPointerDown={e=>{gesture.current={y:e.clientY,id:e.pointerId};}} onPointerUp={e=>{if(gesture.current?.id===e.pointerId&&e.clientY-gesture.current.y>70&&!e.target.closest('input,select,button,.music-dock-queue,.music-connections'))collapse();gesture.current=null;}}>
  <div ref={content} className="music-island-content">
  <div className="music-panel-heading"><span>{connections?<button aria-label="Вернуться к музыке" onClick={()=>setConnections(false)}><ArrowLeft size={16}/></button>:<Headphones size={15}/ >}{connections?'Подключения':queue?'Очередь':'Музыка'}</span><div><button aria-label="Музыкальные аккаунты и плейлисты" aria-expanded={connections} onClick={()=>setConnections(v=>!v)}><Settings2 size={16}/></button><button aria-label="Свернуть музыкальный плеер" onClick={collapse}><ChevronDown size={17}/></button>{track&&<button aria-label="Закрыть музыкальный плеер" onClick={()=>{pause();closeMusic();collapse();}}><X size={16}/></button>}</div></div>
  {connections?<MusicConnections track={track} compact/>:track?<>
   <div className="music-panel-track"><div className="music-disc">{art}</div><div><strong>{displayTitle}</strong><small>{identity.artist||metadata?.artists?.join(', ')||'Исполнитель не указан'}</small></div><button className="music-dock-save" aria-label="Музыку в избранное" disabled={track.source==='file'} aria-pressed={saved} onClick={favorite}><Heart size={17} fill={saved?'currentColor':'none'}/></button></div>
   {timeline(true)}
   <div className="music-island-playback">{controls(true)}<button aria-label="Очередь музыки" aria-expanded={queue} onClick={()=>setQueue(v=>!v)}><ListMusic size={17}/></button><label className="music-volume"><Volume2 size={15}/><input type="range" min="0" max="1" step="0.05" value={volume} style={{'--music-progress':(volume*100)+'%'}} onChange={e=>setVolume(Number(e.target.value))} aria-label="Громкость музыки"/></label></div>
   {busy&&<p className="music-provider-note" role="status">Подготавливаем аудио…</p>}
   {youtube&&<div className="music-dock-recording">{results.length>0&&<details open={!selected||undefined}><summary>Выбрать запись</summary><label>Запись<select aria-label="Запись YouTube" value={selected} onChange={e=>{setSelected(e.target.value);setError('');}}><option value="">Выбрать запись</option>{results.map(r=><option value={r.id} key={r.id}>{r.title} · {r.author}</option>)}</select></label></details>}{error&&<><p className="music-provider-note">Аудио через Oracle недоступно</p><button type="button" disabled={busy} onClick={()=>setAudioRetry(v=>v+1)}>Повторить подготовку аудио</button></>}</div>}
   {queue&&<div className="music-dock-queue"><strong>Далее в очереди</strong>{state.queue.map((t,i)=><button key={t.id} aria-current={i===state.index} onClick={()=>playMusic(t,state.queue)}><span>{i+1}</span>{t.title}{i===state.index&&<span className="music-equalizer" aria-hidden="true"><i/><i/><i/></span>}</button>)}</div>}
   <details className="music-lyrics-settings" open={lyricsOpen} onToggle={e=>setLyricsOpen(e.currentTarget.open)}><summary>Текст песни <small>{lyricData.precision==='word'?'По словам':lyricData.lines?.length?'По строкам':lyricData.plainText?'Без синхронизации':'Не найден'}</small></summary><div><label><input type="checkbox" checked={lyricsEnabled} onChange={e=>{setLyricsEnabled(e.target.checked);try{localStorage.setItem('mediavault_lyrics_enabled',String(e.target.checked));}catch{}}}/>Синхронизировать текст</label><div className="music-panel-lyrics">{lyricData.plainText?<p className="music-plain-lyrics">{lyricData.plainText}</p>:activeLyric}</div><label>Сдвиг текста · {lyricOffset>0?'+':''}{lyricOffset.toFixed(1)} с<input aria-label="Сдвиг текста песни" type="range" min="-15" max="15" step=".1" value={lyricOffset} onChange={e=>shiftLyrics(Number(e.target.value))}/></label><div className="music-lyric-actions"><button onClick={()=>lyricFile.current?.click()}>Загрузить LRC / TTML</button><button onClick={()=>{setManualLyrics(null);automaticLyrics.retry();}}>Повторить поиск</button></div><input hidden ref={lyricFile} type="file" accept=".lrc,.ttml,.xml" onChange={importLyrics}/>{lyricData.source&&<small>{lyricData.url?<a href={lyricData.url} target="_blank" rel="noopener noreferrer">{lyricData.source}</a>:lyricData.source}{lyricData.timingMismatch?' · длительность видео отличается; показан текст без синхронизации':lyricData.precision==='line'?' · источник содержит только времена строк':''}</small>}{lyricError&&<small role="status">{lyricError}</small>}</div></details>
   {metadata?.found&&<details className="music-song-details"><summary>О записи</summary><span>{metadata.album}</span>{metadata.date&&<small>{metadata.date}</small>}<a href={metadata.url} target="_blank" rel="noopener noreferrer">MusicBrainz <ExternalLink size={11}/></a></details>}
  </>:<div className="music-empty"><div className="music-empty-heading"><span className="music-disc"><Music2 size={20}/></span><div><strong>Выбери музыку</strong><p>Опенинги, эндинги и твои записи</p></div></div>{tracks(userId).length>0?<div className="music-recent">{tracks(userId).slice(0,4).map(t=><button key={t.id} onClick={()=>playMusic(t,tracks(userId))}><span><strong>{t.title}</strong><small>{t.artists?.join(', ')}</small></span><Play size={14}/></button>)}</div>:<p className="music-empty-note">Запусти песню из коллекции или со страницы аниме.</p>}</div>}
  {error&&!connections&&<p className="music-dock-error" role="status">{error}</p>}
  </div>
 </motion.aside>;
 if(!track&&!nav)return null;
 return <>{audioBacked&&<audio className="music-audio" key={state.request} ref={audio} src={source||undefined} preload="metadata" onLoadedMetadata={e=>setDuration(Number.isFinite(e.currentTarget.duration)?e.currentTarget.duration:0)} onTimeUpdate={e=>setTime(e.currentTarget.currentTime)} onPlay={playingEvent} onPause={()=>setPlaying(false)} onEnded={()=>{setPlaying(false);stepMusic(1);}} onError={()=>{if(source){if(serverAudio)setSource('');setPlaying(false);setError('Аудиопоток недоступен или формат не поддерживается браузером.');}}}/>}{<div ref={trigger} className={'music-nav'+(!nav?' music-dock-compact':'')+(track?' has-track':'')}><button className="music-nav-toggle" aria-label="Музыкальный плеер" title={error||undefined} aria-expanded={expanded} onClick={()=>expanded?collapse():setExpanded(true)}>{track?art:<Headphones size={19}/ >}{playing&&<i/>}</button>{bar}</div>}{createPortal(panel,document.body)}</>;
}
