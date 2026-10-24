import {useEffect,useMemo,useRef,useState} from 'react';
import {Pause,Play,Settings2,SkipForward,Subtitles,Volume2,VolumeX,PictureInPicture2,Maximize2,ChevronLeft,ChevronRight,Sparkles,X} from 'lucide-react';
import './player.css';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import usePlayerAtmosphere from './use-player-atmosphere.js';
import {buildPlaybackLibrary,openingBounds,toWebVtt} from './player-model.js';
import {startNeuralUpscaler} from './neural-upscaler.js';
import {diagnoseVideoFailure} from './playback-diagnostics.js';

const PREF_KEY='mediavault_player_preferences_v1';
const DEFAULTS={speed:1,volume:1,autoNext:false,autoSkip:false,gpu:false,neuralMode:'balanced',subSize:24,subOffset:8};
function getPrefs(){
  try{return {...DEFAULTS,...JSON.parse(localStorage.getItem(PREF_KEY)||'{}')};}catch{return DEFAULTS;}
}
function clock(seconds){
  if(!Number.isFinite(seconds)||seconds<0)return '00:00';
  const n=Math.floor(seconds),h=Math.floor(n/3600),m=Math.floor(n%3600/60),s=n%60;
  return (h?h+':'+String(m).padStart(2,'0'):String(m).padStart(2,'0'))+':'+String(s).padStart(2,'0');
}
function keyFor(libraryId,id){return 'mediavault_playback_'+String(libraryId||'local')+'_'+id;}
function readResume(key){
  try{const value=Number(localStorage.getItem(key));return Number.isFinite(value)&&value>=10?value:0;}catch{return 0;}
}
function writeResume(key,value){
  try{if(value>10)localStorage.setItem(key,String(Math.floor(value)));else localStorage.removeItem(key);}catch{}
}
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
export default function VideoPlayer({item,source,catalog,libraryId,mediaRef,onSelectItem,onError,busy}){
  const ownRef=useRef(null),canvasRef=useRef(null),stageRef=useRef(null),railRef=useRef(null);
  const videoRef=mediaRef||ownRef;
  const reducedMotion=useReducedMotion();
  const [prefs,setPrefs]=useState(getPrefs);
  const [time,setTime]=useState(0),[duration,setDuration]=useState(0),[buffered,setBuffered]=useState(0);
  const [playing,setPlaying]=useState(false),[muted,setMuted]=useState(false);
  const [panel,setPanel]=useState('watch'),[localTrack,setLocalTrack]=useState('');
  const [controlsVisible,setControlsVisible]=useState(true);
  const hideTimer=useRef(null);
  const settingsOpen=panel==='settings';
  const scene=usePlayerAtmosphere(videoRef,source,playing,stageRef);
  const [subtitle,setSubtitle]=useState('off'),[availableTracks,setAvailableTracks]=useState([]);
  const [audioTracks,setAudioTracks]=useState([]),[activeAudio,setActiveAudio]=useState(0);
  const [subtitleText,setSubtitleText]=useState(''),[gpuActive,setGpuActive]=useState(false);
  const [gpuWarning,setGpuWarning]=useState('');
  const [neuralStats,setNeuralStats]=useState(null);
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
  useEffect(()=>()=>clearTimeout(hideTimer.current),[]);
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
    let disposed=false,stop;
    const canvas=canvasRef.current;
    canvas.style.opacity='0';
    setGpuWarning('');setNeuralStats(null);setGpuActive(false);
    (async()=>{
      try{
        stop=await startNeuralUpscaler(videoRef.current,canvas,{
          mode:prefs.neuralMode,
          onStats:stats=>{if(!disposed)setNeuralStats(stats);},
          onFailure:error=>{
            if(disposed)return;
            setGpuWarning(error.message||'Ошибка нейросетевого инференса.');
            setGpuActive(false);
            changePrefs({gpu:false});
          }
        });
        if(disposed)stop();
        else setGpuActive(true);
      }catch(error){
        if(disposed)return;
        setGpuActive(false);
        setGpuWarning(error.message||'FSRCNN недоступна. Включено исходное видео.');
        changePrefs({gpu:false});
      }
    })();
    return()=>{disposed=true;stop?.();canvas.style.opacity='0';};
  },[source,prefs.gpu,prefs.neuralMode]);
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
      writeResume(keyFor(libraryId,item.id),video.currentTime);
    }
  }
  function loaded(){
    const video=videoRef.current;if(!video)return;
    setDuration(Number.isFinite(video.duration)?video.duration:0);
    video.playbackRate=Number(prefs.speed)||1;video.volume=Math.max(0,Math.min(1,Number(prefs.volume)));
    if(!resumeApplied.current){
      resumeApplied.current=true;
      const point=readResume(keyFor(libraryId,item.id));
      if(point>0&&point<video.duration-12)seek(point);
    }
  }
  function choose(nextItem,keepTime=false){
    if(!nextItem||nextItem.id===item.id)return;
    if(keepTime)writeResume(keyFor(libraryId,nextItem.id),videoRef.current?.currentTime||0);
    onSelectItem?.(nextItem);
  }
  function nextEpisode(){choose(next);}
  function ended(){
    setPlaying(false);writeResume(keyFor(libraryId,item.id),0);
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
      if(event.altKey||event.ctrlKey||event.metaKey||
        ['INPUT','SELECT','TEXTAREA','BUTTON'].includes(document.activeElement?.tagName)||
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
  const seekable=duration>0&&Number.isFinite(duration);
  const canSkip=opening&&time>=opening.start&&time<opening.end;
  const hiddenControls=playing&&panel==='watch'&&!controlsVisible;
  const progress=seekable?Math.min(100,time/duration*100):0;
  return <div ref={stageRef} className={'mv-player'+(playing?' is-playing':'')+(panel!=='watch'?' is-browsing':'')+(hiddenControls?' controls-hidden':'')}
    style={{'--scene-rgb':scene.color}} aria-label="Видеоплеер MediaVault" role="region" onPointerMove={revealControls}
    onTouchStart={revealControls} onFocusCapture={revealControls}>
    <div className="mv-player-screen">
      <div className="mv-player-ambient" aria-hidden="true"/>
      <div className="mv-player-panorama" aria-hidden="true"><AnimatePresence>{scene.image&&!playing&&<motion.img key={scene.image} src={scene.image} initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} transition={{duration:reducedMotion?0:1.2}}/>}</AnimatePresence></div>
      <div className="mv-player-stage">
        <video ref={videoRef} src={source||undefined} playsInline preload="metadata" muted={muted}
          onLoadedMetadata={loaded} onTimeUpdate={onTime}
          onPlay={()=>setPlaying(true)} onPause={()=>{setPlaying(false);writeResume(keyFor(libraryId,item.id),videoRef.current?.currentTime||0);}}
          onDurationChange={loaded} onEnded={ended}
          onError={()=>{if(source)diagnoseVideoFailure({video:videoRef.current,source}).then(message=>onError?.(Error(message))).catch(()=>{});}}
          onClick={()=>{revealControls();toggle();}} aria-label="Воспроизвести или приостановить видео">{localTrack&&<track key={localTrack} kind="subtitles" src={localTrack} srcLang="ru" label="Загруженные субтитры"/>}</video>
        <canvas ref={canvasRef} className="mv-player-canvas" aria-hidden="true"/>
        {subtitleText&&<div className="mv-player-captions" style={{fontSize:prefs.subSize+'px',bottom:(hiddenControls?prefs.subOffset:Math.max(22,prefs.subOffset))+'%'}} aria-live="off">{subtitleText}</div>}
      </div>
      <div id="player-panel-watch" hidden={panel!=='watch'} className="mv-player-watch">
        <AnimatePresence>{!playing&&<motion.div className="mv-player-overview" initial={{opacity:0,y:24,filter:'blur(8px)'}} animate={{opacity:1,y:0,filter:'blur(0px)'}} exit={{opacity:0,y:-12,filter:'blur(5px)'}} transition={{duration:reducedMotion?0:.65,ease:[.22,1,.36,1]}}>
          <h1>{library.title.replace(/\.(mp4|mkv|webm|mov|m4v|avi)$/i,'')}</h1>
          <p>{season?.name}<span> / </span>{episode?.label}</p>
        </motion.div>}</AnimatePresence>
      </div>
      <AnimatePresence mode="wait">
      {panel!=='watch'&&<motion.section key={panel} initial={{opacity:0,x:-40}} animate={{opacity:1,x:0}} exit={{opacity:0,x:-30}} transition={{duration:reducedMotion?0:.55,ease:[.22,1,.36,1]}} id="player-settings" role="region" aria-label="Настройки просмотра" className="mv-player-drawer">
        <div className="mv-player-drawer-head"><h2>Настройки</h2><button aria-label="Закрыть настройки" onClick={()=>openPanel('watch')}><X size={19}/></button></div>
        <div className="mv-player-settings">
        {episode?.variants.length>1&&<label>Озвучка<select value={item.id} onChange={event=>choose(episode.variants.find(v=>v.item.id===event.target.value)?.item,true)}>{episode.variants.map(v=><option key={v.item.id} value={v.item.id}>{v.label}</option>)}</select></label>}
        <label>Скорость<select value={prefs.speed} onChange={event=>changePrefs({speed:Number(event.target.value)})}>
          {[0.5,0.75,1,1.25,1.5,1.75,2].map(v=><option key={v} value={v}>{v}×</option>)}</select></label>
        {audioTracks.length>1&&<label>Аудиодорожка<select value={activeAudio} onChange={event=>switchAudio(Number(event.target.value))}>
          {audioTracks.map(a=><option key={a.index} value={a.index}>{a.name}</option>)}</select></label>}
        <label>Субтитры<select value={subtitle} onChange={event=>setSubtitle(event.target.value)}>
          <option value="off">Выключены</option>
          {availableTracks.map(track=><option key={track.id} value={track.id}>{track.name}</option>)}
        </select></label>
        <label>Размер субтитров<input aria-label="Размер субтитров" type="range" min="16" max="40" step="2"
          value={prefs.subSize} onChange={event=>changePrefs({subSize:Number(event.target.value)})}/></label>
        <label>Отступ субтитров<input aria-label="Отступ субтитров" type="range" min="3" max="22" step="1"
          value={prefs.subOffset} onChange={event=>changePrefs({subOffset:Number(event.target.value)})}/></label>
        <label className="mv-player-check"><input type="checkbox" checked={prefs.autoNext}
          onChange={event=>changePrefs({autoNext:event.target.checked})}/> Следующий эпизод автоматически</label>
        <label className="mv-player-check"><input type="checkbox" checked={prefs.autoSkip}
          onChange={event=>changePrefs({autoSkip:event.target.checked})}/> Автоматически пропускать опенинг</label>
        <label className="mv-player-check"><input type="checkbox" checked={prefs.gpu}
          onChange={event=>changePrefs({gpu:event.target.checked})}/> Улучшение изображения · AI ×2</label>
        {prefs.gpu&&<label>Режим улучшения<select value={prefs.neuralMode||'balanced'}
          onChange={event=>changePrefs({neuralMode:event.target.value})}>
          <option value="performance">Экономный · 320px</option>
          <option value="balanced">Баланс · 480px</option>
          <option value="quality">Качество · 640px</option>
        </select></label>}
        {neuralStats&&prefs.gpu&&<small>FSRCNN: {neuralStats.width}×{neuralStats.height}, {neuralStats.fps} FPS, {neuralStats.latency} мс/кадр</small>}
        <div className="mv-player-intro"><span>Опенинг: {opening?clock(opening.start)+' – '+clock(opening.end):'не размечен'}</span>
          <div><button onClick={()=>setOpeningDraft(time)}>Начало {openingDraft!==null?'('+clock(openingDraft)+')':''}</button>
          <button disabled={openingDraft===null} onClick={markEnd}>Конец</button>
          <button disabled={!opening} onClick={()=>setIntro(null)}>Очистить</button></div>
        </div>
        <small>Улучшение работает на твоём устройстве. При высокой нагрузке включится исходное видео. В режиме «Картинка в картинке» улучшение недоступно.</small>
        <button className="mv-player-settings-action" onClick={()=>subtitleInput.current?.click()}><Subtitles size={16}/> Загрузить субтитры SRT / VTT</button>
        <button className="mv-player-settings-action" disabled={!videoRef.current?.requestPictureInPicture} onClick={()=>videoRef.current?.requestPictureInPicture?.().catch(()=>{})}><PictureInPicture2 size={16}/> Картинка в картинке</button>
      </div>
      </motion.section>}</AnimatePresence>
      {canSkip&&panel==='watch'&&<button className="mv-player-skip" onClick={()=>seek(opening.end)}><SkipForward size={16}/> Пропустить опенинг</button>}
      {gpuActive&&<span className="mv-player-gpu-tag"><Sparkles size={12}/> AI ×2{neuralStats?` · ${neuralStats.fps} FPS`:``}</span>}
      {busy&&<div className="mv-player-loading" role="status">Готовим видео…</div>}
      <div className="mv-player-console" onPointerEnter={revealControls}>
        <div className="mv-player-timeline"><input aria-label="Перемотка видео" type="range" min="0" max={seekable?duration:1}
          value={Math.min(time,seekable?duration:1)} disabled={!seekable} step="0.1" onChange={event=>seek(Number(event.target.value))}
          style={{'--played':progress+'%','--buffered':Math.max(progress,seekable?buffered/duration*100:0)+'%'}}/></div>
        <div className="mv-player-controls">
          <div className="mv-player-control-group">
            <button className="mv-player-play" aria-label={playing?'Пауза':'Воспроизвести'} onClick={toggle} disabled={!source}>{playing?<Pause size={21} fill="currentColor"/>:<Play size={21} fill="currentColor"/>}</button>
            <button aria-label={muted?'Включить звук':'Отключить звук'} onClick={()=>setMuted(!muted)}>{muted?<VolumeX size={19}/>:<Volume2 size={19}/>}</button>
            <input className="mv-player-volume" type="range" min="0" max="1" step=".05" value={prefs.volume} aria-label="Громкость" onChange={event=>changePrefs({volume:Number(event.target.value)})}/>
            <span className="mv-player-time">{clock(time)} <span>/ {clock(duration)}</span></span>
          </div>
          <div className="mv-player-control-group">
            <button className={settingsOpen?'is-active':''} aria-label="Настройки плеера" aria-expanded={settingsOpen} onClick={()=>openPanel(settingsOpen?'watch':'settings')}><Settings2 size={20}/></button>
            <button aria-label="На весь экран" onClick={fullscreen}><Maximize2 size={20}/></button>
          </div>
        </div>
      </div>
    </div>
    <input ref={subtitleInput} type="file" accept=".srt,.vtt,text/vtt" hidden onChange={attachSubtitle}/>
    {episodes.length>1&&<section className="mv-player-shelf" inert={playing||panel!=='watch'} aria-label="Эпизоды сезона">
      <div className="mv-player-shelf-heading"><div className="mv-player-season-title">{seasons.length>1?<label><span className="sr-only">Сезон</span><select value={season?.id||''} onChange={event=>choose(seasons.find(s=>s.id===event.target.value)?.episodes[0]?.variants[0]?.item)}>{seasons.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label>:<span>{season?.name}</span>}<small>{season?.episodes.length} эпизодов</small></div><div><button aria-label="Предыдущие эпизоды" onClick={()=>scrollEpisodes(-360)}><ChevronLeft size={18}/></button><button aria-label="Следующие эпизоды" onClick={()=>scrollEpisodes(360)}><ChevronRight size={18}/></button></div></div>
      <div className="mv-player-rail" ref={railRef}>{season?.episodes.map((ep,i)=>{
        const current=ep===episode;
        return <button key={ep.id} className={'mv-player-card'+(current?' is-current':'')} aria-current={current?'true':undefined} onClick={()=>{choose(ep.variants[0]?.item);openPanel('watch');}}>
          <span className="mv-player-card-art">{scene.image&&current&&<img className="mv-player-card-preview" src={scene.image} alt=""/>}<span className="mv-player-card-number">{String(ep.number||i+1).padStart(2,'0')}</span><small>{current?'СЕЙЧАС':String(i+1).padStart(2,'0')}</small></span>
          <strong>{ep.label}</strong><small>{ep.variants[0]?.label}</small>
        </button>;
      })}</div>
    </section>}
    {gpuWarning&&<p className="mv-player-warning" role="status">{gpuWarning}</p>}

  </div>;
}
