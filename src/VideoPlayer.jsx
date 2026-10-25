import {useEffect,useMemo,useRef,useState} from 'react';
import {Music2,Pause,Play,Settings2,SkipForward,Subtitles,PictureInPicture2,Maximize2,Minimize2,ChevronLeft,ChevronRight,Sparkles,X,Sun,Share2,Camera,Video,ChevronsUp,ChevronsDown} from 'lucide-react';
import './player.css';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {readProgress,writeProgress} from './playback-progress.js';
import usePlayerGestures from './use-player-gestures.js';
import usePlayerActions from './use-player-actions.js';
import usePlayerAtmosphere from './use-player-atmosphere.js';
import {buildPlaybackLibrary,openingBounds,toWebVtt} from './player-model.js';
import {startNeuralUpscaler} from './neural-upscaler.js';
import Soundtrack from './Soundtrack.jsx';
import PlayerSettings,{SettingsGlyph} from './PlayerSettings.jsx';
import {diagnoseVideoFailure} from './playback-diagnostics.js';
import {startMobileGpu} from './mobile-gpu-upscaler.js';

const PREF_KEY='mediavault_player_preferences_v1';
const DEFAULTS={speed:1,volume:1,autoNext:false,autoSkip:false,gpu:false,upscaler:'auto',deviceProfile:'auto',neuralMode:'balanced',subSize:24,subOffset:8};
function getPrefs(){
  try{return {...DEFAULTS,...JSON.parse(localStorage.getItem(PREF_KEY)||'{}')};}catch{return DEFAULTS;}
}
function clock(seconds){
  if(!Number.isFinite(seconds)||seconds<0)return '00:00';
  const n=Math.floor(seconds),h=Math.floor(n/3600),m=Math.floor(n%3600/60),s=n%60;
  return (h?h+':'+String(m).padStart(2,'0'):String(m).padStart(2,'0'))+':'+String(s).padStart(2,'0');
}
function keyFor(userId,libraryId,id){return [userId,libraryId,id];}
function readResume(key){return readProgress(...key)?.time||0;}
function openerKey(libraryId,id){return 'mediavault_opening_'+String(libraryId||'local')+'_'+id;}
function getOpening(item,libraryId){
  try{
    const saved=localStorage.getItem(openerKey(libraryId,item.id));
    if(saved!==null)return openingBounds(JSON.parse(saved));
  }catch{}
  return openingBounds(item.opening||item.intro);
}
const tracksOf=video=>Array.from(video?.textTracks||[]).map((track,index)=>({
  id:track.label==='Загруженные субтитры'?'local':'native:'+index,
  name:track.label||(track.language?track.language:'Дорожка '+(index+1))
}));
function VolumeGlyph({value,muted}){
  const level=muted?0:value;
  return <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" data-volume-level={level}>
    <path d="M10 5 5 9H2v6h3l5 4z"/>
    <path className="volume-wave" style={{opacity:level>.01?1:0}} d="M13 10a3 3 0 0 1 0 4"/>
    <path className="volume-wave" style={{opacity:level>.35?1:0}} d="M16 7a7 7 0 0 1 0 10"/>
    <path className="volume-wave" style={{opacity:level>.7?1:0}} d="M19 4a11 11 0 0 1 0 16"/>
    <path className="volume-wave" style={{opacity:level===0?1:0}} d="m14 10 6 6m0-6-6 6"/>
  </svg>;
}
export default function VideoPlayer({item,source,catalog,libraryId,userId,mediaRef,onSelectItem,onError,busy,renderEpisodeArtwork,onPlaybackChange}){
  const ownRef=useRef(null),canvasRef=useRef(null),stageRef=useRef(null),railRef=useRef(null);
  const videoRef=mediaRef||ownRef;
  const reducedMotion=useReducedMotion();
  const [prefs,setPrefs]=useState(getPrefs);
  const [time,setTime]=useState(0),[duration,setDuration]=useState(0),[buffered,setBuffered]=useState(0);
  const [playing,setPlaying]=useState(false),[muted,setMuted]=useState(false);
  const [isFullscreen,setIsFullscreen]=useState(false),[isPip,setIsPip]=useState(false);
  useEffect(()=>{const v=videoRef.current;const enter=()=>setIsPip(true),leave=()=>setIsPip(false);v?.addEventListener('enterpictureinpicture',enter);v?.addEventListener('leavepictureinpicture',leave);return()=>{v?.removeEventListener('enterpictureinpicture',enter);v?.removeEventListener('leavepictureinpicture',leave);};},[]);
  useEffect(()=>{const update=()=>setIsFullscreen(document.fullscreenElement===stageRef.current);document.addEventListener('fullscreenchange',update);return()=>document.removeEventListener('fullscreenchange',update);},[]);
  const [panel,setPanel]=useState('watch'),[localTrack,setLocalTrack]=useState('');
  const [controlsVisible,setControlsVisible]=useState(true);
  const hideTimer=useRef(null);
  const [musicOpen,setMusicOpen]=useState(false);
  const musicIdentity=item.metadataId||catalog?.storage?.collections?.find?.(v=>v.id===item.collectionId)?.metadata?.ids?.mal;
  const settingsOpen=panel==='settings';
  const scene=usePlayerAtmosphere(videoRef,source,playing,stageRef);
  const [subtitle,setSubtitle]=useState('off'),[availableTracks,setAvailableTracks]=useState([]);
  const [audioTracks,setAudioTracks]=useState([]),[activeAudio,setActiveAudio]=useState(0);
  const [subtitleText,setSubtitleText]=useState(''),[gpuActive,setGpuActive]=useState(false);
  const [gpuWarning,setGpuWarning]=useState('');
  const [neuralStats,setNeuralStats]=useState(null);
  const [gpuAttempt,setGpuAttempt]=useState(0);
  const mobileDevice=/Android|iPhone|iPad/i.test(navigator.userAgent)||matchMedia('(any-pointer: coarse)').matches;
  const deviceProfile=prefs.deviceProfile==='auto'?(mobileDevice?'phone':'desktop'):prefs.deviceProfile;
  const engine=prefs.upscaler==='auto'?(deviceProfile==='desktop'?'anime4k':'mobile'):prefs.upscaler;
  const engineName=engine==='mobile'?'Мобильный GPU':engine==='fsrcnn'?'FSRCNN':'Anime4K';
  function retryGpu(value=prefs.upscaler){setGpuAttempt(n=>n+1);changePrefs({gpu:value!=='off',...(value!=='off'?{upscaler:value}:{})});}
  const [opening,setOpening]=useState(()=>getOpening(item,libraryId));
  const [openingDraft,setOpeningDraft]=useState(null);
  const lastStored=useRef(-1),resumeApplied=useRef(false),subtitleInput=useRef(null);
  const library=useMemo(()=>buildPlaybackLibrary(item,catalog),[item.id,catalog]);
  const seasons=library.seasons;
  const episodes=seasons.flatMap(season=>season.episodes);
  const season=seasons.find(part=>part.episodes.some(ep=>ep.variants.some(v=>v.item.id===item.id)));
  const episode=season?.episodes.find(ep=>ep.variants.some(v=>v.item.id===item.id));
  const index=episodes.indexOf(episode);
  const next=episodes[index+1]?.variants[0]?.item;
  function revealControls(){
    setControlsVisible(true);clearTimeout(hideTimer.current);
    hideTimer.current=setTimeout(()=>setControlsVisible(false),3000);
  }
  useEffect(()=>()=>{clearTimeout(hideTimer.current);onPlaybackChange?.(false);},[]);
  useEffect(()=>{revealControls();},[playing,panel]);
  useEffect(()=>{
    const rail=railRef.current,card=rail?.querySelector('[aria-current="true"]');
    if(rail&&card)rail.scrollTo({left:rail.scrollLeft+card.getBoundingClientRect().left-rail.getBoundingClientRect().left-(rail.clientWidth-card.clientWidth)/2,behavior:'instant'});
  },[item.id]);
  function scrollEpisodes(offset){railRef.current?.scrollBy({left:offset,behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});}
  function openPanel(value){setPanel(value);revealControls();}
  const changePrefs=(change)=>{
    setPrefs(prev=>{
      const updated={...prev,...change};
      try{localStorage.setItem(PREF_KEY,JSON.stringify(updated));}catch{}
      return updated;
    });
  };
  useEffect(()=>{
    const media=videoRef.current;if(!media)return;
    media.playbackRate=Number(prefs.speed)||1;
    media.volume=Math.max(0,Math.min(1,Number(prefs.volume)));
  },[prefs.speed,prefs.volume]);
  useEffect(()=>{resumeApplied.current=false;},[source]);
  useEffect(()=>{setOpening(getOpening(item,libraryId));setOpeningDraft(null);resumeApplied.current=false;lastStored.current=-1;},[item.id,libraryId]);
  useEffect(()=>()=>{if(localTrack)URL.revokeObjectURL(localTrack);},[localTrack]);
  useEffect(()=>{
    const media=videoRef.current;if(!media||!source)return;
    const refresh=()=>{
      setAvailableTracks(tracksOf(media));
      const audio=Array.from(media.audioTracks||[]).map((track,index)=>({
        index,name:track.label||track.language||'Аудио '+(index+1)
      }));
      setAudioTracks(audio);
      setActiveAudio(Math.max(0,Array.from(media.audioTracks||[]).findIndex(track=>track.enabled)));
    };
    refresh();
    media.textTracks?.addEventListener?.('addtrack',refresh);
    media.textTracks?.addEventListener?.('removetrack',refresh);
    media.audioTracks?.addEventListener?.('addtrack',refresh);
    const id=setTimeout(refresh,350);
    return()=>{
      clearTimeout(id);
      media.textTracks?.removeEventListener?.('addtrack',refresh);
      media.textTracks?.removeEventListener?.('removetrack',refresh);
      media.audioTracks?.removeEventListener?.('addtrack',refresh);
    };
  },[source]);
  useEffect(()=>{
    const media=videoRef.current;if(!media)return;
    const tracks=Array.from(media.textTracks||[]);
    const refresh=()=>setSubtitleText(tracks.filter(track=>track.mode==='hidden')
      .flatMap(track=>Array.from(track.activeCues||[]).map(cue=>cue.text)).join('\n'));
    tracks.forEach((track,index)=>{
      track.mode=(subtitle===(track.label==='Загруженные субтитры'?'local':'native:'+index))?'hidden':'disabled';
      track.addEventListener?.('cuechange',refresh);
    });
    refresh();
    return()=>tracks.forEach(track=>track.removeEventListener?.('cuechange',refresh));
  },[subtitle,availableTracks,localTrack,source]);
  useEffect(()=>{
    if(!source||!prefs.gpu||!canvasRef.current||!videoRef.current){
      setGpuActive(false);setNeuralStats(null);
      return;
    }
    let disposed=false,stop,failed=false;
    const canvas=canvasRef.current;
    canvas.style.opacity='0';
    setGpuWarning('');setNeuralStats(null);setGpuActive(false);
    (async()=>{
      try{
        const start=engine==='mobile'?startMobileGpu:engine==='fsrcnn'?startNeuralUpscaler:(await import('./anime4k-runtime.js')).startAnime4K;
        stop=await start(videoRef.current,canvas,{
          mode:prefs.neuralMode,deviceProfile,
          onStats:stats=>{if(!disposed)setNeuralStats(stats);},
          onFailure:error=>{
            if(disposed)return;
            failed=true;
            setGpuWarning(error.message||'Ошибка нейросетевого инференса.');
            setGpuActive(false);
            changePrefs({gpu:false});
          }
        });
        if(disposed)stop();
        else if(!failed)setGpuActive(true);
      }catch(error){
        if(disposed)return;
        setGpuActive(false);
        setGpuWarning(error.message||'Улучшение недоступно. Продолжаем исходное видео.');
        changePrefs({gpu:false});
      }
    })();
    return()=>{disposed=true;stop?.();canvas.style.opacity='0';};
  },[source,prefs.gpu,prefs.neuralMode,engine,deviceProfile,gpuAttempt]);
  const seek=seconds=>{
    const media=videoRef.current;
    if(media&&Number.isFinite(media.duration))media.currentTime=Math.max(0,Math.min(seconds,media.duration));
  };
  function onTime(){
    const video=videoRef.current;if(!video)return;
    setTime(video.currentTime);
    const ranges=video.buffered;
    if(ranges.length)setBuffered(ranges.end(ranges.length-1));
    if(prefs.autoSkip&&opening&&video.currentTime>=opening.start&&video.currentTime<opening.end-0.2)
      seek(opening.end);
    if(Math.abs(video.currentTime-lastStored.current)>=5){
      lastStored.current=video.currentTime;
      writeProgress(userId,libraryId,item,video.currentTime,video.duration);
    }
  }
  function loaded(){
    const video=videoRef.current;if(!video)return;
    setDuration(Number.isFinite(video.duration)?video.duration:0);
    video.playbackRate=Number(prefs.speed)||1;video.volume=Math.max(0,Math.min(1,Number(prefs.volume)));
    if(!source||!Number.isFinite(video.duration)||video.duration<=0)return;
    if(!resumeApplied.current){
      resumeApplied.current=true;
      const shared=sessionStorage.getItem('mediavault_pending_time_'+item.id);
      if(shared!==null){sessionStorage.removeItem('mediavault_pending_time_'+item.id);const point=Number(shared);if(Number.isFinite(point))seek(point);}
      else{const point=readResume(keyFor(userId,libraryId,item.id));if(point>0&&point<video.duration-12)seek(point);}
    }
  }
  function choose(nextItem,keepTime=false){
    if(!nextItem||nextItem.id===item.id)return;
    if(keepTime){try{sessionStorage.setItem('mediavault_pending_time_'+nextItem.id,String(videoRef.current?.currentTime||0));}catch{}}
    onSelectItem?.(nextItem);
  }
  function nextEpisode(){choose(next);}
  function ended(){
    setPlaying(false);writeProgress(userId,libraryId,item,0,videoRef.current?.duration);
    if(prefs.autoNext)nextEpisode();
  }
  function toggle(){const video=videoRef.current;if(!video)return;
    if(video.paused){openPanel('watch');video.play().catch(onError);}else video.pause();
  }
  function fullscreen(){
    const stage=stageRef.current,video=videoRef.current;
    if(document.fullscreenElement){document.exitFullscreen?.().catch(()=>{});return;}
    if(stage?.requestFullscreen)stage.requestFullscreen().catch(()=>video?.webkitEnterFullscreen?.());
    else video?.webkitEnterFullscreen?.();
  }
  function switchAudio(index){
    const list=videoRef.current?.audioTracks;if(!list)return;
    for(let i=0;i<list.length;i++)list[i].enabled=i===index;
    setActiveAudio(index);
  }
  async function attachSubtitle(event){
    const file=event.target.files?.[0];event.target.value='';
    if(!file)return;
    try{
      if(file.size>5*1024*1024)throw Error('Субтитры должны быть меньше 5 МБ.');
      const content=toWebVtt(await file.text(),file.name);
      setLocalTrack(URL.createObjectURL(new Blob([content],{type:'text/vtt'})));
      setSubtitle('local');setSubtitleText('');
    }catch(cause){onError?.(cause);}
  }
  function setIntro(value){
    setOpening(value);
    try{localStorage.setItem(openerKey(libraryId,item.id),JSON.stringify(value));}catch{}
  }
  function markEnd(){
    const end=videoRef.current?.currentTime||0;
    const nextBounds=openingBounds([openingDraft,end],Number.isFinite(duration)&&duration>0?duration:Infinity);
    if(nextBounds){setIntro(nextBounds);setOpeningDraft(null);}
    else onError?.(Error('Конец опенинга должен быть позже его начала.'));
  }
  useEffect(()=>{
    const handler=event=>{
      if(event.key==='Escape'&&panel!=='watch'){event.preventDefault();event.stopImmediatePropagation();openPanel('watch');stageRef.current?.querySelector('[aria-label="Настройки плеера"]')?.focus();return;}
      if(panel!=='watch')return;
      if(!stageRef.current?.contains(document.activeElement)&&document.fullscreenElement!==stageRef.current)return;
      if(document.activeElement?.tagName==='BUTTON'&&['Space','Enter'].includes(event.code))return;
      if(event.altKey||event.ctrlKey||event.metaKey||
        ['INPUT','SELECT','TEXTAREA'].includes(document.activeElement?.tagName)||
        document.activeElement?.isContentEditable)return;
      switch(event.code){
        case 'Space':case 'KeyK':event.preventDefault();toggle();break;
        case 'ArrowLeft':case 'KeyJ':event.preventDefault();seek((videoRef.current?.currentTime||0)-10);break;
        case 'ArrowRight':case 'KeyL':event.preventDefault();seek((videoRef.current?.currentTime||0)+10);break;
        case 'KeyM':setMuted(prev=>!prev);break;
        case 'KeyF':fullscreen();break;
        default:break;
      }
    };
    window.addEventListener('keydown',handler,true);
    return()=>window.removeEventListener('keydown',handler,true);
  });
  const gestures=usePlayerGestures({videoRef,volume:muted?0:prefs.volume,setVolume:value=>{setMuted(false);changePrefs({volume:value});},openPanel,toggle,reveal:revealControls});
  const actions=usePlayerActions({videoRef,canvasRef,item,gpuActive});
  const previewTime=gestures.feedback?.type==='seek'?gestures.feedback.value:time;
  const effectiveVolume=muted?0:Number(prefs.volume);
  const pip=async()=>{try{const v=videoRef.current;if(document.pictureInPictureElement)await document.exitPictureInPicture();else if(v?.requestPictureInPicture)await v.requestPictureInPicture();else if(v?.webkitSetPresentationMode)v.webkitSetPresentationMode(v.webkitPresentationMode==='picture-in-picture'?'inline':'picture-in-picture');}catch{}};
  const seekable=duration>0&&Number.isFinite(duration);
  const canSkip=opening&&time>=opening.start&&time<opening.end;
  const hiddenControls=playing&&panel==='watch'&&!controlsVisible;
  const progress=seekable?Math.min(100,previewTime/duration*100):0;
  return <div ref={stageRef} className={'mv-player'+(playing?' is-playing':'')+(panel!=='watch'?' is-browsing':'')+(hiddenControls?' controls-hidden':'')+(panel==='episodes'?' episodes-open':'')}
    style={{'--scene-rgb':scene.color,'--video-brightness':gestures.brightness}} aria-label="Видеоплеер MediaVault" role="region" tabIndex={0} onPointerDown={event=>{if(!event.target.closest('button,input,select,a,[role="dialog"]'))stageRef.current?.focus({preventScroll:true});}} onPointerMove={revealControls}
    onTouchStart={revealControls} onFocusCapture={revealControls}>
    <div className="mv-player-screen">
      <div className="mv-player-ambient" aria-hidden="true"/>
      <div className="mv-player-panorama" aria-hidden="true">{scene.image&&<img src={scene.image} alt=""/>}</div>
      <div className="mv-player-stage">
        <video ref={videoRef} src={source||undefined} crossOrigin="anonymous" playsInline preload="metadata" muted={muted}
          onLoadedMetadata={loaded} onTimeUpdate={onTime}
          onPlay={()=>{setPlaying(true);onPlaybackChange?.(true);}} onPause={()=>{setPlaying(false);onPlaybackChange?.(false);writeProgress(userId,libraryId,item,videoRef.current?.currentTime||0,videoRef.current?.duration);}}
          onDurationChange={loaded} onEnded={ended}
          onError={()=>{if(source)diagnoseVideoFailure({video:videoRef.current,source}).then(message=>onError?.(Error(message))).catch(()=>{});}}
          aria-label="Воспроизвести или приостановить видео">{localTrack&&<track key={localTrack} kind="subtitles" src={localTrack} srcLang="ru" label="Загруженные субтитры"/>}</video>
        <canvas key={engine+':'+deviceProfile+':'+prefs.neuralMode+':'+gpuAttempt} ref={canvasRef} className="mv-player-canvas" aria-hidden="true"/>
        {subtitleText&&<div className="mv-player-captions" style={{fontSize:prefs.subSize+'px',bottom:(hiddenControls?prefs.subOffset:Math.max(22,prefs.subOffset))+'%'}} aria-live="off">{subtitleText}</div>}
      </div>
      {panel==='watch'&&<div className="mv-player-touch-surface" {...gestures.surface} aria-hidden="true"/>}
      <AnimatePresence>{gestures.feedback&&gestures.feedback.type!=='seek'&&<motion.output className="mv-player-gesture-hud" style={{x:'-50%',y:'-50%'}} initial={{opacity:0,scale:.9}} animate={{opacity:1,scale:1}} exit={{opacity:0,scale:.95}} aria-live="off">
        {gestures.feedback.type==='seek'?<><strong>{clock(gestures.feedback.value)}</strong><small>{gestures.feedback.delta>=0?'+':'−'}{Math.abs(Math.round(gestures.feedback.delta))} сек.</small></>:gestures.feedback.type==='brightness'?<><Sun size={25}/><strong>{Math.round(gestures.feedback.value*100)}%</strong></>:gestures.feedback.type==='volume'?<><VolumeGlyph value={effectiveVolume}/><strong>{Math.round(effectiveVolume*100)}%</strong></>:<>{gestures.feedback.type==='episodes'?<ChevronsUp size={26}/>:<ChevronsDown size={26}/>}<small>{gestures.feedback.type==='episodes'?'Эпизоды':'Настройки'}</small></>}
      </motion.output>}</AnimatePresence>
      {actions.notice&&<output className="mv-player-action-notice" role="status">{actions.notice}</output>}
      {actions.recording&&<button className="mv-player-recording" onClick={actions.clip}><i/> {actions.clipSeconds} / 30 сек. · Остановить</button>}
      <div id="player-panel-watch" className="mv-player-watch" aria-hidden={playing||panel!=='watch'}>
        <div className="mv-player-overview">
          <h1>{library.title.replace(/\.(mp4|mkv|webm|mov|m4v|avi)$/i,'')}</h1>
          <p>{season?.name}<span> / </span>{episode?.label}</p>{episode?.description&&/[а-яё]/i.test(episode.description)&&<p className="mv-episode-description">{episode.description}</p>}
        {readResume(keyFor(userId,libraryId,item.id))>0&&<button className="mv-resume" onClick={()=>{seek(readResume(keyFor(userId,libraryId,item.id)));videoRef.current?.play().catch(onError);}}>Продолжить просмотр · {clock(readResume(keyFor(userId,libraryId,item.id)))}</button>}</div>
      </div>
      <AnimatePresence>
      {settingsOpen&&<PlayerSettings onClose={()=>openPanel('watch')}>{{
        watch:<div className="mv-player-settings">        <label>Качество<select aria-label="Качество" value={item.id} disabled={!episode?.variants.some(v=>v.item.id!==item.id&&v.label===episode.variants.find(x=>x.item.id===item.id)?.label)} onChange={e=>choose(episode.variants.find(v=>v.item.id===e.target.value)?.item,true)}>{episode?.variants.filter(v=>v.item.id===item.id||v.label===episode.variants.find(x=>x.item.id===item.id)?.label).map(v=><option key={v.item.id} value={v.item.id}>{v.item.quality||v.item.resolution||(v.item.id===item.id&&videoRef.current?.videoHeight?videoRef.current.videoHeight+'p':'Исходное')}</option>)}</select></label>
        {episode?.variants.length>1&&<label>Озвучка<select value={item.id} onChange={event=>choose(episode.variants.find(v=>v.item.id===event.target.value)?.item,true)}>{episode.variants.map(v=><option key={v.item.id} value={v.item.id}>{v.label}</option>)}</select></label>}
        <label>Скорость<select value={prefs.speed} onChange={event=>changePrefs({speed:Number(event.target.value)})}>
          {[0.5,0.75,1,1.25,1.5,1.75,2].map(v=><option key={v} value={v}>{v}×</option>)}</select></label>
        {audioTracks.length>1&&<label>Аудиодорожка<select value={activeAudio} onChange={event=>switchAudio(Number(event.target.value))}>
          {audioTracks.map(a=><option key={a.index} value={a.index}>{a.name}</option>)}</select></label>}
        <label className="mv-player-check"><input type="checkbox" checked={prefs.autoNext}
          onChange={event=>changePrefs({autoNext:event.target.checked})}/> Следующий эпизод автоматически</label>
        <label className="mv-player-check"><input type="checkbox" checked={prefs.autoSkip}
          onChange={event=>changePrefs({autoSkip:event.target.checked})}/> Автоматически пропускать опенинг</label>
        <div className="mv-player-intro"><span>Опенинг: {opening?clock(opening.start)+' – '+clock(opening.end):'не размечен'}</span>
          <div><button onClick={()=>setOpeningDraft(time)}>Начало {openingDraft!==null?'('+clock(openingDraft)+')':''}</button>
          <button disabled={openingDraft===null} onClick={markEnd}>Конец</button>
          <button disabled={!opening} onClick={()=>setIntro(null)}>Очистить</button></div>
        </div>
</div>,
        image:<div className="mv-player-settings"><label>Устройство<select aria-label="Профиль устройства" value={prefs.deviceProfile||'auto'} onChange={event=>{setGpuAttempt(n=>n+1);changePrefs({deviceProfile:event.target.value});}}><option value="auto">Автоматически</option><option value="phone">Телефон / Android</option><option value="tablet">Планшет</option><option value="desktop">Компьютер</option></select></label><label>Улучшение<select aria-label="Алгоритм улучшения" value={prefs.gpu?(prefs.upscaler||'auto'):'off'} onChange={event=>retryGpu(event.target.value)}><option value="off">Выключено</option><option value="auto">Авто · {deviceProfile==='desktop'?'Anime4K':'мобильный GPU'}</option><option value="mobile">Мобильный GPU · лёгкий</option><option value="anime4k">Anime4K ×2 · мощный GPU</option><option value="fsrcnn">FSRCNN ×2 · WebGPU</option></select></label>
        {prefs.gpu&&<label>Нагрузка<select aria-label="Режим улучшения" value={prefs.neuralMode||'balanced'} onChange={event=>changePrefs({neuralMode:event.target.value})}><option value="performance">Экономный</option><option value="balanced">Баланс</option><option value="quality">Качество</option></select></label>}
        {neuralStats&&prefs.gpu&&<small>{engineName}: {neuralStats.width}×{neuralStats.height} · {neuralStats.fps} кадр/с · {neuralStats.latency} мс{(neuralStats.adapter||neuralStats.renderer)?' · '+(neuralStats.adapter||neuralStats.renderer):''}{neuralStats.software?' · программный рендерер браузера':''}</small>}
        {gpuWarning&&<button onClick={()=>retryGpu(mobileDevice?'mobile':prefs.upscaler)}>Повторить на новом GPU-контексте</button>}
        <p className="player-setting-help">Мобильный режим обрабатывает текстуру видео в WebGL без нейросети на CPU. Anime4K оставлен для мощных GPU. Если браузер отключил аппаратное ускорение, сайт не может включить видеокарту за него. Мини-окно показывает исходник.</p></div>,
        captions:<div className="mv-player-settings">        <label>Субтитры<select value={subtitle} onChange={event=>setSubtitle(event.target.value)}>
          <option value="off">Выключены</option>
          {availableTracks.map(track=><option key={track.id} value={track.id}>{track.name}</option>)}
        </select></label>
        <label>Размер субтитров<input aria-label="Размер субтитров" type="range" min="16" max="40" step="2"
          value={prefs.subSize} onChange={event=>changePrefs({subSize:Number(event.target.value)})}/></label>
        <label>Отступ субтитров<input aria-label="Отступ субтитров" type="range" min="3" max="22" step="1"
          value={prefs.subOffset} onChange={event=>changePrefs({subOffset:Number(event.target.value)})}/></label>
<button className="mv-player-settings-action" onClick={()=>subtitleInput.current?.click()}><Subtitles size={16}/> Загрузить SRT / VTT</button></div>,
        actions:<div className="mv-player-settings">        <div className="mv-player-quick-actions"><button onClick={actions.share}><Share2 size={19}/><span>Поделиться</span></button><button onClick={actions.screenshot}><Camera size={19}/><span>Кадр</span></button><button onClick={actions.clip} disabled={actions.recording} aria-pressed={actions.recording}><Video size={19}/><span>{actions.recording?'Запись…':'Клип'}</span></button></div>
<p className="player-setting-help">Ссылка откроет эту серию с текущей позиции после входа в библиотеку. Клип записывается до 30 секунд.</p></div>
      }}</PlayerSettings>}</AnimatePresence>
      {canSkip&&panel==='watch'&&<button className="mv-player-skip" onClick={()=>seek(opening.end)}><SkipForward size={16}/> Пропустить опенинг</button>}
      {gpuActive&&<span className="mv-player-gpu-tag"><Sparkles size={12}/> {engineName}{engine==='mobile'?'':' ×2'}{neuralStats?` · ${neuralStats.fps} кадр/с`:``}</span>}
      {busy&&<div className="mv-player-loading" role="status">Готовим видео…</div>}
      <div className="mv-player-console" onPointerEnter={revealControls}>
        <div className="mv-player-timeline">{gestures.feedback?.type==='seek'&&<output className="mv-player-seek-preview" style={{left:Math.max(8,Math.min(92,progress))+'%'}}>{clock(previewTime)} <small>{gestures.feedback.delta>=0?'+':'−'}{Math.abs(Math.round(gestures.feedback.delta))} сек.</small></output>}<input aria-label="Перемотка видео" type="range" min="0" max={seekable?duration:1}
          value={Math.min(previewTime,seekable?duration:1)} disabled={!seekable} step="0.1" onChange={event=>seek(Number(event.target.value))}
          style={{'--played':progress+'%','--buffered':Math.max(progress,seekable?buffered/duration*100:0)+'%'}}/></div>
        <div className="mv-player-controls">
          <div className="mv-player-control-group">
            <button className="mv-player-play" aria-label={playing?'Пауза':'Воспроизвести'} onClick={toggle} disabled={!source}><AnimatePresence initial={false}><motion.span key={playing?'pause':'play'} initial={{opacity:0,scale:.9}} animate={{opacity:1,scale:1}} exit={{opacity:0,scale:.9}} transition={{duration:reducedMotion?0:.14}}>{playing?<Pause size={21} fill="currentColor"/>:<Play size={21} fill="currentColor"/>}</motion.span></AnimatePresence></button>
            <button aria-label={effectiveVolume===0?'Включить звук':'Отключить звук'} onClick={()=>{if(effectiveVolume===0){setMuted(false);if(!prefs.volume)changePrefs({volume:1});}else setMuted(true);}}><VolumeGlyph value={prefs.volume} muted={muted}/></button>
            <input className="mv-player-volume" type="range" min="0" max="1" step=".05" value={prefs.volume} aria-label="Громкость" onChange={event=>{setMuted(false);changePrefs({volume:Number(event.target.value)});}}/>
            <span className="mv-player-time">{clock(time)} <span>/ {clock(duration)}</span></span>
          </div>
          <div className="mv-player-control-group">
            <button aria-label={isPip?'Закрыть мини-окно':'Мини-окно'} aria-pressed={isPip} title="Мини-окно" disabled={!videoRef.current?.requestPictureInPicture&&!videoRef.current?.webkitSetPresentationMode} onClick={pip}><PictureInPicture2 size={19}/></button>
            {musicIdentity&&<button aria-label="Музыка из аниме" aria-expanded={musicOpen} onClick={()=>setMusicOpen(v=>!v)}><Music2 size={19}/></button>}<button className={settingsOpen?'is-active':''} aria-label="Настройки плеера" aria-expanded={settingsOpen} onClick={()=>openPanel(settingsOpen?'watch':'settings')}><SettingsGlyph/></button>
            <button aria-label={isFullscreen?'Выйти из полноэкранного режима':'На весь экран'} onClick={fullscreen}>{isFullscreen?<Minimize2 size={20}/>:<Maximize2 size={20}/>}</button>
          </div>
        </div>
      </div>
    </div>
    <input ref={subtitleInput} type="file" accept=".srt,.vtt,text/vtt" hidden onChange={attachSubtitle}/>
    {musicOpen&&<aside className="mv-player-music"><button className="icon-button" aria-label="Закрыть музыку" onClick={()=>setMusicOpen(false)}><X size={17}/></button><Soundtrack identity={musicIdentity} userId={userId} compact/></aside>}
    {episodes.length>1&&<section className="mv-player-shelf" inert={settingsOpen} aria-label="Эпизоды сезона">
      <div className="mv-player-shelf-heading">{panel==='episodes'&&<button aria-label="Закрыть эпизоды" onClick={()=>openPanel('watch')}><X size={20}/></button>}<div className="mv-player-season-title">{seasons.length>1?<label><span className="sr-only">Сезон</span><select value={season?.id||''} onChange={event=>choose(seasons.find(s=>s.id===event.target.value)?.episodes[0]?.variants[0]?.item)}>{seasons.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label>:<span>{season?.name}</span>}<button className="mv-player-expand-episodes" aria-label="Развернуть эпизоды" onClick={()=>openPanel(panel==='episodes'?'watch':'episodes')}>{season?.episodes.length} эпизодов <ChevronsUp size={12}/></button></div><div><button aria-label="Предыдущие эпизоды" onClick={()=>scrollEpisodes(-360)}><ChevronLeft size={18}/></button><button aria-label="Следующие эпизоды" onClick={()=>scrollEpisodes(360)}><ChevronRight size={18}/></button></div></div>
      <div className="mv-player-rail" ref={railRef}>{season?.episodes.map((ep,i)=>{
        const current=ep===episode;
        return <button key={ep.id} className={'mv-player-card'+(current?' is-current':'')} aria-current={current?'true':undefined} onClick={()=>{choose(ep.variants[0]?.item);openPanel('watch');}}>
          <span className="mv-player-card-art">{renderEpisodeArtwork?renderEpisodeArtwork(ep.variants.find(v=>v.item.id===item.id)?.item||ep.variants.find(v=>v.item.previewArtwork)?.item||ep.variants[0]?.item,i):null}{(!renderEpisodeArtwork)&&(ep.variants[0]?.item.preview||item.preview||scene.image)&&<img className="mv-player-card-preview" src={ep.variants[0]?.item.preview||item.preview||scene.image} alt=""/>}<span className="mv-player-card-number">{String(ep.number||i+1).padStart(2,'0')}</span><small>{current?'СЕЙЧАС':String(i+1).padStart(2,'0')}</small></span>
          <strong>{ep.label}</strong><small>{ep.variants[0]?.label}</small>
        </button>;
      })}</div>
    </section>}
    {gpuWarning&&<p className="mv-player-warning" role="status">{gpuWarning}</p>}

  </div>;
}
