import {useEffect,useMemo,useRef,useState} from 'react';
import {useReducedMotion} from 'motion/react';
import {writeProgress} from './playback-progress.js';
import {openingBounds,toWebVtt} from './player-model.js';
import {getPrefs,PREF_KEY,clock,keyFor,readResume,openerKey,getOpening,tracksOf} from './player-runtime.js';
import {usePlayerUi,usePlayerTheater} from './player-session.js';
import usePlaybackHealth from './use-playback-health.js';
import useSmoothTimeline from './use-smooth-timeline.js';
import usePlayerGestures from './use-player-gestures.js';
import usePlayerActions from './use-player-actions.js';
import usePlayerAtmosphere from './use-player-atmosphere.js';
import {pauseContext} from './pause-character-context.js';
import {startNeuralUpscaler} from './neural-upscaler.js';
import useVideoStream from './use-video-stream.js';
import {contiguousBufferEnd} from './watch-quality.js';
import useEpisodeMusic from './use-episode-music.js';
import {musicIdentityFor} from './music-library.js';
import {startMobileGpu} from './mobile-gpu-upscaler.js';
import {startFsr} from './fsr-upscaler.js';
import useExternalAudio from './use-external-audio.js';
import {captureEpisodePreview} from './episode-preview-cache.js';
import {buildPlaybackLibrary} from './player-model.js';
export default function usePlayerController({item,source,catalog,libraryId,userId,mediaRef,onSelectItem,onError,busy,renderEpisodeArtwork,onPlaybackChange,onlineControls,onPreview,onClose,autoPlay=false,characterService}){
  const timeline=useRef(null),clockDrawn=useRef(0),keyboardHandler=useRef(null);
  const ownRef=useRef(null),canvasRef=useRef(null),stageRef=useRef(null),railRef=useRef(null);
  const videoRef=mediaRef||ownRef;
  const health=usePlaybackHealth(videoRef,source,onError,autoPlay);
  useSmoothTimeline(videoRef,timeline,source);
  const streaming=useVideoStream(videoRef,source,item.onlineType,onError,{quality:onlineControls?.quality||'best',startPosition:readResume(keyFor(userId,libraryId,item.id))||0});
  const reducedMotion=useReducedMotion();
  useEffect(()=>{const pause=()=>videoRef.current?.pause();addEventListener('mediavault-music-playing',pause);return()=>removeEventListener('mediavault-music-playing',pause);},[]);
  const [prefs,setPrefs]=useState(getPrefs);
  const [hoverSeek,setHoverSeek]=useState(null),seekTimer=useRef(null);
  useEffect(()=>()=>clearTimeout(seekTimer.current),[]);
  const [time,setTime]=useState(0),[duration,setDuration]=useState(0),[buffered,setBuffered]=useState(0);
  const [playing,setPlaying]=useState(false),[muted,setMuted]=useState(false);
  const [audioError,setAudioError]=useState('');
  const external=useExternalAudio(videoRef,audioError?'':onlineControls?.audio?.url,onlineControls?.audio?.type,Number(prefs.volume),muted,Number(prefs.audioOffset)||0,e=>setAudioError(e.message));
  useEffect(()=>setAudioError(''),[onlineControls?.audio?.url]);
  const snapshot=useRef({time:0,duration:0}),previewCaptured=useRef('');
  useEffect(()=>{const save=()=>{const v=snapshot.current;if(v.time>0)writeProgress(userId,libraryId,item,v.time,v.duration);};const hidden=()=>{if(document.visibilityState==='hidden')save();};addEventListener('pagehide',save);document.addEventListener('visibilitychange',hidden);return()=>{save();removeEventListener('pagehide',save);document.removeEventListener('visibilitychange',hidden);};},[item.id,source,userId,libraryId]);
  const [isFullscreen,setIsFullscreen]=useState(false),[isPip,setIsPip]=useState(false);
  useEffect(()=>{const v=videoRef.current;const enter=()=>setIsPip(true),leave=()=>setIsPip(false);v?.addEventListener('enterpictureinpicture',enter);v?.addEventListener('leavepictureinpicture',leave);return()=>{v?.removeEventListener('enterpictureinpicture',enter);v?.removeEventListener('leavepictureinpicture',leave);};},[]);
  useEffect(()=>{const update=()=>setIsFullscreen(document.fullscreenElement===stageRef.current);document.addEventListener('fullscreenchange',update);return()=>document.removeEventListener('fullscreenchange',update);},[]);
  const {panel,setPanel,musicOpen,setMusicOpen,theater,setTheater,settingsTab,setSettingsTab}=usePlayerUi();
  const [localTrack,setLocalTrack]=useState('');
  const [controlsVisible,setControlsVisible]=useState(true);
  const hideTimer=useRef(null),lastReveal=useRef(0);
  const settingsButton=useRef(null),musicButton=useRef(null);
  usePlayerTheater(stageRef,theater);
  function cinema(){setTheater(v=>!v);}

  const musicIdentity=musicIdentityFor(item,catalog);
  const episodeMusic=useEpisodeMusic(musicIdentity,item.episode||Number(item.name?.match(/(?:серия|episode)[ _-]*(\d+)/i)?.[1])||1,duration,onlineControls?.server||window.MEDIA_VAULT_CONFIG?.importServerUrl);
  const [dismissedCue,setDismissedCue]=useState('');
  const settingsOpen=panel==='settings';
  const scene=usePlayerAtmosphere(videoRef,source,prefs.ambient);
  const [subtitle,setSubtitle]=useState('off'),[availableTracks,setAvailableTracks]=useState([]);
  useEffect(()=>{streaming.setSubtitle(subtitle.startsWith('hls:')?Number(subtitle.slice(4)):-1);},[subtitle,source,streaming.subtitles]);
  const [audioTracks,setAudioTracks]=useState([]),[activeAudio,setActiveAudio]=useState(0);
  const [subtitleText,setSubtitleText]=useState(''),[gpuActive,setGpuActive]=useState(false);
  const [gpuWarning,setGpuWarning]=useState('');
  const [neuralStats,setNeuralStats]=useState(null),statsClock=useRef(0);
  const [gpuAttempt,setGpuAttempt]=useState(0);
  const mobileDevice=/Android|iPhone|iPad/i.test(navigator.userAgent)||matchMedia('(any-pointer: coarse)').matches;
  const deviceProfile=prefs.deviceProfile==='auto'?(mobileDevice?'phone':'desktop'):prefs.deviceProfile;
  const engine=prefs.upscaler==='auto'?(deviceProfile==='desktop'?'anime4k':'mobile'):prefs.upscaler;
  const [colors,setColors]=useState(()=>{try{return JSON.parse(localStorage.getItem('mv_video_colors')||'{}');}catch{return {};}});
  function color(change){setColors(old=>{const next={...old,...change};localStorage.setItem('mv_video_colors',JSON.stringify(next));return next;});}
  const colorFilter=`saturate(${colors.saturation??1}) contrast(${colors.contrast??1}) brightness(${colors.brightness??1})`;
  const engineName=engine==='lanczos'?'Lanczos3':String(engine).startsWith('fsr-')||engine==='fsr'?(engine==='fsr-soft'?'FSR1 · мягкий':'FSR1'):engine==='mobile'?'Мобильный GPU':engine==='fsrcnn'?'FSRCNN':({'anime4k-l':'Anime4K L','anime4k-vl':'Anime4K VL','anime4k-ul':'Anime4K UL'}[engine]||'Anime4K');
  function retryGpu(value=prefs.upscaler){setGpuAttempt(n=>n+1);changePrefs({gpu:value!=='off',...(value!=='off'?{upscaler:value}:{})});}
  const [opening,setOpening]=useState(()=>getOpening(item,libraryId));
  const [openingDraft,setOpeningDraft]=useState(null);
  const [introOffset,setIntroOffset]=useState(()=>{try{return Number(localStorage.getItem(openerKey(libraryId,item.id)+':offset'))||0;}catch{return 0;}});
  useEffect(()=>{try{setIntroOffset(Number(localStorage.getItem(openerKey(libraryId,item.id)+':offset'))||0);}catch{setIntroOffset(0);}},[item.id,libraryId]);
  const shifted=episodeMusic.intervals.map(v=>({...v,start:Math.max(0,v.start+introOffset),end:Math.min(duration,v.end+introOffset)})).filter(v=>v.end>v.start);
  const sourceIntervals=(onlineControls?.sourceIntervals||[]).filter(v=>['op','ed'].includes(v.type)&&Number.isFinite(v.start)&&Number.isFinite(v.end)&&v.start>=0&&v.end>v.start&&v.end<=duration+1);
  const effectiveOpening=opening||sourceIntervals.find(v=>v.type==='op')||shifted.find(v=>v.type==='op');
  const ending=openingBounds(item.ending)||sourceIntervals.find(v=>v.type==='ed')||shifted.find(v=>v.type==='ed');
  const activeTheme=effectiveOpening&&time>=effectiveOpening.start&&time<effectiveOpening.end?'OP':ending&&time>=ending.start&&time<ending.end?'ED':null;
  const songCandidates=episodeMusic.tracks.filter(t=>t.type===activeTheme),currentSong=songCandidates.length===1?songCandidates[0]:null;
  const lastStored=useRef(-1),resumeApplied=useRef(false),subtitleInput=useRef(null);
  const library=useMemo(()=>buildPlaybackLibrary(item,catalog),[item.id,catalog]);
  const seasons=library.seasons;
  const episodes=seasons.flatMap(season=>season.episodes);
  const season=seasons.find(part=>part.episodes.some(ep=>ep.variants.some(v=>v.item.id===item.id)));
  const [browsedSeasonId,setBrowsedSeasonId]=useState('');
  const shelfSeason=seasons.find(s=>s.id===browsedSeasonId)||season;
  const episode=season?.episodes.find(ep=>ep.variants.some(v=>v.item.id===item.id));
  const characterContext=useMemo(()=>pauseContext({...item,episode:episode?.number||item.episode},catalog,library.title,season?.name),[item,catalog,library.title,season?.name,episode?.number]);
  const index=episodes.indexOf(episode);
  const next=episodes[index+1]?.variants[0]?.item;
  const previous=episodes[index-1]?.variants[0]?.item;
  function revealControls(){
    const now=performance.now();if(controlsVisible&&now-lastReveal.current<150)return;lastReveal.current=now;
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
  function openPanel(value){if(value==='episodes'&&onlineControls?.externalEpisodeList&&!onlineControls?.episodeBrowser){stageRef.current?.closest('.online-watch')?.querySelector('.watch-episode-grid')?.scrollIntoView({behavior:reducedMotion?'instant':'smooth',block:'center'});setPanel('watch');revealControls();return;}setPanel(value);revealControls();}
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
  },[prefs.speed,prefs.volume,source]);
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
      if(!subtitle.startsWith('hls:'))track.mode=(subtitle===(track.label==='Загруженные субтитры'?'local':'native:'+index))?'hidden':'disabled';
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
        const start=engine==='fsr'||engine==='fsr-soft'?startFsr:engine==='mobile'||engine==='lanczos'?startMobileGpu:engine==='fsrcnn'?startNeuralUpscaler:(await import('./anime4k-runtime.js')).startAnime4K;
        stop=await start(videoRef.current,canvas,{
          mode:prefs.neuralMode,profile:engine,deviceProfile,
          onStats:stats=>{const now=performance.now();if(!disposed&&now-statsClock.current>=1000){statsClock.current=now;setNeuralStats(stats);}},
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
    if(Math.abs(video.currentTime-clockDrawn.current)>=.5||video.paused){clockDrawn.current=video.currentTime;setTime(video.currentTime);}snapshot.current={time:video.currentTime,duration:video.duration};
    if(onPreview&&previewCaptured.current!==item.id&&video.currentTime>=1){const image=captureEpisodePreview(video);if(image){previewCaptured.current=item.id;onPreview(item.episode,image);}}
    const ranges=video.buffered;
    setBuffered(contiguousBufferEnd(ranges,video.currentTime));
    if(prefs.autoSkip){const skip=[effectiveOpening,ending].find(v=>v&&video.currentTime>=v.start&&video.currentTime<v.end-.2);if(skip)seek(skip.end);}
    if(Math.abs(video.currentTime-lastStored.current)>=5){
      lastStored.current=video.currentTime;
      writeProgress(userId,libraryId,item,video.currentTime,video.duration);
    }
  }
  function loaded(){
    const video=videoRef.current;if(!video)return;
    setDuration(Number.isFinite(video.duration)?video.duration:0);
    snapshot.current={time:video.currentTime,duration:video.duration};
    video.playbackRate=Number(prefs.speed)||1;video.volume=Math.max(0,Math.min(1,Number(prefs.volume)));
    if(!source||!Number.isFinite(video.duration)||video.duration<=0)return;
    if(!resumeApplied.current){
      resumeApplied.current=true;
      const shared=sessionStorage.getItem('mediavault_pending_time_'+item.id);
      if(shared!==null){sessionStorage.removeItem('mediavault_pending_time_'+item.id);const point=Number(shared);if(Number.isFinite(point))seek(point);}
      else{const point=readResume(keyFor(userId,libraryId,item.id));if(point>0&&point<video.duration-12)seek(point);}
    }
    snapshot.current={time:video.currentTime,duration:video.duration};
  }
  function choose(nextItem,keepTime=false){
    if(!nextItem||nextItem.id===item.id)return;
    if(keepTime){try{sessionStorage.setItem('mediavault_pending_time_'+nextItem.id,String(videoRef.current?.currentTime||0));}catch{}}
    onSelectItem?.(nextItem);
  }
  function nextEpisode(){choose(next);}
  function ended(){
    snapshot.current={time:0,duration:videoRef.current?.duration};setPlaying(false);writeProgress(userId,libraryId,item,0,videoRef.current?.duration);
    if(prefs.autoNext)nextEpisode();
  }
  function toggle(){const video=videoRef.current;if(!video)return;
    if(video.paused){openPanel('watch');video.play().catch(onError);}else video.pause();
  }
  function fullscreen(){
    const stage=stageRef.current,video=videoRef.current;
    const animate=()=>{if(!reducedMotion)stage?.querySelector('.mv-player-screen')?.animate([{opacity:.85,transform:'scale(.98)'},{opacity:1,transform:'scale(1)'}],{duration:240,easing:'cubic-bezier(.2,.8,.2,1)'});};
    if(document.fullscreenElement){document.exitFullscreen?.().then(animate).catch(()=>{});return;}
    if(stage?.requestFullscreen)stage.requestFullscreen().then(animate).catch(()=>video?.webkitEnterFullscreen?.());
    else video?.webkitEnterFullscreen?.();
  }
  function switchAudio(index){
    if(streaming.audio.length){streaming.setAudio(index);setActiveAudio(index);return;}const list=videoRef.current?.audioTracks;if(!list)return;
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
  keyboardHandler.current=event=>{
      if(event.key==='Escape'&&panel==='watch'&&theater){event.preventDefault();event.stopImmediatePropagation();setTheater(false);return;}
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
  useEffect(()=>{const handler=e=>keyboardHandler.current?.(e);window.addEventListener('keydown',handler,true);return()=>window.removeEventListener('keydown',handler,true);},[]);
  const gestures=usePlayerGestures({videoRef,volume:muted?0:prefs.volume,setVolume:value=>{setMuted(false);changePrefs({volume:value});},openPanel,toggle,reveal:revealControls});
  const actions=usePlayerActions({videoRef,canvasRef,item,gpuActive});
  const previewTime=gestures.feedback?.type==='seek'?gestures.feedback.value:time;
  const effectiveVolume=muted?0:Number(prefs.volume);
  const pip=async()=>{try{const v=videoRef.current;if(document.pictureInPictureElement)await document.exitPictureInPicture();else if(v?.requestPictureInPicture)await v.requestPictureInPicture();else if(v?.webkitSetPresentationMode)v.webkitSetPresentationMode(v.webkitPresentationMode==='picture-in-picture'?'inline':'picture-in-picture');}catch{}};
  const seekable=duration>0&&Number.isFinite(duration);
  const skipRange=[effectiveOpening,ending].find(v=>v&&time>=v.start&&time<v.end);
  const canSkip=!!skipRange;
  const hiddenControls=playing&&panel==='watch'&&!musicOpen&&!controlsVisible;
  const progress=seekable?Math.min(100,previewTime/duration*100):0;
  return {
    timeline,canvasRef,stageRef,railRef,videoRef,health,streaming,reducedMotion,prefs,hoverSeek,setHoverSeek,seekTimer,time,duration,buffered,setBuffered,playing,setPlaying,muted,setMuted,audioError,setAudioError,external,previewCaptured,isFullscreen,isPip,panel,musicOpen,setMusicOpen,theater,settingsTab,setSettingsTab,localTrack,settingsButton,musicButton,cinema,musicIdentity,episodeMusic,dismissedCue,setDismissedCue,settingsOpen,scene,subtitle,setSubtitle,availableTracks,audioTracks,activeAudio,subtitleText,gpuActive,gpuWarning,neuralStats,gpuAttempt,setGpuAttempt,mobileDevice,deviceProfile,engine,colors,color,colorFilter,engineName,retryGpu,opening,openingDraft,setOpeningDraft,introOffset,setIntroOffset,effectiveOpening,ending,activeTheme,currentSong,subtitleInput,library,seasons,episodes,season,shelfSeason,setBrowsedSeasonId,episode,characterContext,index,revealControls,scrollEpisodes,openPanel,changePrefs,seek,onTime,loaded,choose,ended,toggle,fullscreen,switchAudio,attachSubtitle,setIntro,markEnd,gestures,actions,previewTime,effectiveVolume,pip,seekable,skipRange,canSkip,hiddenControls,progress,item,source,nextEpisode,previous,setTheater
  };
}
