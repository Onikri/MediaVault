import UiSelect from './UiSelect.jsx';
import {useHostRoom} from './watch-room.js';
import RoomConversation from './RoomConversation.jsx';
import {roomControlRows} from './WatchRoomControls.jsx';
import './watch-room.css';
import './interface-refinement.css';
import {Music2,Pause,Play,Settings2,SkipForward,Subtitles,PictureInPicture2,Maximize2,Minimize2,ChevronLeft,ChevronRight,Sparkles,X,Sun,Share2,Camera,Video,ChevronsUp,ChevronsDown,Users,RotateCcw,RotateCw,Captions,Download,RectangleHorizontal,SlidersHorizontal,ChevronsRight} from 'lucide-react';
import './player-redesign.css';
import './player.css';
import './player-refinement.css';
import './player-comfort.css';
import PlayerPopover from './PlayerPopover.jsx';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {readProgress,writeProgress} from './playback-progress.js';
import PauseFrameEffects from './PauseFrameEffects.jsx';
import TimelinePreview from './TimelinePreview.jsx';
import {playMusic} from './music-player.js';
import PlayerSongCue from './PlayerSongCue.jsx';
import PlayerSettings,{SettingsGlyph} from './PlayerSettings.jsx';
import {diagnoseVideoFailure} from './playback-diagnostics.js';
import {captureEpisodePreview} from './episode-preview-cache.js';
import {contiguousBufferEnd} from './watch-quality.js';
import {useEffect,useImperativeHandle,useRef,useState} from 'react';
import {isShortEpisodeClip} from './watch-session.js';
import usePlayerController from './player-controller.js';
import {clock,keyFor,readResume,openerKey} from './player-runtime.js';
import {PlayerContext,usePlayerSession,usePlayerExtensions,usePlayerMediaSession} from './player-session.js';
import PlayerExtensionSlot from './PlayerExtensionSlot.jsx';
import {createPortal} from 'react-dom';
import './player-shell.css';
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
export default function MediaVaultPlayer({item,source,catalog,libraryId,userId,mediaRef,onSelectItem,onError,busy,renderEpisodeArtwork,onPlaybackChange,onPlaybackRecovered,minimumDuration=0,onRejectedSource,onlineControls,onPreview,onClose,autoPlay=false,characterService,extensions=[],apiRef,roomControl}){
  const controller=usePlayerController({item,source,catalog,libraryId,userId,mediaRef,onSelectItem,onError,busy,renderEpisodeArtwork,onPlaybackChange,onlineControls,onPreview,onClose,autoPlay,characterService,roomControl});
  const {timeline,canvasRef,stageRef,railRef,videoRef,health,streaming,reducedMotion,prefs,hoverSeek,setHoverSeek,seekTimer,time,duration,buffered,setBuffered,playing,setPlaying,muted,setMuted,audioError,setAudioError,external,previewCaptured,isFullscreen,isPip,panel,musicOpen,setMusicOpen,theater,settingsTab,setSettingsTab,localTrack,settingsButton,musicButton,cinema,musicIdentity,episodeMusic,dismissedCue,setDismissedCue,settingsOpen,scene,subtitle,setSubtitle,availableTracks,audioTracks,activeAudio,subtitleText,gpuActive,gpuWarning,neuralStats,gpuAttempt,setGpuAttempt,mobileDevice,deviceProfile,engine,colors,color,colorFilter,engineName,retryGpu,opening,openingDraft,setOpeningDraft,introOffset,setIntroOffset,effectiveOpening,ending,activeTheme,currentSong,subtitleInput,library,seasons,episodes,season,shelfSeason,setBrowsedSeasonId,episode,characterContext,index,revealControls,scrollEpisodes,openPanel,changePrefs,seek,onTime,loaded,choose,ended,toggle,fullscreen,switchAudio,attachSubtitle,setIntro,markEnd,gestures,actions,previewTime,effectiveVolume,pip,seekable,skipRange,canSkip,hiddenControls,progress}=controller;
  const api=usePlayerSession(controller);
  const room=useHostRoom(api,characterService,item,source,characterContext,!roomControl,onlineControls);
  useImperativeHandle(apiRef,()=>api,[api]);
  usePlayerExtensions(api,extensions,onError);
  function seekAtPointer(event){
    const node=event.currentTarget;if(node.disabled||!seekable)return;
    const bounds=node.getBoundingClientRect();event.preventDefault();event.stopPropagation();
    seek(Math.max(0,Math.min(1,(event.clientX-bounds.left)/bounds.width))*duration);
  }
  const selectorSeasons=onlineControls?.seasonOptions||seasons;
  usePlayerMediaSession(api);
  // On a title page the room chat takes the right column's top (ratings slide
  // below it) so the player keeps its width while a room is live.
  const [chatSlot,setChatSlot]=useState(null),roomLive=!!room.info;
  useEffect(()=>{
    const sidebar=roomLive&&stageRef.current?.closest('.mv-title-layout')?.querySelector('.title-sidebar');
    if(!sidebar||getComputedStyle(sidebar).display==='none'){setChatSlot(null);return;}
    const slot=document.createElement('div');slot.className='room-chat-slot';sidebar.prepend(slot);sidebar.classList.add('has-room-chat');setChatSlot(slot);
    return()=>{slot.remove();sidebar.classList.remove('has-room-chat');setChatSlot(null);};
  },[roomLive]);
  const toggleCaptions=controller.toggleCaptions;
  // Online sessions are capability URLs: the server remuxes the playing
  // quality into one MP4 (no re-encode). Rooms relay someone else's stream.
  const onlineMatch=/^(https?:\/\/[^/]+)\/online\/([\w-]{20,80})\/([\w-]{10,40})$/.exec(source||'');
  const canDownload=!roomControl&&!room.info&&(!!onlineMatch||String(source||'').startsWith('blob:'));
  const [downloadOpen,setDownloadOpen]=useState(false),downloadButton=useRef(null);
  const defaultName=[library.title.replace(/\.(mp4|mkv|webm|mov|m4v|avi)$/i,''),episode?.label].filter(Boolean).join(' · ')||'MediaVault';
  const downloadHeights=[...new Set([...streaming.levels.map(l=>l.height||0),...(onlineControls?.qualities||[]).map(Number)])].filter(h=>h>0).sort((a,b)=>b-a);
  const [downloadHeight,setDownloadHeight]=useState(0),[downloadName,setDownloadName]=useState('');
  useEffect(()=>{if(downloadOpen){setDownloadName(defaultName);setDownloadHeight(streaming.levels.find(l=>l.index===streaming.level)?.height||downloadHeights[0]||0);}},[downloadOpen]);
  function download(chosen,label){
    const name=(label||'').trim()||defaultName;
    const current=streaming.levels.find(l=>l.index===streaming.level)?.height,best=Math.max(0,...streaming.levels.map(l=>l.height||0));
    const requested=onlineControls?.quality&&onlineControls.quality!=='best'?Number(onlineControls.quality):0;
    const href=onlineMatch?onlineMatch[1]+'/online/'+onlineMatch[2]+'/'+onlineMatch[3]+'/download?'+new URLSearchParams({height:String(chosen||current||requested||best||0),name}):source;
    const link=document.createElement('a');link.href=href;link.download=name+'.mp4';link.rel='noopener';document.body.append(link);link.click();link.remove();
  }
  return <PlayerContext.Provider value={api}><div className={'player-room-layout'+(room.info&&!chatSlot?' has-live-room':'')}><div ref={stageRef} className={'mv-player'+(playing?' is-playing':'')+(panel!=='watch'?' is-browsing':'')+(hiddenControls?' controls-hidden':'')+(theater?' is-theater':'')+(!prefs.depthShadow?' depth-shadow-off':'')+(!prefs.ambient?' ambient-off':'')+(panel==='episodes'?' episodes-open':'')}
    style={{'--scene-rgb':scene.color,'--video-brightness':gestures.brightness,'--picture-filter':colorFilter}} aria-label="Видеоплеер MediaVault" role="region" tabIndex={0} onPointerDown={event=>{if(!event.target.closest('button,input,select,a,[role="dialog"]'))stageRef.current?.focus({preventScroll:true});}} onPointerMove={revealControls}
    onTouchStart={revealControls} onFocusCapture={revealControls} data-player="mediavault">
    <div className="mv-player-screen">
      {(episodes.length>1||onlineControls?.episodeBrowser)&&<div className="mv-player-top-selectors">{selectorSeasons.length>1&&<label><span className="sr-only">Сезон плеера</span><UiSelect aria-label="Сезон плеера" value={onlineControls?.browseSeasonId||shelfSeason?.id||''} onChange={event=>{if(onlineControls?.onBrowseSeason)onlineControls.onBrowseSeason(event.target.value);else setBrowsedSeasonId(event.target.value);openPanel('episodes');}}>{selectorSeasons.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</UiSelect></label>}<button aria-label="Выбрать серию" aria-expanded={panel==='episodes'} onClick={()=>openPanel(panel==='episodes'?'watch':'episodes')}>{episode?.label||'Серии'}<ChevronsDown size={14}/></button></div>}
      <div className="mv-player-ambient" aria-hidden="true"/>

      <div className="mv-player-stage">
        <video ref={videoRef} className="mv-player-touch-surface mv-player-media" {...gestures.surface} src={streaming.hls?undefined:source||undefined} crossOrigin="anonymous" playsInline preload="auto" muted={muted||!!onlineControls?.audio&&!audioError}
          onLoadedMetadata={event=>{const video=event.currentTarget;if(isShortEpisodeClip(video.duration,minimumDuration)){video.pause();onRejectedSource?.(Error('Источник вернул короткий ролик вместо полной серии.'));return;}loaded();}} onLoadedData={event=>{if(isShortEpisodeClip(event.currentTarget.duration,minimumDuration))return;const image=captureEpisodePreview(videoRef.current);if(onPreview&&image){previewCaptured.current=item.id;onPreview(item.episode,image);}}} onTimeUpdate={onTime} onProgress={()=>{const v=videoRef.current;if(v)setBuffered(contiguousBufferEnd(v.buffered,v.currentTime));}}
          onPlay={()=>{setPlaying(true);onPlaybackChange?.(true);}} onPlaying={()=>onPlaybackRecovered?.()} onPause={()=>{setPlaying(false);onPlaybackChange?.(false);if(videoRef.current?.readyState>=1)writeProgress(userId,libraryId,item,videoRef.current?.currentTime||0,videoRef.current?.duration);}}
          onDurationChange={event=>{if(!isShortEpisodeClip(event.currentTarget.duration,minimumDuration))loaded();}} onEnded={ended}
          onError={()=>{if(source)diagnoseVideoFailure({video:videoRef.current,source}).then(message=>onError?.(Error(message))).catch(()=>{});}}
          aria-label="Воспроизвести или приостановить видео">{localTrack&&<track key={localTrack} kind="subtitles" src={localTrack} srcLang="ru" label="Загруженные субтитры"/>}{onlineControls?.externalCaptions?.map(t=><track key={t.url} kind="subtitles" src={t.url} srcLang={t.language||'ru'} label={t.name}/>)}</video>
        {onlineControls?.audio&&<video ref={external.ref} hidden style={{display:"none"}} className="mv-external-audio" src={onlineControls?.audio?.type==='hls'?undefined:onlineControls?.audio?.url} crossOrigin="anonymous" playsInline preload="metadata" aria-hidden="true" onError={()=>{if(onlineControls?.audio)setAudioError('Отдельная озвучка не ответила. Включён исходный звук.');}}/>}
        <canvas key={engine+':'+deviceProfile+':'+prefs.neuralMode+':'+gpuAttempt} ref={canvasRef} className="mv-player-canvas" aria-hidden="true"/>
        <PauseFrameEffects characterContext={characterContext} characterService={characterService} userId={userId} key={item.id} videoRef={videoRef} source={source} paused={!playing} enabled={prefs.depthShadow} modelAllowed={prefs.depthModelAllowed} strength={prefs.shadowStrength} breathPeriod={prefs.breathPeriod} breathAmplitude={prefs.breathAmplitude} autoRecognize={prefs.characterAuto} visible={panel==='watch'&&!musicOpen}/>
        {subtitleText&&<div className="mv-player-captions" style={{fontSize:prefs.subSize+'px',bottom:(hiddenControls?prefs.subOffset:Math.max(22,prefs.subOffset))+'%'}} aria-live="off">{subtitleText}</div>}
      </div>
      {health.visible&&<div className="mv-playback-status" role="status">{health.phase==='blocked'?<button onClick={health.retry}>Нажми, чтобы воспроизвести</button>:health.phase==='failed'?<><span>Поток задерживается</span><button onClick={onlineControls?.retryStream||health.retry}>Повторить</button></>:<><span className="loading-ring"/>{health.phase==='loading'?'Запускаем видео…':'Подгружаем видео…'}</>}<button className="mv-status-dismiss" aria-label="Скрыть статус воспроизведения" onClick={health.dismiss}><X size={14}/></button></div>}

      <AnimatePresence>{gestures.feedback&&gestures.feedback.type!=='seek'&&<motion.output className="mv-player-gesture-hud" style={{x:'-50%',y:'-50%'}} initial={{opacity:0,scale:.9}} animate={{opacity:1,scale:1}} exit={{opacity:0,scale:.95}} aria-live="off">
        {gestures.feedback.type==='seek'?<><strong>{clock(gestures.feedback.value)}</strong><small>{gestures.feedback.delta>=0?'+':'−'}{Math.abs(Math.round(gestures.feedback.delta))} сек.</small></>:gestures.feedback.type==='brightness'?<><Sun size={25}/><strong>{Math.round(gestures.feedback.value*100)}%</strong></>:gestures.feedback.type==='volume'?<><VolumeGlyph value={effectiveVolume}/><strong>{Math.round(effectiveVolume*100)}%</strong></>:<>{gestures.feedback.type==='episodes'?<ChevronsUp size={26}/>:<ChevronsDown size={26}/>}<small>{gestures.feedback.type==='episodes'?'Эпизоды':'Настройки'}</small></>}
      </motion.output>}</AnimatePresence>
      {actions.notice&&<output className="mv-player-action-notice" role="status">{actions.notice}</output>}
      {actions.recording&&<button className="mv-player-recording" onClick={actions.clip}><i/> {actions.clipSeconds} / 30 сек. · Остановить</button>}
      <PlayerExtensionSlot name="overlay" extensions={extensions} onError={onError}/>
      <div id="player-panel-watch" className={'mv-player-watch'+(currentSong&&dismissedCue!==currentSong.id?' has-song-cue':'')} aria-hidden={panel!=='watch'||(playing&&(!currentSong||dismissedCue===currentSong.id||hiddenControls))}>
        <div className="mv-player-overview">
          {currentSong&&dismissedCue!==currentSong.id?<PlayerSongCue track={currentSong} theme={activeTheme} visible={panel==='watch'} onDismiss={()=>setDismissedCue(currentSong.id)} onPlay={()=>playMusic(currentSong)}/>:<h1>{library.title.replace(/\.(mp4|mkv|webm|mov|m4v|avi)$/i,'')}</h1>}
          <p>{onlineControls?.seasonName||season?.name}<span> / </span>{episode?.label}</p>{episode?.description&&/[а-яё]/i.test(episode.description)&&<p className="mv-episode-description">{episode.description}</p>}
        </div>
      </div>
      <AnimatePresence>
      {settingsOpen&&<PlayerSettings anchor={settingsButton} initialPage={settingsTab} onClose={()=>openPanel('watch')}>{{
        watch:<div className="mv-player-settings">{onlineControls?.configuration}<div hidden={!!onlineControls?.configuration}><label>Качество{!streaming.levels.length&&onlineControls?.qualities?.length?<UiSelect aria-label="Качество" value={onlineControls.quality} onChange={e=>onlineControls.onQuality(e.target.value)}><option value="best">Лучшее · автоматически</option>{onlineControls.qualities.map(q=><option key={q} value={q}>{q}p</option>)}</UiSelect>:streaming.levels.length?<UiSelect aria-label="Качество" value={streaming.level} onChange={e=>{const value=e.target.value;if(value.startsWith('source:'))onlineControls.onQuality(value.slice(7));else if(value==='-1'&&onlineControls?.quality&&onlineControls.quality!=='best'&&(streaming.levels.length<2||(onlineControls.qualities||[]).some(q=>q>Math.max(...streaming.levels.map(l=>l.height||0)))))onlineControls.onQuality('best');else streaming.setLevel(Number(value));}}><option value={-1}>Лучшее · автоматически</option>{streaming.levels.filter((l,i,all)=>all.findIndex(x=>x.height===l.height)===i).map(l=><option key={l.index} value={l.index}>{l.height}p</option>)}{(onlineControls?.qualities||[]).filter(q=>!streaming.levels.some(l=>l.height===q)).map(q=><option key={'source:'+q} value={'source:'+q}>{q}p</option>)}</UiSelect>:<UiSelect aria-label="Качество" value={item.id} disabled={!episode?.variants.some(v=>v.item.id!==item.id&&v.label===episode.variants.find(x=>x.item.id===item.id)?.label)} onChange={e=>choose(episode.variants.find(v=>v.item.id===e.target.value)?.item,true)}>{episode?.variants.filter(v=>v.item.id===item.id||v.label===episode.variants.find(x=>x.item.id===item.id)?.label).map(v=><option key={v.item.id} value={v.item.id}>{v.item.quality||v.item.resolution||(v.item.id===item.id&&videoRef.current?.videoHeight?videoRef.current.videoHeight+'p':'Исходное')}</option>)}</UiSelect>}</label>
        </div><p className="player-setting-help" role="status">Загружено вперёд: {Math.max(0,Math.round(buffered-time))} с · качество в авто снижается при нехватке скорости.</p>
        {onlineControls?.voices?.length>0&&<label>Звуковая дорожка<UiSelect aria-label="Озвучка в плеере" value={onlineControls.voiceId||''} onChange={e=>onlineControls.onVoice(e.target.value)}>{onlineControls.voices.map(v=><option key={v.id} value={v.id}>{v.name}</option>)}</UiSelect></label>}
        {onlineControls?.audio&&<><p className="player-setting-help">Видео сохраняет выбранное качество. Звук синхронизируется из отдельного потока; он также использует сеть.</p><label>Сдвиг звука · {Number(prefs.audioOffset)||0} с<input aria-label="Сдвиг звука" type="range" min="-30" max="30" step="0.1" value={Number(prefs.audioOffset)||0} onChange={e=>changePrefs({audioOffset:Number(e.target.value)})}/></label></>}
        {(onlineControls?.trackBusy||onlineControls?.trackError||audioError)&&<p className="player-setting-help" role="status">{audioError||onlineControls.trackError||'Подключаем дорожку…'}</p>}
        {episode?.variants.length>1&&<label>Озвучка<UiSelect value={item.id} onChange={event=>choose(episode.variants.find(v=>v.item.id===event.target.value)?.item,true)}>{episode.variants.map(v=><option key={v.item.id} value={v.item.id}>{v.label}</option>)}</UiSelect></label>}
        <label>Скорость<UiSelect value={prefs.speed} onChange={event=>changePrefs({speed:Number(event.target.value)})}>
          {[0.5,0.75,1,1.25,1.5,1.75,2].map(v=><option key={v} value={v}>{v}×</option>)}</UiSelect></label>
        {(streaming.audio.length||audioTracks.length)>1&&<label>Аудиодорожка<UiSelect value={activeAudio} onChange={event=>switchAudio(Number(event.target.value))}>
          {(streaming.audio.length?streaming.audio:audioTracks).map(a=><option key={a.index} value={a.index}>{a.name}</option>)}</UiSelect></label>}
        <label className="mv-player-check"><input type="checkbox" checked={prefs.autoNext}
          onChange={event=>changePrefs({autoNext:event.target.checked})}/> Следующий эпизод автоматически</label>
        <label className="mv-player-check"><input type="checkbox" checked={prefs.autoSkip}
          onChange={event=>changePrefs({autoSkip:event.target.checked})}/> Пропускать опенинг и эндинг</label>

</div>,
        intro:<div className="mv-player-settings"><p className="player-setting-help" role="status">{onlineControls?.sourceIntervals?.length?'Разметка '+onlineControls.sourceIntervals[0].source+' для текущего видео.':episodeMusic.timingState==='loading'?'Ищем разметку AniSkip…':episodeMusic.timingState==='ready'?'Разметка AniSkip найдена'+(episodeMusic.intervals.some(v=>v.needsReview)?' · другая длительность релиза, проверь начало.':'.'):episodeMusic.timingMessage||'Нет разметки. Можно отметить опенинг вручную.'}</p><button className="mv-player-settings-action" onClick={episodeMusic.retry}>Найти разметку опенинга</button>{episodeMusic.intervals.length>0&&<label>Сдвиг меток · {introOffset} с<input aria-label="Сдвиг меток опенинга" type="range" min="-60" max="60" step=".5" value={introOffset} onChange={e=>{const value=Number(e.target.value);setIntroOffset(value);try{localStorage.setItem(openerKey(libraryId,item.id)+':offset',String(value));}catch{}}}/></label>}        <div className="mv-player-intro"><span>Опенинг: {effectiveOpening?clock(effectiveOpening.start)+' – '+clock(effectiveOpening.end)+(effectiveOpening.source?' · '+effectiveOpening.source:''):'разметки пока нет'}</span>
          <div><button onClick={()=>setOpeningDraft(time)}>Начало {openingDraft!==null?'('+clock(openingDraft)+')':''}</button>
          <button disabled={openingDraft===null} onClick={markEnd}>Конец</button>
          <button disabled={!opening} onClick={()=>setIntro(null)}>Очистить</button></div>
        </div></div>,
        effects:<div className="mv-player-settings"><label className="mv-player-check"><input type="checkbox" checked={prefs.depthModelAllowed} onChange={e=>changePrefs({depthModelAllowed:e.target.checked})}/>Модель глубины · 27 МБ, один раз</label><label className="mv-player-check"><input type="checkbox" checked={prefs.depthShadow} onChange={e=>changePrefs({depthShadow:e.target.checked})}/>Тень по глубине на паузе</label><label>Интенсивность тени<input aria-label="Интенсивность тени на паузе" type="range" min=".2" max=".95" step=".05" value={prefs.shadowStrength} onChange={e=>changePrefs({shadowStrength:Number(e.target.value)})}/></label><label>Цикл дыхания<input aria-label="Цикл дыхания тени" type="range" min="4" max="20" step="1" value={prefs.breathPeriod||10} onChange={e=>changePrefs({breathPeriod:Number(e.target.value)})}/></label><label>Амплитуда тени<input aria-label="Амплитуда тени" type="range" min=".08" max=".35" step=".01" value={prefs.breathAmplitude||.22} onChange={e=>changePrefs({breathAmplitude:Number(e.target.value)})}/></label><label className="mv-player-check"><input type="checkbox" checked={prefs.characterAuto} onChange={e=>changePrefs({characterAuto:e.target.checked})}/>Распознавать персонажей на паузе</label><p className="player-setting-help">Глубина считается на устройстве. По кнопке или при автоопределении кадр отправляется в Gemini и AnimeTrace. Используются ключи переводчика, имена — на русском.</p><label className="mv-player-check"><input type="checkbox" checked={prefs.ambient} onChange={e=>changePrefs({ambient:e.target.checked})}/>Ambient-подсветка</label><label className="mv-player-check"><input type="checkbox" checked={theater} onChange={cinema}/>Кинотеатр · затемнить страницу</label></div>,
        image:<div className="mv-player-settings">{gpuWarning&&<button onClick={()=>retryGpu(mobileDevice?'mobile':prefs.upscaler)}>Повторить на новом GPU-контексте</button>}<label>Устройство<UiSelect aria-label="Профиль устройства" value={prefs.deviceProfile||'auto'} onChange={event=>{setGpuAttempt(n=>n+1);changePrefs({deviceProfile:event.target.value});}}><option value="auto">Автоматически</option><option value="phone">Телефон / Android</option><option value="tablet">Планшет</option><option value="desktop">Компьютер</option></UiSelect></label><label>Улучшение<UiSelect aria-label="Алгоритм улучшения" value={prefs.gpu?(prefs.upscaler||'auto'):'off'} onChange={event=>retryGpu(event.target.value)}><option value="off">Выключено</option><option value="auto">Авто · {deviceProfile==='desktop'?'Anime4K':'мобильный GPU'}</option><option value="mobile">Мобильный GPU · лёгкий</option><option value="anime4k">Anime4K ×2 · мощный GPU</option><option value="anime4k-l">Anime4K L ×2 · дискретный GPU</option><option value="anime4k-vl">Anime4K VL ×2 · высокая нагрузка</option><option value="anime4k-ul">Anime4K UL ×2 · максимальная нагрузка</option><option value="lanczos">Lanczos3 · без нейросети</option><option value="fsr">AMD FSR1 · EASU + RCAS</option><option value="fsr-soft">AMD FSR1 · мягкая резкость</option><option value="fsrcnn">FSRCNN ×2 · WebGPU</option></UiSelect></label>
        {prefs.gpu&&<label>Нагрузка<UiSelect aria-label="Режим улучшения" value={prefs.neuralMode||'balanced'} onChange={event=>changePrefs({neuralMode:event.target.value})}><option value="performance">Экономный</option><option value="balanced">Баланс</option><option value="quality">Качество</option></UiSelect></label>}
        {neuralStats&&prefs.gpu&&<small>{engineName}: {neuralStats.width}×{neuralStats.height} · {neuralStats.fps} кадр/с · {neuralStats.latency} мс{(neuralStats.adapter||neuralStats.renderer)?' · '+(neuralStats.adapter||neuralStats.renderer):''}{neuralStats.software?' · программный рендерер браузера':''}</small>}
        
        <fieldset className="player-colors"><legend>Цвет изображения</legend><div className="chip-row">{[['Оригинал',1,1,1],['Аниме · сочнее',1.18,1.06,1.01],['Мягкий',1.06,.97,1.03]].map(([name,saturation,contrast,brightness])=><button key={name} onClick={()=>color({saturation,contrast,brightness})}>{name}</button>)}</div>{[['saturation','Насыщенность',.5,1.6],['contrast','Контраст',.8,1.3],['brightness','Яркость',.8,1.2]].map(([id,label,min,max])=><label key={id}>{label}<input aria-label={label+' изображения'} type="range" min={min} max={max} step=".01" value={colors[id]??1} onChange={e=>color({[id]:Number(e.target.value)})}/><small>{Math.round((colors[id]??1)*100)}%</small></label>)}</fieldset></div>,
        captions:<div className="mv-player-settings">        <label>Субтитры<UiSelect aria-label="Субтитры" value={subtitle} onChange={event=>setSubtitle(event.target.value)}>
          <option value="off">Выключены</option>
          {streaming.subtitles.map(t=><option key={'hls:'+t.index} value={'hls:'+t.index}>{t.name}</option>)}
          {availableTracks.map(track=><option key={track.id} value={track.id}>{track.name}</option>)}
        </UiSelect></label>
        {onlineControls?.captionVoices?.length>0&&<label>Подключить из другой версии<UiSelect aria-label="Источник субтитров" value={onlineControls.subtitleId||''} onChange={e=>onlineControls.onCaptionVoice(e.target.value)}><option value="">Дорожки текущего видео</option>{onlineControls.captionVoices.map(v=><option key={v.id} value={v.id}>{v.name}</option>)}</UiSelect></label>}
        <label>Размер субтитров<input aria-label="Размер субтитров" type="range" min="16" max="40" step="2"
          value={prefs.subSize} onChange={event=>changePrefs({subSize:Number(event.target.value)})}/></label>
        <label>Отступ субтитров<input aria-label="Отступ субтитров" type="range" min="3" max="22" step="1"
          value={prefs.subOffset} onChange={event=>changePrefs({subOffset:Number(event.target.value)})}/></label>
<button className="mv-player-settings-action" onClick={()=>subtitleInput.current?.click()}><Subtitles size={16}/> Загрузить SRT / VTT</button></div>,
        room:!roomControl&&<div className="mv-player-settings">{roomControlRows(room)}</div>,
        actions:<div className="mv-player-settings">        <div className="mv-player-quick-actions">{onClose&&<button aria-label="Закрыть встроенный просмотр" onClick={onClose}><X size={19}/><span>Закрыть</span></button>}<button onClick={actions.share}><Share2 size={19}/><span>Поделиться</span></button><button onClick={actions.screenshot}><Camera size={19}/><span>Кадр</span></button><button onClick={actions.clip} disabled={actions.recording} aria-pressed={actions.recording}><Video size={19}/><span>{actions.recording?'Запись…':'Клип'}</span></button></div>
<p className="player-setting-help">Ссылка откроет эту серию с текущей позиции после входа в библиотеку. Клип записывается до 30 секунд.</p></div>
      }}</PlayerSettings>}</AnimatePresence>
      <AnimatePresence>{canSkip&&panel==='watch'&&<motion.button key={skipRange===ending?'ed':'op'} className="mv-player-skip" style={{'--skip-progress':Math.max(0,Math.min(1,(time-skipRange.start)/Math.max(1,skipRange.end-skipRange.start)))}} initial={reducedMotion?false:{opacity:0,x:16}} animate={{opacity:1,x:0}} exit={reducedMotion?undefined:{opacity:0,x:16}} transition={{duration:.2,ease:[.2,.8,.2,1]}} onClick={()=>seek(skipRange.end)}><span>{skipRange===ending?'Пропустить эндинг':'Пропустить опенинг'}</span><ChevronsRight size={18}/></motion.button>}</AnimatePresence>

      {gpuActive&&<span className="mv-player-gpu-tag"><Sparkles size={12}/> {engineName}{engine==='mobile'||engine==='lanczos'||String(engine).startsWith('fsr')?'':' ×2'}{neuralStats?` · ${neuralStats.fps} кадр/с`:``}</span>}
      {busy&&<div className="mv-player-loading" role="status">Готовим видео…</div>}
      <div className="mv-player-console" onPointerEnter={revealControls}>
        <div className="mv-player-timeline" onPointerMove={e=>{if(!seekable||!source||navigator.connection?.saveData)return;const r=e.currentTarget.getBoundingClientRect(),fraction=Math.max(0,Math.min(1,(e.clientX-r.left)/r.width));clearTimeout(seekTimer.current);const value={time:fraction*duration,left:Math.max(14,Math.min(86,fraction*100))};seekTimer.current=setTimeout(()=>setHoverSeek(value),200);}} onPointerLeave={()=>{clearTimeout(seekTimer.current);setHoverSeek(null);}} onPointerCancel={()=>{clearTimeout(seekTimer.current);setHoverSeek(null);}}><span className="mv-timeline-markers" aria-label="Разметка опенинга и эндинга">{[effectiveOpening,ending].filter(Boolean).map((v,i)=><i key={i} title={(i===0?'Опенинг':'Эндинг')+' · '+clock(v.start)+' – '+clock(v.end)} style={{left:(duration?v.start/duration*100:0)+'%',width:(duration?(v.end-v.start)/duration*100:0)+'%'}}/>)}</span>{hoverSeek&&<TimelinePreview source={source} type={item.onlineType} point={hoverSeek.time} left={hoverSeek.left}/>}{gestures.feedback?.type==='seek'&&<output className="mv-player-seek-preview" style={{left:Math.max(8,Math.min(92,progress))+'%'}}>{clock(previewTime)} <small>{gestures.feedback.delta>=0?'+':'−'}{Math.abs(Math.round(gestures.feedback.delta))} сек.</small></output>}<input ref={timeline} aria-label="Перемотка видео" type="range" min="0" max={seekable?duration:1}
          onPointerDown={event=>{if(event.button===0&&!event.currentTarget.disabled){event.currentTarget.setPointerCapture(event.pointerId);seekAtPointer(event);}}} onPointerMove={event=>{if(event.currentTarget.hasPointerCapture(event.pointerId))seekAtPointer(event);}} onPointerUp={event=>{if(event.currentTarget.hasPointerCapture(event.pointerId)){seekAtPointer(event);event.currentTarget.releasePointerCapture(event.pointerId);}}}
          value={Math.min(previewTime,seekable?duration:1)} disabled={!seekable||!!roomControl&&!roomControl.canControl} step="0.1" onChange={event=>seek(Number(event.target.value))}
          style={{'--played':progress+'%','--buffered':Math.max(progress,seekable?buffered/duration*100:0)+'%'}}/></div>
        <div className="mv-player-controls">
          <div className="mv-player-control-group">
            <button className="mv-player-play" aria-label={playing?'Пауза':'Воспроизвести'} onClick={toggle} disabled={!source}><AnimatePresence initial={false} mode="popLayout"><motion.span key={playing?'pause':'play'} initial={reducedMotion?false:{opacity:0,scale:.5,rotate:playing?-90:90}} animate={{opacity:1,scale:1,rotate:0}} exit={reducedMotion?undefined:{opacity:0,scale:.5}} transition={{type:'spring',stiffness:520,damping:30}}>{playing?<Pause size={22} fill="currentColor" strokeWidth={0}/>:<Play size={22} fill="currentColor" strokeWidth={0}/>}</motion.span></AnimatePresence></button>
            <motion.button whileTap={reducedMotion?undefined:{rotate:-40,scale:.9}} className="mv-player-jump" aria-label="Назад на 10 секунд" title="Назад 10 с · ←" disabled={!seekable} onClick={()=>seek(time-10)}><RotateCcw size={20}/><small aria-hidden="true">10</small></motion.button>
            <motion.button whileTap={reducedMotion?undefined:{rotate:40,scale:.9}} className="mv-player-jump" aria-label="Вперёд на 10 секунд" title="Вперёд 10 с · →" disabled={!seekable} onClick={()=>seek(time+10)}><RotateCw size={20}/><small aria-hidden="true">10</small></motion.button>
            <div className="mv-player-volume-group"><button aria-label={effectiveVolume===0?'Включить звук':'Отключить звук'} title="Звук · M" onClick={()=>{if(effectiveVolume===0){setMuted(false);if(!prefs.volume)changePrefs({volume:1});}else setMuted(true);}}><VolumeGlyph value={prefs.volume} muted={muted}/></button>
            <input className="mv-player-volume" type="range" min="0" max="1" step=".05" value={effectiveVolume} aria-label="Громкость" style={{'--volume':effectiveVolume*100+'%'}} onChange={event=>{setMuted(false);changePrefs({volume:Number(event.target.value)});}}/></div>
            <span className="mv-player-time">{clock(time)} <span>/ {clock(duration)}</span></span>
          </div>
          <div className="mv-player-control-group">
            {room.info&&<button className="room-active-control" title="Настройки комнаты" aria-label={'Комната · '+(room.state?.members.filter(m=>m.online).length||1)+' участников'} aria-pressed={settingsOpen&&settingsTab==='room'} onClick={()=>{setSettingsTab('room');openPanel('settings');}}><Users size={20}/><span className="room-participant-badge">{room.state?.members.filter(m=>m.online).length||1}</span></button>}
            {controller.nextEpisode&&episodes[index+1]&&<motion.button whileHover={reducedMotion?undefined:{x:2}} aria-label="Следующая серия" title={'Следующая серия · '+(episodes[index+1]?.label||'')} onClick={controller.nextEpisode}><SkipForward size={20}/></motion.button>}
            <button aria-label={subtitle==='off'?'Включить субтитры':'Выключить субтитры'} aria-pressed={subtitle!=='off'} title="Субтитры · C" onClick={toggleCaptions}><motion.span className="mv-icon" animate={{scale:subtitle!=='off'&&!reducedMotion?[1,1.18,1]:1}} transition={{duration:.25}}><Captions size={20}/></motion.span></button>
            {canDownload&&<motion.button ref={downloadButton} whileTap={reducedMotion?undefined:{y:2}} aria-label="Скачать видео" aria-expanded={downloadOpen} title="Сохранить серию на компьютер" onClick={()=>{setMusicOpen(false);setDownloadOpen(v=>!v);}}><Download size={20}/></motion.button>}
            {musicIdentity&&<button ref={musicButton} aria-label="Музыка из аниме" aria-expanded={musicOpen} onClick={()=>openPanel(musicOpen?'watch':'music')}><Music2 size={20}/></button>}
            <button ref={settingsButton} className={settingsOpen?'is-active':''} aria-label="Настройки плеера" aria-expanded={settingsOpen} onClick={()=>{setSettingsTab('watch');setMusicOpen(false);openPanel(settingsOpen?'watch':'settings');}}><SlidersHorizontal size={20}/></button>
            <button aria-label={isPip?'Закрыть мини-окно':'Мини-окно'} aria-pressed={isPip} title="Мини-окно" disabled={!document.pictureInPictureEnabled&&!('webkitSetPresentationMode' in HTMLVideoElement.prototype)} onClick={pip}><PictureInPicture2 size={20}/></button>
            <button className="mv-player-theater" title="Кинотеатр" aria-label="Режим кинотеатра" aria-pressed={theater} onClick={cinema}><RectangleHorizontal size={20}/></button>
            <button aria-label={isFullscreen?'Выйти из полноэкранного режима':'На весь экран'} title="Полный экран · F" onClick={fullscreen}><AnimatePresence initial={false} mode="popLayout"><motion.span className="mv-icon" key={isFullscreen?'min':'max'} initial={reducedMotion?false:{scale:isFullscreen?1.4:.6,opacity:0}} animate={{scale:1,opacity:1}} exit={reducedMotion?undefined:{opacity:0}} transition={{duration:.18}}>{isFullscreen?<Minimize2 size={20}/>:<Maximize2 size={20}/>}</motion.span></AnimatePresence></button>
          </div>
        </div>
      </div>
    </div>
    {panel==='episodes'&&onlineControls?.episodeBrowser&&<div className="mv-player-episode-browser" inert={settingsOpen}>{panel==='episodes'&&<button className="mv-player-close-episodes" aria-label="Закрыть серии" onClick={()=>openPanel('watch')}><X size={18}/>Серии</button>}{onlineControls.episodeBrowser}</div>}
    <PlayerExtensionSlot name="footer" extensions={extensions} onError={onError}/>
    <input ref={subtitleInput} type="file" accept=".srt,.vtt,text/vtt" hidden onChange={attachSubtitle}/>
    <AnimatePresence>{musicOpen&&<PlayerPopover anchor={musicButton} label="Музыка серии" className="mv-player-music mv-mini-menu" onClose={()=>setMusicOpen(false)}>
      <div className="mv-mini-head"><strong>Музыка серии</strong><small>{episodeMusic.tracks.length?episodeMusic.tracks.length+' песен':''}</small></div>
      {episodeMusic.tracks.length?<ul className="mv-mini-list">{episodeMusic.tracks.slice(0,8).map(t=><li key={t.id}><button onClick={()=>{playMusic(t,episodeMusic.tracks);setMusicOpen(false);}} aria-label={'Слушать '+t.title}><span className="mv-mini-badge" data-type={t.type}>{t.type||'♪'}</span><span className="mv-mini-text"><strong>{t.title}</strong><small>{(t.artists||[]).join(', ')}</small></span><Play size={14} fill="currentColor" strokeWidth={0}/></button></li>)}</ul>:<p className="mv-mini-empty">{episodeMusic.timingState==='loading'?'Ищем песни серии…':'Песни для этой серии не найдены.'}</p>}
    </PlayerPopover>}</AnimatePresence>
    <AnimatePresence>{downloadOpen&&<PlayerPopover anchor={downloadButton} label="Скачать серию" className="mv-player-download mv-mini-menu" onClose={()=>setDownloadOpen(false)}>
      <div className="mv-mini-head"><strong>Скачать серию</strong><small>MP4 · без перекодирования</small></div>
      {downloadHeights.length>0&&<div className="mv-mini-chips" role="radiogroup" aria-label="Качество файла">{downloadHeights.map(h=><button key={h} role="radio" aria-checked={downloadHeight===h} onClick={()=>setDownloadHeight(h)}>{h>=2160?'4K':h+'p'}</button>)}</div>}
      <label className="mv-mini-field">Имя файла<input value={downloadName} maxLength={120} onChange={e=>setDownloadName(e.target.value)}/></label>
      <p className="mv-mini-note">Сервер собирает файл из потока и отдаёт его постепенно. Для некоторых источников скорость равна скорости просмотра.</p>
      <div className="mv-mini-actions"><button className="mv-mini-secondary" onClick={()=>setDownloadOpen(false)}>Отмена</button><button className="mv-mini-primary" onClick={()=>{download(downloadHeight,downloadName);setDownloadOpen(false);}}><Download size={15}/>Скачать</button></div>
    </PlayerPopover>}</AnimatePresence>
    {panel==='episodes'&&episodes.length>1&&!onlineControls?.externalEpisodeList&&<section className="mv-player-shelf" inert={settingsOpen} aria-label="Эпизоды сезона">
      <div className="mv-player-shelf-heading">{panel==='episodes'&&<button aria-label="Закрыть эпизоды" onClick={()=>openPanel('watch')}><X size={20}/></button>}<div className="mv-player-season-title">{seasons.length>1?<label><span className="sr-only">Сезон</span><UiSelect aria-label="Сезон" value={shelfSeason?.id||''} onChange={event=>setBrowsedSeasonId(event.target.value)}>{seasons.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</UiSelect></label>:<span>{shelfSeason?.name}</span>}<button className="mv-player-expand-episodes" aria-label="Развернуть эпизоды" onClick={()=>openPanel(panel==='episodes'?'watch':'episodes')}>{shelfSeason?.episodes.length} эпизодов <ChevronsUp size={12}/></button></div><div><button aria-label="Предыдущие эпизоды" onClick={()=>scrollEpisodes(-360)}><ChevronLeft size={18}/></button><button aria-label="Следующие эпизоды" onClick={()=>scrollEpisodes(360)}><ChevronRight size={18}/></button></div></div>
      <div className="mv-player-rail" ref={railRef}>{shelfSeason?.episodes.map((ep,i)=>{
        const current=ep===episode;
        return <button key={ep.id} className={'mv-player-card'+(current?' is-current':'')} aria-current={current?'true':undefined} onClick={()=>{choose(ep.variants[0]?.item);openPanel('watch');}}>
          <span className="mv-player-card-art">{renderEpisodeArtwork?renderEpisodeArtwork(ep.variants.find(v=>v.item.id===item.id)?.item||ep.variants.find(v=>v.item.previewArtwork)?.item||ep.variants[0]?.item,i):null}{(!renderEpisodeArtwork)&&(ep.variants[0]?.item.preview||item.preview||scene.image)&&<img className="mv-player-card-preview" src={ep.variants[0]?.item.preview||item.preview||scene.image} alt=""/>}<span className="mv-player-card-number">{String(ep.number||i+1).padStart(2,'0')}</span><small>{current?'СЕЙЧАС':String(i+1).padStart(2,'0')}</small></span>
          <strong>{ep.label}</strong><small>{ep.variants[0]?.label}</small>
        </button>;
      })}</div>
    </section>}
    {gpuWarning&&<p className="mv-player-warning" role="status">{gpuWarning}</p>}

  </div>{room.info&&(chatSlot?createPortal(<aside className="player-room-conversation is-sidebar"><RoomConversation conversation={room.conversation}/></aside>,chatSlot):<aside className="player-room-conversation"><RoomConversation conversation={room.conversation}/></aside>)}</div></PlayerContext.Provider>;
}
