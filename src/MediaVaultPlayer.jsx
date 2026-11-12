import {useHostRoom} from './watch-room.js';
import {ostTrack} from './use-episode-ost.js';
const clockOf=v=>{v=Math.max(0,Math.floor(v||0));return Math.floor(v/60)+':'+String(v%60).padStart(2,'0');};
import RoomConversation from './RoomConversation.jsx';
import {RoomPanel,roomSummary,roomMembers} from './WatchRoomControls.jsx';
import RoomOverlay from './RoomOverlay.jsx';
import './watch-room.css';
import './interface-refinement.css';
import {Music2,Pause,Play,Subtitles,PictureInPicture2,Maximize2,Minimize2,Sparkles,X,Sun,Share2,Camera,Video,ChevronsUp,ChevronsDown,Users,RotateCcw,RotateCw,Captions,Download,RectangleHorizontal,SlidersHorizontal,ChevronsRight,ChevronDown,SkipForward,LayoutGrid,Check,Square} from 'lucide-react';
import './player-redesign.css';
import './player.css';
import './player-refinement.css';
import './player-comfort.css';
import './player-next.css';
import PlayerPopover from './PlayerPopover.jsx';
import {AnimatePresence,motion} from 'motion/react';
import {readProgress,writeProgress} from './playback-progress.js';
import PauseFrameEffects from './PauseFrameEffects.jsx';
import TimelinePreview from './TimelinePreview.jsx';
import {playMusic,musicSnapshot,subscribeMusic} from './music-player.js';
import PlayerSongCue from './PlayerSongCue.jsx';
import PlayerSettings,{themedControls} from './PlayerSettings.jsx';
import {Row,Switch,Choices,Segmented,Slider,Note,Group} from './player-sheet-controls.jsx';
import {diagnoseVideoFailure} from './playback-diagnostics.js';
import {captureEpisodePreview} from './episode-preview-cache.js';
import {contiguousBufferEnd} from './watch-quality.js';
import {useEffect,useImperativeHandle,useLayoutEffect,useRef,useState,useSyncExternalStore} from 'react';
import {isShortEpisodeClip} from './watch-session.js';
import usePlayerController from './player-controller.js';
import {clock,keyFor,readResume,openerKey} from './player-runtime.js';
import {PlayerContext,usePlayerSession,usePlayerExtensions,usePlayerMediaSession} from './player-session.js';
import PlayerExtensionSlot from './PlayerExtensionSlot.jsx';
import {createPortal} from 'react-dom';
import {UPSCALERS,upscalerById,autoUpscaler,migrateUpscaler} from './upscaler-catalog.js';
import {SourceBadges} from './source-badges.jsx';
import {readSubtitleTrack,subtitleFileName,subtitleMime} from './subtitle-export.js';
import {saveBlob} from './use-player-actions.js';
import {useColorGrade,readCustomPresets,writeCustomPresets} from './color-grade.js';
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
function plural(n,one,few,many){const a=n%10,b=n%100;return a===1&&b!==11?one:a>=2&&a<=4&&(b<12||b>14)?few:many;}
const cleanTitle=value=>String(value||'').replace(/\.(mp4|mkv|webm|mov|m4v|avi)$/i,'');
// name, saturation, contrast, brightness, temperature, tint
const COLOR_PRESETS=[['Оригинал',1,1,1,0,0],['Сочнее',1.18,1.06,1.01,0,0],['Мягче',1.06,.97,1.03,0,0],['Кино',.92,1.1,.98,.12,0],['Ярко',1.12,1.04,1.06,0,0],['Тепло',1.05,1.02,1.01,.35,.05],['Холодно',1.02,1.04,1,-.35,0],['Ночь',.95,1.08,.9,-.15,0],['Пастель',.86,.92,1.06,.08,.04],['Ч/б',0,1.1,1,0,0]];
const sameColor=(colors,p)=>(colors.saturation??1)===p[1]&&(colors.contrast??1)===p[2]&&(colors.brightness??1)===p[3]&&(colors.temperature??0)===p[4]&&(colors.tint??0)===p[5];

// The one loud element: a map of the episode (opening, ending) filled with the scene colour.
function Timeline({timeline,duration,time,buffered,seekable,disabled,source,type,segments,feedback,onSeek,hoverSeek,setHoverSeek,seekTimer}){
  const [hover,setHover]=useState(null);
  const progress=seekable?Math.min(100,time/duration*100):0;
  const loaded=Math.max(progress,seekable?buffered/duration*100:0);
  function seekAtPointer(event){
    const node=event.currentTarget;if(node.disabled||!seekable)return;
    const bounds=node.getBoundingClientRect();event.preventDefault();event.stopPropagation();
    onSeek(Math.max(0,Math.min(1,(event.clientX-bounds.left)/bounds.width))*duration);
  }
  function move(event){
    if(!seekable)return;
    const r=event.currentTarget.getBoundingClientRect(),fraction=Math.max(0,Math.min(1,(event.clientX-r.left)/r.width)),point=fraction*duration;
    setHover({time:point,left:fraction*100,label:segments.find(s=>point>=s.start&&point<s.end)?.label});
    clearTimeout(seekTimer.current);
    if(!source||navigator.connection?.saveData)return;
    const value={time:point,left:Math.max(12,Math.min(88,fraction*100))};
    seekTimer.current=setTimeout(()=>setHoverSeek(value),200);
  }
  function leave(){clearTimeout(seekTimer.current);setHover(null);setHoverSeek(null);}
  const bubble=feedback?.type==='seek'?{left:progress,time,delta:feedback.delta}:hover;
  return <div className={'mvx-timeline'+(hover?' is-hovered':'')} onPointerMove={move} onPointerLeave={leave} onPointerCancel={leave}>
    {hoverSeek&&<TimelinePreview source={source} type={type} point={hoverSeek.time} left={hoverSeek.left}/>}
    {bubble&&<output className="mvx-timeline-bubble" style={{left:Math.max(4,Math.min(96,bubble.left))+'%'}}>
      {bubble.label&&<span>{bubble.label}</span>}{clock(bubble.time)}
      {Number.isFinite(bubble.delta)&&<small>{bubble.delta>=0?'+':'−'}{Math.abs(Math.round(bubble.delta))} сек.</small>}
    </output>}
    <div className="mvx-track" aria-hidden="true">
      <i className="mvx-track-loaded" style={{width:loaded+'%'}}/>
      {seekable&&segments.map(s=><i key={s.label} className="mvx-track-segment" title={s.label+', '+clock(s.start)+'–'+clock(s.end)} style={{left:s.start/duration*100+'%',width:(s.end-s.start)/duration*100+'%'}}><b>{s.label}</b></i>)}
      <i className="mvx-track-played" style={{width:progress+'%'}}/>
    </div>
    <i className="mvx-thumb" style={{left:progress+'%'}} aria-hidden="true"/>
    <input ref={timeline} aria-label="Перемотка видео" type="range" min="0" max={seekable?duration:1} step="0.1"
      value={Math.min(time,seekable?duration:1)} disabled={!seekable||disabled}
      onPointerDown={event=>{if(event.button===0&&!event.currentTarget.disabled){event.currentTarget.setPointerCapture(event.pointerId);seekAtPointer(event);}}}
      onPointerMove={event=>{if(event.currentTarget.hasPointerCapture(event.pointerId))seekAtPointer(event);}}
      onPointerUp={event=>{if(event.currentTarget.hasPointerCapture(event.pointerId)){seekAtPointer(event);event.currentTarget.releasePointerCapture(event.pointerId);}}}
      onChange={event=>onSeek(Number(event.target.value))}/>
  </div>;
}

// Dub switch kept in the control bar: the most frequent anime-specific choice.
function DubMenu({label,options,value,onPick,current:currentSource}){
  const [open,setOpen]=useState(false),root=useRef(null);
  const current=options.find(o=>String(o.value)===String(value));
  useEffect(()=>{
    if(!open)return;
    const away=event=>{if(!root.current?.contains(event.target))setOpen(false);};
    document.addEventListener('pointerdown',away,true);
    root.current?.querySelector('[aria-checked="true"]')?.focus();
    return()=>document.removeEventListener('pointerdown',away,true);
  },[open]);
  return <div className="mvx-dub" ref={root} onKeyDownCapture={event=>{if(event.key==='Escape'&&open){event.preventDefault();event.stopPropagation();setOpen(false);root.current?.querySelector('.mvx-dub-button')?.focus();}}}>
    <button type="button" className="mvx-dub-button" aria-haspopup="true" aria-expanded={open} aria-label={label+': '+(current?.label||'')} onClick={()=>setOpen(v=>!v)}>
      <span>{current?.label||label}</span>{currentSource&&<SourceBadges sources={[currentSource]}/>}<ChevronDown size={14} aria-hidden="true"/>
    </button>
    {open&&<div className="mvx-dub-menu mvx-scroll" role="radiogroup" aria-label={label}>
      {options.map(o=><button type="button" key={o.value} role="radio" aria-checked={String(o.value)===String(value)} onClick={()=>{setOpen(false);onPick(o.value);}}>
        <span>{o.label}<SourceBadges sources={o.sources}/></span>{String(o.value)===String(value)&&<Check size={15} aria-hidden="true"/>}
      </button>)}
    </div>}
  </div>;
}

export default function MediaVaultPlayer({item,source,catalog,libraryId,userId,mediaRef,onSelectItem,onError,busy,renderEpisodeArtwork,onPlaybackChange,onPlaybackRecovered,minimumDuration=0,onRejectedSource,onlineControls,onPreview,onClose,autoPlay=false,characterService,extensions=[],apiRef,roomControl,onDownload}){
  const controller=usePlayerController({item,source,catalog,libraryId,userId,mediaRef,onSelectItem,onError,busy,renderEpisodeArtwork,onPlaybackChange,onlineControls,onPreview,onClose,autoPlay,characterService,roomControl});
  const {episodeOst,songTheme,timeline,canvasRef,stageRef,railRef,videoRef,health,streaming,prefs,hoverSeek,setHoverSeek,seekTimer,time,duration,buffered,setBuffered,playing,setPlaying,muted,setMuted,audioError,setAudioError,external,previewCaptured,isFullscreen,isPip,panel,musicOpen,setMusicOpen,theater,settingsTab,setSettingsTab,localTrack,settingsButton,musicButton,cinema,musicIdentity,episodeMusic,dismissedCue,setDismissedCue,settingsOpen,scene,subtitle,setSubtitle,availableTracks,audioTracks,activeAudio,subtitleText,gpuActive,gpuWarning,neuralStats,setGpuAttempt,gpuAttempt,deviceProfile,engine,colors,color,colorFilter,engineName,retryGpu,opening,openingDraft,setOpeningDraft,introOffset,setIntroOffset,effectiveOpening,ending,activeTheme,currentSong,subtitleInput,library,seasons,episodes,season,shelfSeason,setBrowsedSeasonId,episode,characterContext,index,revealControls,openPanel,changePrefs,seek,onTime,loaded,choose,ended,toggle,fullscreen,switchAudio,attachSubtitle,setIntro,markEnd,gestures,actions,previewTime,effectiveVolume,pip,seekable,skipRange,canSkip,hiddenControls,progress,localSubtitle}=controller;
  const api=usePlayerSession(controller);
  const room=useHostRoom(api,characterService,item,source,characterContext,!roomControl,onlineControls);
  useImperativeHandle(apiRef,()=>api,[api]);
  usePlayerExtensions(api,extensions,onError);
  usePlayerMediaSession(api);
  const nowPlaying=useSyncExternalStore(subscribeMusic,musicSnapshot);
  const gradeRef=useRef(null),lutInput=useRef(null);
  const [gradeError,setGradeError]=useState(''),[customPresets,setCustomPresets]=useState(readCustomPresets),[presetName,setPresetName]=useState('');
  const grade=useColorGrade({canvasRef:gradeRef,videoRef,upscaledRef:canvasRef,upscaled:gpuActive,colors,onError:e=>setGradeError(e.message)});
  // Dev-only preview of the fullscreen room overlay (embedded browsers may block fullscreen).
  const previewOverlay=import.meta.env.DEV&&new URLSearchParams(location.search).has('room-overlay');
  const selectorSeasons=onlineControls?.seasonOptions||seasons;
  // On a title page the room chat takes the right column's top (ratings slide
  // below it) so the player keeps its width while a room is live.
  // The retained player is portalled into document.body, so the title layout is
  // found through its anchor on the page; it is re-checked when the player turns
  // into a popup, theater mode hides the column, the route or the width changes.
  const [chatSlot,setChatSlot]=useState(null),roomLive=!!room.info;
  useEffect(()=>{
    if(!roomLive){setChatSlot(null);return;}
    let slot=null,sidebar=null,frame=0,watched=null;
    const observer=new MutationObserver(()=>schedule());
    const release=()=>{
      const old=slot;old?.classList.add('is-leaving');setTimeout(()=>old?.remove(),320);
      sidebar?.classList.remove('has-room-chat');slot=sidebar=null;setChatSlot(null);
    };
    const place=()=>{
      frame=0;
      const stage=stageRef.current,host=stage?.closest('.retained-media-host');
      const anchor=host?document.querySelector('[data-retained-slot="'+CSS.escape(host.dataset.session||'')+'"]'):stage;
      const layout=host&&host.dataset.mode!=='attached'?null:anchor?.closest('.mv-title-layout');
      if(watched!==layout){observer.disconnect();watched=layout;if(host)observer.observe(host,{attributes:true,attributeFilter:['data-mode']});if(layout)observer.observe(layout,{attributes:true,attributeFilter:['class']});}
      const next=layout?.querySelector('.title-sidebar');
      if(!next||getComputedStyle(next).display==='none'){if(slot)release();return;}
      if(slot&&sidebar===next&&slot.isConnected)return;
      if(slot)release();
      slot=document.createElement('div');slot.className='room-chat-slot';next.prepend(slot);next.classList.add('has-room-chat');sidebar=next;setChatSlot(slot);
    };
    const schedule=()=>{if(!frame)frame=requestAnimationFrame(place);};
    place();
    const late=setTimeout(schedule,400);
    addEventListener('hashchange',schedule);addEventListener('resize',schedule);
    return()=>{clearTimeout(late);cancelAnimationFrame(frame);observer.disconnect();removeEventListener('hashchange',schedule);removeEventListener('resize',schedule);slot?.remove();sidebar?.classList.remove('has-room-chat');setChatSlot(null);};
  },[roomLive]);
  const toggleCaptions=controller.toggleCaptions;
  // Online sessions are capability URLs: the server remuxes the playing
  // quality into one MP4 (no re-encode). Rooms relay someone else's stream.
  const onlineMatch=/^(https?:\/\/[^/]+)\/online\/([\w-]{20,80})\/([\w-]{10,40})$/.exec(source||'');
  // A blob HLS master (Collaps in the viewer's browser) is a playlist, not a file: it saves through onDownload.
  const playlistBlob=item?.onlineType==='hls'&&String(source||'').startsWith('blob:');
  const canDownload=!roomControl&&!room.info&&(!!onlineMatch||!!onDownload||String(source||'').startsWith('blob:')&&!playlistBlob);
  const [downloadStatus,setDownloadStatus]=useState('');
  const [subtitleSaving,setSubtitleSaving]=useState(''),[subtitleError,setSubtitleError]=useState('');
  // A caption source picked from another version is switched on once its track arrives.
  const captionPick=useRef(false);
  useEffect(()=>{
    if(!captionPick.current)return;
    const names=(onlineControls?.externalCaptions||[]).map(t=>t.name),track=availableTracks.find(t=>t.element&&names.includes(t.name));
    if(track){captionPick.current=false;setSubtitle(track.id);}
  },[availableTracks,onlineControls?.externalCaptions]);
  useEffect(()=>setSubtitleError(''),[source]);
  const [downloadOpen,setDownloadOpen]=useState(false),downloadButton=useRef(null),roomButton=useRef(null);
  const title=cleanTitle(library.title);
  const defaultName=[title,episode?.label].filter(Boolean).join(' · ')||'MediaVault';
  const downloadHeights=[...new Set([...streaming.levels.map(l=>l.height||0),...(onlineControls?.qualities||[]).map(Number)])].filter(h=>h>0).sort((a,b)=>b-a);
  const [downloadHeight,setDownloadHeight]=useState(0),[downloadName,setDownloadName]=useState('');
  useEffect(()=>{if(downloadOpen){setDownloadName(defaultName);setDownloadHeight(streaming.levels.find(l=>l.index===streaming.level)?.height||downloadHeights[0]||0);}},[downloadOpen]);
  function download(chosen,label){
    const name=(label||'').trim()||defaultName;
    const current=streaming.levels.find(l=>l.index===streaming.level)?.height,best=Math.max(0,...streaming.levels.map(l=>l.height||0));
    const requested=onlineControls?.quality&&onlineControls.quality!=='best'?Number(onlineControls.quality):0;
    if(onDownload){setDownloadStatus('Готовим файл…');Promise.resolve(onDownload(chosen||current||requested||0,name,setDownloadStatus)).then(()=>setDownloadStatus('')).catch(error=>setDownloadStatus(error.name==='AbortError'?'':error.message));return;}
    const href=onlineMatch?onlineMatch[1]+'/online/'+onlineMatch[2]+'/'+onlineMatch[3]+'/download?'+new URLSearchParams({height:String(chosen||current||requested||best||0),name}):source;
    const link=document.createElement('a');link.href=href;link.download=name+'.mp4';link.rel='noopener';document.body.append(link);link.click();link.remove();
  }
  // Switching a dub keeps this player mounted (and fullscreen): the last frame stays
  // on screen until the other version's video can play, then playback continues.
  const [bridge,setBridge]=useState(''),resumeAfterSwitch=useRef(false);
  function switchVariant(next){
    if(!next||next.id===item.id)return;
    const video=videoRef.current;
    resumeAfterSwitch.current=!!video&&!video.paused;
    try{if(video?.videoWidth){const c=document.createElement('canvas');c.width=video.videoWidth;c.height=video.videoHeight;c.getContext('2d').drawImage(video,0,0);setBridge(c.toDataURL('image/jpeg',.85));}}catch{setBridge('');}
    choose(next,true);
  }
  function bridgeDone(){if(!bridge&&!resumeAfterSwitch.current)return;setBridge('');if(resumeAfterSwitch.current){resumeAfterSwitch.current=false;videoRef.current?.play().catch(()=>{});}}
  useEffect(()=>{if(!bridge)return;const v=videoRef.current,safety=setTimeout(bridgeDone,8000);const ready=setTimeout(()=>{if(v&&v.readyState>=3&&!v.seeking)bridgeDone();},60);return()=>{clearTimeout(safety);clearTimeout(ready);};},[source,bridge]);
  // An online voice switch hands the same episode to another stream. Before
  // hls.js detaches the old one, its last frame becomes the bridge, so the
  // picture holds until the new voice can play from the same second.
  const bridgedSource=useRef(source);
  useLayoutEffect(()=>{
    const previous=bridgedSource.current;bridgedSource.current=source;
    if(!previous||previous===source||!onlineControls?.continuing)return;
    const video=videoRef.current;
    try{if(video?.videoWidth&&video.readyState>=2){const c=document.createElement('canvas');c.width=video.videoWidth;c.height=video.videoHeight;c.getContext('2d').drawImage(video,0,0);setBridge(c.toDataURL('image/jpeg',.85));}}catch{}
  },[source]);
  // Another dub inside the playing stream (Collaps): only the audio track changes.
  const audioName=onlineControls?.audioName||'';
  useEffect(()=>{
    if(!audioName||!streaming.audio.length)return;
    const index=streaming.audio.findIndex(track=>track.name===audioName);
    if(index>=0&&index!==streaming.audioTrack())switchAudio(index);
  },[audioName,streaming.audio]);
  const voiceSwitch=onlineControls?.voiceSwitch?.phase?onlineControls.voiceSwitch:null;
  function openSettings(page='watch'){setSettingsTab(page);setMusicOpen(false);setDownloadOpen(false);openPanel('settings');}

  // ---- Values for the settings sheet ----
  const currentVariant=episode?.variants.find(v=>v.item.id===item.id);
  const variantQuality=v=>v.item.quality||v.item.resolution||(v.item.id===item.id&&videoRef.current?.videoHeight?videoRef.current.videoHeight+'p':'Исходное');
  let quality;
  if(!streaming.levels.length&&onlineControls?.qualities?.length)quality={value:onlineControls.quality,options:[{value:'best',label:'Лучшее, автоматически'},...onlineControls.qualities.map(q=>({value:q,label:q+'p'}))],pick:v=>onlineControls.onQuality(v)};
  else if(streaming.levels.length)quality={value:streaming.level,options:[{value:-1,label:'Лучшее, автоматически'},...streaming.levels.filter((l,i,all)=>all.findIndex(x=>x.height===l.height)===i).map(l=>({value:l.index,label:l.height+'p'})),...(onlineControls?.qualities||[]).filter(q=>!streaming.levels.some(l=>l.height===q)).map(q=>({value:'source:'+q,label:q+'p',hint:'Другой поток источника'}))],
    pick:value=>{value=String(value);if(value.startsWith('source:'))onlineControls.onQuality(value.slice(7));else if(value==='-1'&&onlineControls?.quality&&onlineControls.quality!=='best'&&(streaming.levels.length<2||(onlineControls.qualities||[]).some(q=>q>Math.max(...streaming.levels.map(l=>l.height||0)))))onlineControls.onQuality('best');else streaming.setLevel(Number(value));}};
  else{const same=episode?.variants.filter(v=>v.item.id===item.id||v.label===currentVariant?.label)||[];quality={value:item.id,options:same.map(v=>({value:v.item.id,label:variantQuality(v)})),pick:value=>choose(episode.variants.find(v=>v.item.id===value)?.item,true)};}
  const qualityLabel=quality.options.find(o=>String(o.value)===String(quality.value))?.label||'Исходное';
  const audioList=streaming.audio.length?streaming.audio:audioTracks;
  // «Скачать» in each track row: a file track is saved as it is (SRT, VTT,
  // ASS), a stream track is assembled into one VTT file.
  async function saveSubtitle(value,name){
    if(subtitleSaving)return;
    setSubtitleSaving(value);setSubtitleError('');
    try{
      const {text,format}=await readSubtitleTrack(value,{video:videoRef.current,hlsUrl:streaming.subtitleUrl,localFile:value==='local'?localSubtitle?.current:null});
      saveBlob(new Blob([text],{type:subtitleMime(format)}),subtitleFileName([title,episode?.label,name],format));
    }catch(error){setSubtitleError(error.message||'Не удалось скачать субтитры.');}
    finally{setSubtitleSaving('');}
  }
  const subtitleAction=(value,name)=>({label:subtitleSaving===value?'Скачиваем…':'Скачать',ariaLabel:'Скачать субтитры: '+name,icon:<Download size={15} aria-hidden="true"/>,busy:subtitleSaving===value,disabled:!!subtitleSaving,onClick:()=>saveSubtitle(value,name)});
  const subtitleOptions=[{value:'off',label:'Выключены'},...streaming.subtitles.map(t=>({value:'hls:'+t.index,label:t.name,action:subtitleAction('hls:'+t.index,t.name)})),...availableTracks.filter(t=>t.element||!streaming.subtitles.some(h=>h.name===t.name)).map(t=>({value:t.id,label:t.name,action:subtitleAction(t.id,t.name)}))];
  const subtitleLabel=subtitleOptions.find(o=>o.value===subtitle)?.label||'Выключены';
  // Dub in the bar: online voices (separate audio) or local file variants.
  const dub=onlineControls?.voices?.length>1?{label:'Озвучка',value:onlineControls.voiceId||'',options:onlineControls.voices.map(v=>({value:v.id,label:v.name,sources:v.sources})),pick:id=>onlineControls.onVoice(id),current:onlineControls.currentSource}
    :episode?.variants.length>1?{label:'Озвучка',value:item.id,options:episode.variants.map(v=>({value:v.item.id,label:v.label})),pick:id=>switchVariant(episode.variants.find(v=>v.item.id===id)?.item)}:null;
  const engineValue=prefs.gpu?migrateUpscaler(prefs.upscaler||'auto'):'off';
  const engineLabel=(prefs.gpu?(engineValue==='auto'?'Авто, '+(upscalerById(autoUpscaler(deviceProfile))?.label||''):upscalerById(engineValue)?.label||'Выключено'):'Выключено')+(colors.sharpen?', резкость':'')+(colors.deband?', без полос':'');
  const allPresets=[...COLOR_PRESETS,...customPresets.map(p=>[p.name,p.saturation,p.contrast,p.brightness,p.temperature,p.tint,true])];
  const colorPreset=(allPresets.find(p=>sameColor(colors,p))?.[0]||'Свой')+(grade.lut?', '+grade.lut.title:'');
  const applyPreset=p=>color({saturation:p[1],contrast:p[2],brightness:p[3],temperature:p[4],tint:p[5]});
  function savePreset(){const name=presetName.trim().slice(0,24);if(!name)return;const value={name,saturation:colors.saturation??1,contrast:colors.contrast??1,brightness:colors.brightness??1,temperature:colors.temperature??0,tint:colors.tint??0};setCustomPresets(writeCustomPresets([...customPresets.filter(p=>p.name!==name),value]));setPresetName('');}
  async function loadLut(event){const file=event.target.files?.[0];event.target.value='';if(!file)return;setGradeError('');try{if(file.size>12*1024*1024)throw Error('Файл LUT должен быть меньше 12 МБ.');await grade.load(file);}catch(e){setGradeError(e.message);}}
  const depthLabel=!prefs.depthShadow?'Выключены':(prefs.depthMode||'cinematic')==='shadow'?'Тень по рельефу':'Объём и параллакс';
  const segments=[effectiveOpening&&{start:effectiveOpening.start,end:effectiveOpening.end,label:'Опенинг'},ending&&{start:ending.start,end:ending.end,label:'Эндинг'}].filter(Boolean);
  const timingStatus=onlineControls?.sourceIntervals?.length?'Разметка '+onlineControls.sourceIntervals[0].source+' для этого видео.':episodeMusic.timingState==='loading'?'Ищем разметку AniSkip.':episodeMusic.timingState==='ready'?'Разметка AniSkip найдена.'+(episodeMusic.intervals.some(v=>v.needsReview)?' У релиза другая длительность, проверь начало.':''):episodeMusic.timingMessage||'Разметки нет. Опенинг можно отметить вручную.';
  const showSongCue=!!currentSong&&dismissedCue!==currentSong.id&&panel==='watch';
  const hasEpisodes=episodes.length>1||!!onlineControls?.episodeBrowser;
  const browsingSeasonId=onlineControls?.browseSeasonId||shelfSeason?.id||'';
  const seasonEpisodes=shelfSeason?.episodes||[];
  const episodeNumber=season?.episodes.indexOf(episode)+1;
  const resumePoint=readResume(keyFor(userId,libraryId,item.id));
  const picker=(label,value,options,pick)=>close=><Choices label={label} value={value} options={options} onPick={v=>{pick(v);close();}}/>;
  const voiceItem=episode?.variants.length>1&&{id:'voice',label:'Озвучка',value:currentVariant?.label,content:picker('Озвучка',item.id,episode.variants.map(v=>({value:v.item.id,label:v.label})),id=>switchVariant(episode.variants.find(v=>v.item.id===id)?.item))};
  const trackItem=onlineControls?.voices?.length>0&&{id:'track',label:'Озвучка',value:onlineControls.voices.find(v=>v.id===onlineControls.voiceId)?.name,content:close=><>
      <Choices label="Озвучка" value={onlineControls.voiceId||''} options={onlineControls.voices.map(v=>({value:v.id,label:v.name,badges:<SourceBadges sources={v.sources}/>}))} onPick={id=>{onlineControls.onVoice(id);if(!onlineControls?.audio)close();}}/>
      {onlineControls?.audio&&<><Note>Видео остаётся в выбранном качестве, звук идёт отдельным потоком и тоже расходует сеть.</Note><Slider label="Сдвиг звука" ariaLabel="Сдвиг звука" min={-30} max={30} step={.1} value={Number(prefs.audioOffset)||0} format={v=>(v>0?'+':'')+v.toFixed(1)+' с'} onChange={v=>changePrefs({audioOffset:v})}/></>}
      {(onlineControls?.trackBusy||onlineControls?.trackError||audioError)&&<Note role="status">{audioError||onlineControls.trackError||'Подключаем дорожку.'}</Note>}
    </>};
  const sections=[
    {id:'play',items:[
      onlineControls?.configuration&&{id:'source',label:'Источник',value:'Озвучка и качество',content:<div className="mvx-source">{themedControls(onlineControls.configuration)}</div>},
      trackItem,voiceItem,
      {id:'quality',label:'Качество',value:qualityLabel,content:close=><><Choices label="Качество" value={quality.value} options={quality.options} onPick={v=>{quality.pick(v);close();}}/>{quality.options.length<2&&<Note>У этой серии одно качество.</Note>}<Note role="status">Загружено вперёд {Math.max(0,Math.round(buffered-time))} с. В автоматическом режиме качество снижается, когда не хватает скорости.</Note></>},
      audioList.length>1&&{id:'audio',label:'Аудиодорожка',value:audioList.find(a=>a.index===activeAudio)?.name,content:picker('Аудиодорожка',activeAudio,audioList.map(a=>({value:a.index,label:a.name})),v=>switchAudio(Number(v)))},
      {id:'speed',label:'Скорость',value:prefs.speed===1?'Обычная':prefs.speed+'×',content:picker('Скорость',prefs.speed,[0.5,0.75,1,1.25,1.5,1.75,2].map(v=>({value:v,label:v===1?'Обычная':v+'×'})),v=>changePrefs({speed:Number(v)}))},
      {id:'captions',label:'Субтитры',value:subtitleLabel,content:<>
        <Choices label="Субтитры" value={subtitle} options={subtitleOptions} onPick={setSubtitle}/>
        {subtitleError&&<p className="mvx-help" role="alert">{subtitleError}</p>}
        {onlineControls?.captionVoices?.length>0&&<><h3 className="mvx-subhead">Из другой версии</h3><Choices label="Источник субтитров" value={onlineControls.subtitleId||''} options={[{value:'',label:'Дорожки текущего видео'},...onlineControls.captionVoices.map(v=>({value:v.id,label:v.name,badges:<SourceBadges sources={v.sources}/>}))]} onPick={id=>{captionPick.current=!!id;onlineControls.onCaptionVoice(id);}}/>
          {onlineControls.captionNotice?<Note role="status">{onlineControls.captionNotice}</Note>:onlineControls.subtitleId&&(onlineControls.trackBusy||onlineControls.trackError)&&<Note role="status">{onlineControls.trackError||'Подключаем субтитры…'}</Note>}</>}
        <button type="button" className="mvx-link" onClick={()=>subtitleInput.current?.click()}><Subtitles size={16}/>Загрузить файл SRT или VTT</button>
        <Slider label="Размер" ariaLabel="Размер субтитров" min={16} max={40} step={2} value={prefs.subSize} format={v=>v+' px'} onChange={v=>changePrefs({subSize:v})}/>
        <Slider label="Отступ снизу" ariaLabel="Отступ субтитров" min={3} max={22} step={1} value={prefs.subOffset} format={v=>v+'%'} onChange={v=>changePrefs({subOffset:v})}/>
      </>}
    ]},
    {id:'auto',items:[
      {id:'autoNext',label:'Следующая серия автоматически',switch:{checked:prefs.autoNext,onChange:v=>changePrefs({autoNext:v})}},
      {id:'autoSkip',label:'Пропускать опенинг и эндинг',switch:{checked:prefs.autoSkip,onChange:v=>changePrefs({autoSkip:v})}},
      {id:'intro',label:'Разметка опенинга',value:effectiveOpening?clock(effectiveOpening.start)+'–'+clock(effectiveOpening.end):'Нет',content:<>
        <Note role="status">{timingStatus}{effectiveOpening?.source?' Источник: '+effectiveOpening.source+'.':''}</Note>
        <button type="button" className="mvx-link" onClick={episodeMusic.retry}>Найти разметку опенинга</button>
        {episodeMusic.intervals.length>0&&<Slider label="Сдвиг меток" ariaLabel="Сдвиг меток опенинга" min={-60} max={60} step={.5} value={introOffset} format={v=>(v>0?'+':'')+v+' с'} onChange={value=>{setIntroOffset(value);try{localStorage.setItem(openerKey(libraryId,item.id)+':offset',String(value));}catch{}}}/>}
        <Note>Отметить вручную: поставь видео на первый кадр опенинга и нажми «Начало», затем на последний и нажми «Конец».</Note>
        <div className="mvx-button-row">
          <button type="button" onClick={()=>setOpeningDraft(time)}>{openingDraft!==null?'Начало '+clock(openingDraft):'Начало'}</button>
          <button type="button" disabled={openingDraft===null} onClick={markEnd}>Конец</button>
        </div>
        <button type="button" className="mvx-link" disabled={!opening} onClick={()=>setIntro(null)}>Удалить свою отметку</button>
      </>}
    ]},
    {id:'look',items:[
      {id:'effects',label:'Эффекты паузы',value:depthLabel,content:<>
        <Switch label="Эффект на паузе" hint="Кадр оживает, когда видео стоит на паузе" checked={prefs.depthShadow} onChange={v=>changePrefs({depthShadow:v})}/>
        <Segmented label="Режим" value={prefs.depthMode||'cinematic'} options={[{value:'cinematic',label:'Объём 2.5D'},{value:'shadow',label:'Тень по рельефу'}]} onPick={v=>changePrefs({depthMode:v,depthShadow:true})}/>
        <Note>{(prefs.depthMode||'cinematic')==='shadow'?'Мягкая тень ползёт по карте глубины кадра и дышит в заданном ритме.':'Карта глубины разделяет кадр на планы, и они сдвигаются за курсором с параллаксом.'}</Note>
        <Slider label="Интенсивность" ariaLabel="Интенсивность тени на паузе" min={.2} max={.95} step={.05} value={prefs.shadowStrength} format={v=>Math.round(v*100)+'%'} onChange={v=>changePrefs({shadowStrength:v})}/>
        {(prefs.depthMode||'cinematic')==='shadow'&&<>
          <Slider label="Цикл дыхания" ariaLabel="Цикл дыхания тени" min={4} max={20} step={1} value={prefs.breathPeriod||10} format={v=>v+' с'} onChange={v=>changePrefs({breathPeriod:v})}/>
          <Slider label="Амплитуда" ariaLabel="Амплитуда тени" min={.08} max={.35} step={.01} value={prefs.breathAmplitude||.22} format={v=>Math.round(v*100)+'%'} onChange={v=>changePrefs({breathAmplitude:v})}/>
        </>}
        <Switch label="Нейросетевая карта глубины" hint="Модель 27 МБ скачивается один раз и работает на устройстве" checked={prefs.depthModelAllowed} onChange={v=>changePrefs({depthModelAllowed:v})}/>
        <Switch label="Узнавать персонажей на паузе" hint="Кадр отправляется в Gemini и AnimeTrace, имена на русском" checked={prefs.characterAuto} onChange={v=>changePrefs({characterAuto:v})}/>
        <Switch label="Подсветка цветом сцены" checked={prefs.ambient} onChange={v=>changePrefs({ambient:v})}/>
        <Switch label="Кинотеатр" hint="Затемняет страницу вокруг плеера" checked={theater} onChange={()=>cinema()}/>
      </>},
      {id:'image',label:'Улучшение',value:engineLabel,content:<>
        {gpuWarning&&<button type="button" className="mvx-link" onClick={()=>retryGpu(prefs.upscaler)}>Повторить на новом GPU-контексте</button>}
        <Choices label="Улучшение выключено" value={engineValue} options={[{value:'off',label:'Выключено',hint:'Исходное видео'}]} onPick={v=>retryGpu(v)}/>
        {[...new Set(UPSCALERS.map(u=>u.group))].map(group=><div key={group} className="mvx-engine-group"><h3 className="mvx-subhead">{group}</h3><Choices label={group} value={engineValue} options={UPSCALERS.filter(u=>u.group===group).map(u=>({value:u.id,label:u.label,hint:u.id==='auto'?'Сейчас: '+(upscalerById(autoUpscaler(deviceProfile))?.label||''):u.hint}))} onPick={v=>retryGpu(v)}/></div>)}
        <h3 className="mvx-subhead">Поверх улучшения</h3>
        <Switch label="Резкость AMD CAS" hint="Умная резкость, почти бесплатная по нагрузке" checked={!!colors.sharpen} onChange={v=>color({sharpen:v?.5:0})}/>
        {!!colors.sharpen&&<Slider label="Сила резкости" ariaLabel="Сила резкости CAS" min={.05} max={1} step={.05} value={colors.sharpen} format={v=>Math.round(v*100)+'%'} onChange={v=>color({sharpen:v})}/>}
        <Switch label="Убрать полосы на градиентах" hint="Для неба, теней и тёмных сцен" checked={!!colors.deband} onChange={v=>color({deband:v})}/>
        {prefs.gpu&&<Segmented label="Нагрузка" value={prefs.neuralMode||'balanced'} options={[{value:'performance',label:'Экономно'},{value:'balanced',label:'Баланс'},{value:'quality',label:'Качество'}]} onPick={v=>changePrefs({neuralMode:v})}/>}
        <Segmented label="Устройство" value={prefs.deviceProfile||'auto'} options={[{value:'auto',label:'Авто'},{value:'phone',label:'Телефон'},{value:'tablet',label:'Планшет'},{value:'desktop',label:'Компьютер'}]} onPick={v=>{setGpuAttempt(n=>n+1);changePrefs({deviceProfile:v});}}/>
        {neuralStats&&prefs.gpu&&<p className="mvx-stats"><strong>{engineName}</strong><span>{neuralStats.width}×{neuralStats.height}</span><span>{neuralStats.fps} кадр/с</span><span>{neuralStats.latency} мс</span>{(neuralStats.adapter||neuralStats.renderer)&&<span>{neuralStats.adapter||neuralStats.renderer}</span>}{neuralStats.software&&<span>Программный рендерер браузера</span>}</p>}
        <Note>Видеокарту выбирают браузер и система, сайт не может включить дискретную принудительно.</Note>
      </>},
      {id:'color',label:'Цвет',value:colorPreset,content:<>
        <div className="mvx-presets" role="radiogroup" aria-label="Пресеты цвета">{allPresets.map(p=><span key={p[0]} className="mvx-preset"><button type="button" role="radio" aria-checked={sameColor(colors,p)} onClick={()=>applyPreset(p)}>{p[0]}</button>{p[6]&&<button type="button" className="mvx-preset-remove" aria-label={'Удалить пресет '+p[0]} onClick={()=>setCustomPresets(writeCustomPresets(customPresets.filter(c=>c.name!==p[0])))}><X size={12}/></button>}</span>)}</div>
        {[['saturation','Насыщенность',0,1.6,.01,1,v=>Math.round(v*100)+'%'],['contrast','Контраст',.7,1.4,.01,1,v=>Math.round(v*100)+'%'],['brightness','Яркость',.7,1.3,.01,1,v=>Math.round(v*100)+'%'],['temperature','Температура',-1,1,.01,0,v=>(v>0?'+':'')+Math.round(v*100)],['tint','Оттенок',-1,1,.01,0,v=>(v>0?'+':'')+Math.round(v*100)]].map(([id,label,min,max,step,base,format])=><Slider key={id} label={label} ariaLabel={label+' изображения'} min={min} max={max} step={step} value={colors[id]??base} format={format} onChange={v=>color({[id]:v})}/>)}
        <form className="mvx-inline-form" onSubmit={e=>{e.preventDefault();savePreset();}}><input aria-label="Название пресета" placeholder="Название своего пресета" value={presetName} maxLength={24} onChange={e=>setPresetName(e.target.value)}/><button type="submit" disabled={!presetName.trim()}>Сохранить</button></form>
        {grade.lut?<>
          <p className="mvx-lut-name"><span>LUT</span><strong>{grade.lut.title}</strong><button type="button" onClick={grade.clear}>Убрать</button></p>
          <Slider label="Сила LUT" ariaLabel="Сила LUT" min={0} max={1} step={.01} value={colors.lutAmount??1} format={v=>Math.round(v*100)+'%'} onChange={v=>color({lutAmount:v})}/>
          {!grade.persisted&&<Note>Файл слишком большой для памяти браузера: LUT работает до перезагрузки страницы.</Note>}
        </>:<button type="button" className="mvx-link" onClick={()=>lutInput.current?.click()}>Загрузить LUT, файл .cube</button>}
        {gradeError&&<p className="mvx-error" role="alert">{gradeError}</p>}
      </>}
    ]},
    !roomControl&&{id:'together',items:[{id:'room',label:'Смотреть вместе',value:room.info?roomSummary(room):'Комната не создана',content:<RoomPanel room={room}/>}]}
  ].filter(Boolean);
  const settingsActions=<div className="mvx-actions">
    {!roomControl&&<button type="button" aria-pressed={!!room.info} onClick={()=>setSettingsTab(settingsTab==='room'?'watch':'room')}><Users size={18}/><span>{room.info?'Комната':'Смотреть вместе'}</span></button>}
    <button type="button" onClick={actions.share}><Share2 size={18}/><span>Поделиться</span></button>
    <button type="button" onClick={actions.screenshot}><Camera size={18}/><span>Сохранить кадр</span></button>
    <button type="button" onClick={actions.clip} disabled={actions.recording} aria-pressed={actions.recording}><Video size={18}/><span>{actions.recording?'Идёт запись':'Записать клип'}</span></button>
    {onClose&&<button type="button" aria-label="Закрыть встроенный просмотр" onClick={onClose}><X size={18}/><span>Закрыть плеер</span></button>}
  </div>;
  const settingsFooter=<>
    <Note>Ссылка откроет эту серию с текущего момента после входа в библиотеку. Клип записывается до 30 секунд.</Note>
    <p className="mvx-shortcuts"><span><kbd>Пробел</kbd>пауза</span><span><kbd>←</kbd><kbd>→</kbd>10 секунд</span><span><kbd>C</kbd>субтитры</span><span><kbd>M</kbd>звук</span><span><kbd>F</kbd>весь экран</span></p>
  </>;
  const onlineCount=room.info?(roomMembers(room).filter(m=>m.online).length||1):0;
  return <PlayerContext.Provider value={api}><div className={'player-room-layout'+(room.info&&!chatSlot?' has-live-room':'')}><div ref={stageRef} className={'mv-player mvx'+(playing?' is-playing':'')+(panel!=='watch'?' is-browsing':'')+(hiddenControls?' controls-hidden':'')+(theater?' is-theater':'')+(!prefs.depthShadow?' depth-shadow-off':'')+(!prefs.ambient?' ambient-off':'')+(panel==='episodes'?' episodes-open':'')+(room.info?' has-room':'')+(previewOverlay?' preview-overlay':'')}
    style={{'--scene-rgb':scene.color,'--video-brightness':gestures.brightness,'--picture-filter':colorFilter}} aria-label="Видеоплеер MediaVault" role="region" tabIndex={0} onPointerDown={event=>{if(!event.target.closest('button,input,select,a,[role="dialog"]'))stageRef.current?.focus({preventScroll:true});}} onPointerMove={revealControls}
    onTouchStart={revealControls} onFocusCapture={revealControls} data-player="mediavault">
    <div className="mv-player-screen mvx-screen">
      <div className="mv-player-ambient mvx-ambient" aria-hidden="true"/>
      <div className="mv-player-stage mvx-stage">
        <video ref={videoRef} className="mv-player-touch-surface mv-player-media" {...gestures.surface} src={streaming.hls?undefined:source||undefined} crossOrigin="anonymous" playsInline preload="auto" muted={muted||!!onlineControls?.audio&&!audioError}
          onLoadedMetadata={event=>{const video=event.currentTarget;if(isShortEpisodeClip(video.duration,minimumDuration)){video.pause();onRejectedSource?.(Error('Источник вернул короткий ролик вместо полной серии.'));return;}loaded();}} onLoadedData={event=>{if(isShortEpisodeClip(event.currentTarget.duration,minimumDuration))return;const image=captureEpisodePreview(videoRef.current);if(onPreview&&image){previewCaptured.current=item.id;onPreview(item.episode,image);}}} onTimeUpdate={onTime} onProgress={()=>{const v=videoRef.current;if(v)setBuffered(contiguousBufferEnd(v.buffered,v.currentTime));}}
          onPlay={()=>{setPlaying(true);onPlaybackChange?.(true);}} onPlaying={()=>onPlaybackRecovered?.()} onPause={()=>{setPlaying(false);onPlaybackChange?.(false);if(videoRef.current?.readyState>=1)writeProgress(userId,libraryId,item,videoRef.current?.currentTime||0,videoRef.current?.duration);}}
          onDurationChange={event=>{if(!isShortEpisodeClip(event.currentTarget.duration,minimumDuration))loaded();}} onEnded={ended} onCanPlay={bridgeDone}
          onError={()=>{if(source)diagnoseVideoFailure({video:videoRef.current,source}).then(message=>onError?.(Error(message))).catch(()=>{});}}
          aria-label="Воспроизвести или приостановить видео">{/* Keyed by source: hls.js empties every subtitle track when it leaves a
            stream, and a <track> never loads its file twice, so each stream gets fresh ones. */}{localTrack&&<track key={source+'|'+localTrack} kind="subtitles" src={localTrack} srcLang="ru" label="Загруженные субтитры"/>}{onlineControls?.externalCaptions?.map(t=><track key={source+'|'+t.url} kind="subtitles" src={t.url} srcLang={t.language||'ru'} label={t.name}/>)}</video>
        {onlineControls?.audio&&<video ref={external.ref} hidden style={{display:'none'}} className="mv-external-audio" src={onlineControls?.audio?.type==='hls'?undefined:onlineControls?.audio?.url} crossOrigin="anonymous" playsInline preload="metadata" aria-hidden="true" onError={()=>{if(onlineControls?.audio)setAudioError('Отдельная озвучка не ответила. Включён исходный звук.');}}/>}
        {bridge&&<img className="mvx-bridge" src={bridge} alt="" aria-hidden="true"/>}
        <canvas key={engine+':'+deviceProfile+':'+prefs.neuralMode+':'+gpuAttempt} ref={canvasRef} className="mv-player-canvas mvx-canvas" aria-hidden="true"/>
        <canvas ref={gradeRef} className="mvx-grade" hidden={!grade.active} aria-hidden="true"/>
        <PauseFrameEffects mode={prefs.depthMode||'cinematic'} characterContext={characterContext} characterService={characterService} userId={userId} key={item.id} videoRef={videoRef} source={source} paused={!playing} enabled={prefs.depthShadow} modelAllowed={prefs.depthModelAllowed} strength={prefs.shadowStrength} breathPeriod={prefs.breathPeriod} breathAmplitude={prefs.breathAmplitude} autoRecognize={prefs.characterAuto} visible={panel==='watch'&&!musicOpen}/>
        {subtitleText&&<div className="mvx-captions" style={{fontSize:prefs.subSize+'px',bottom:(hiddenControls?prefs.subOffset:Math.max(22,prefs.subOffset))+'%'}} aria-live="off">{subtitleText}</div>}
      </div>
      {voiceSwitch?(voiceSwitch.phase==='failed'
        ?<div className="mvx-status is-switch-failed" role="alert"><span>Не удалось включить «{voiceSwitch.name}»{voiceSwitch.message?'. '+voiceSwitch.message:''}</span>
          {voiceSwitch.retry&&<button type="button" className="mvx-pill-light" onClick={voiceSwitch.retry}>Повторить</button>}
          {voiceSwitch.revert&&voiceSwitch.previous&&<button type="button" className="mvx-pill-light" onClick={voiceSwitch.revert}>Вернуть «{voiceSwitch.previous}»</button>}</div>
        :<div className="mvx-status is-switching" role="status"><span className="mvx-spinner"/><span>Загружаем озвучку «{voiceSwitch.name}»</span></div>)
      :health.visible&&<div className="mvx-status" role="status">{health.phase==='blocked'?<button type="button" className="mvx-pill-light" onClick={health.retry}><Play size={15} fill="currentColor"/>Нажми, чтобы воспроизвести</button>:health.phase==='failed'?<><span>Поток задерживается</span><button type="button" className="mvx-pill-light" onClick={onlineControls?.retryStream||health.retry}>Повторить</button></>:<><span className="mvx-spinner"/>{health.phase==='loading'?'Запускаем видео':'Подгружаем видео'}</>}<button type="button" className="mvx-status-dismiss" aria-label="Скрыть статус воспроизведения" onClick={health.dismiss}><X size={14}/></button></div>}

      <AnimatePresence>{gestures.feedback&&gestures.feedback.type!=='seek'&&<motion.output className="mvx-hud" style={{x:'-50%',y:'-50%'}} initial={{opacity:0,scale:.92}} animate={{opacity:1,scale:1}} exit={{opacity:0,scale:.96}} aria-live="off">
        {gestures.feedback.type==='brightness'?<><Sun size={22}/><strong>{Math.round(gestures.feedback.value*100)}%</strong><i style={{'--level':gestures.feedback.value/1.5}}/></>:gestures.feedback.type==='volume'?<><VolumeGlyph value={effectiveVolume}/><strong>{Math.round(effectiveVolume*100)}%</strong><i style={{'--level':effectiveVolume}}/></>:<>{gestures.feedback.type==='episodes'?<ChevronsUp size={22}/>:<ChevronsDown size={22}/>}<strong>{gestures.feedback.type==='episodes'?'Серии':'Настройки'}</strong></>}
      </motion.output>}</AnimatePresence>
      {actions.notice&&<output className="mvx-notice" role="status">{actions.notice}</output>}
      {actions.recording&&<button type="button" className="mvx-recording" onClick={actions.clip}><Square size={11} fill="currentColor"/><span>Остановить запись</span><small>{actions.clipSeconds} из 30 сек.</small></button>}
      <PlayerExtensionSlot name="overlay" extensions={extensions} onError={onError}/>

      {hasEpisodes&&<button type="button" className="mvx-episode-chip" aria-label="Выбрать серию" aria-expanded={panel==='episodes'} onClick={()=>openPanel(panel==='episodes'?'watch':'episodes')}>
        <LayoutGrid size={15} aria-hidden="true"/><span>{episode?.label||'Серии'}</span>{(onlineControls?.seasonName||season?.name)&&<small>{onlineControls?.seasonName||season?.name}</small>}<ChevronDown size={14} aria-hidden="true"/>
      </button>}
      <div id="player-panel-watch" className="mvx-overview" inert={playing||panel!=='watch'} aria-hidden={playing||panel!=='watch'}>
        <h1>{title}</h1>
        <p className="mvx-meta">{episode?.label&&<span>{episode.label}</span>}{(onlineControls?.seasonName||season?.name)&&<span>{onlineControls?.seasonName||season?.name}</span>}{season?.episodes.length>1&&episodeNumber>0&&<span>{episodeNumber} из {season.episodes.length}</span>}</p>
        {episode?.description&&/[а-яё]/i.test(episode.description)&&<p className="mvx-description">{episode.description}</p>}
        {source&&!busy&&<button type="button" className="mvx-primary" onClick={toggle}><Play size={16} fill="currentColor" strokeWidth={0}/>{time>1?'Продолжить с '+clock(time):resumePoint>0?'Продолжить с '+clock(resumePoint):'Смотреть'}</button>}
      </div>
      {room.info&&!roomControl&&<button type="button" ref={roomButton} className="mvx-room-pill" aria-label={'Комната, '+roomSummary(room)} aria-pressed={settingsOpen&&settingsTab==='room'} onClick={()=>settingsOpen&&settingsTab==='room'?openPanel('watch'):openSettings('room')}>
        <Users size={15} aria-hidden="true"/><span className="mvx-room-names">{roomMembers(room).filter(m=>m.online).map(m=><span key={m.id} data-speaking={room.conversation.speaking?.[m.id]||undefined}>{m.name}</span>)}</span><small>{onlineCount}</small>
      </button>}
      {room.info&&(isFullscreen||previewOverlay)&&<RoomOverlay conversation={room.conversation} onOpenRoom={()=>openSettings('room')}/>}
      <PlayerSongCue track={showSongCue?currentSong:null} theme={songTheme} visible={showSongCue} onDismiss={()=>setDismissedCue(currentSong.id)} onPlay={()=>playMusic(currentSong)}/>

      <AnimatePresence>{panel==='episodes'&&hasEpisodes&&<motion.section key="episodes" className="mvx-episodes" inert={settingsOpen} aria-label="Сезоны и серии" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} transition={{duration:.18}}>
        <header className="mvx-episodes-head">
          <h2>Серии</h2>
          {selectorSeasons.length>1&&<div className="mvx-season-tabs mvx-scroll" role="tablist" aria-label="Сезон плеера">{selectorSeasons.map(s=><button type="button" role="tab" key={s.id} aria-selected={String(s.id)===String(browsingSeasonId)} onClick={()=>{if(onlineControls?.onBrowseSeason)onlineControls.onBrowseSeason(s.id);else setBrowsedSeasonId(s.id);}}>{s.name}</button>)}</div>}
          <button type="button" className="mvx-episodes-close" aria-label="Закрыть серии" onClick={()=>openPanel('watch')}><X size={20}/></button>
        </header>
        <div className="mvx-episodes-body mvx-scroll">
          {onlineControls?.episodeBrowser?<div className="mvx-online-episodes">{onlineControls.episodeBrowser}</div>:<div className="mvx-episode-grid" ref={railRef}>{seasonEpisodes.map((ep,i)=>{
            const current=ep===episode;
            const shown=ep.variants.find(v=>v.item.id===item.id)?.item||ep.variants.find(v=>v.item.previewArtwork)?.item||ep.variants[0]?.item;
            const saved=current?null:ep.variants.map(v=>readProgress(userId,libraryId,v.item.id)).find(Boolean);
            const watched=saved?.duration?Math.min(1,saved.time/saved.duration):0;
            const voices=ep.variants.length;
            return <button type="button" key={ep.id} className={'mvx-card'+(current?' is-current':'')} aria-current={current?'true':undefined} onClick={()=>{choose(ep.variants[0]?.item);openPanel('watch');}}>
              <span className="mvx-card-art">
                {renderEpisodeArtwork?renderEpisodeArtwork(shown,i):(shown?.preview||item.preview||scene.image)&&<img src={shown?.preview||item.preview||scene.image} alt="" loading="lazy"/>}
                {current&&<span className="mvx-card-now">{playing?<Pause size={14} fill="currentColor"/>:<Play size={14} fill="currentColor"/>}Сейчас</span>}
                {watched>0&&<span className="mvx-card-progress" style={{'--watched':watched*100+'%'}} aria-label={'Просмотрено '+Math.round(watched*100)+'%'}/>}
              </span>
              <strong>{ep.number&&!/\d/.test(ep.label)?ep.number+'. ':''}{ep.label}</strong>
              <small>{voices>1?voices+' '+plural(voices,'озвучка','озвучки','озвучек'):ep.variants[0]?.label}</small>
            </button>;
          })}</div>}
        </div>
      </motion.section>}</AnimatePresence>

      <AnimatePresence>{settingsOpen&&<PlayerSettings anchor={settingsButton} initialPage={settingsTab} sections={sections} actions={settingsActions} footer={settingsFooter} onClose={()=>openPanel('watch')}/>}</AnimatePresence>
      <AnimatePresence>{canSkip&&panel==='watch'&&<motion.button type="button" key={skipRange===ending?'ed':'op'} className="mvx-skip" initial={{opacity:0,x:16}} animate={{opacity:1,x:0}} exit={{opacity:0,x:16}} transition={{duration:.2,ease:[.2,.8,.2,1]}} onClick={()=>seek(skipRange.end)} style={{'--skip-progress':Math.max(0,Math.min(1,(time-skipRange.start)/Math.max(1,skipRange.end-skipRange.start)))}}><span>{skipRange===ending?'Пропустить эндинг':'Пропустить опенинг'}</span><ChevronsRight size={18}/></motion.button>}</AnimatePresence>

      {gpuActive&&<span className="mvx-gpu-tag"><Sparkles size={12}/>{engineName}{engine==='mobile'||engine==='lanczos'||String(engine).startsWith('fsr')?'':' ×2'}{neuralStats&&<span>{neuralStats.fps} кадр/с</span>}</span>}
      {busy&&<div className="mvx-loading" role="status"><span className="mvx-spinner"/>Готовим видео</div>}
      <div className="mvx-console" onPointerEnter={revealControls}>
        <Timeline timeline={timeline} duration={duration} time={previewTime} buffered={buffered} seekable={seekable} disabled={!!roomControl&&!roomControl.canControl} source={source} type={item.onlineType} segments={segments} feedback={gestures.feedback} onSeek={seek} hoverSeek={hoverSeek} setHoverSeek={setHoverSeek} seekTimer={seekTimer}/>
        <div className="mvx-controls">
          <div className="mvx-group-left">
            <button type="button" className="mvx-play" aria-label={playing?'Пауза':'Воспроизвести'} onClick={toggle} disabled={!source}>{playing?<Pause size={22} fill="currentColor" strokeWidth={0}/>:<Play size={22} fill="currentColor" strokeWidth={0}/>}</button>
            {controller.nextEpisode&&episodes[index+1]&&<button type="button" aria-label="Следующая серия" title={'Следующая серия: '+(episodes[index+1]?.label||'')} onClick={controller.nextEpisode}><SkipForward size={19}/></button>}
            <div className="mvx-volume">
              <button type="button" aria-label={effectiveVolume===0?'Включить звук':'Отключить звук'} title="Звук, M" onClick={()=>{if(effectiveVolume===0){setMuted(false);if(!prefs.volume)changePrefs({volume:1});}else setMuted(true);}}><VolumeGlyph value={prefs.volume} muted={muted}/></button>
              <input type="range" min="0" max="1" step=".05" value={effectiveVolume} aria-label="Громкость" style={{'--fill':effectiveVolume*100+'%'}} onChange={event=>{setMuted(false);changePrefs({volume:Number(event.target.value)});}}/>
            </div>
            <span className="mvx-time"><span>{clock(time)}</span><span>{clock(duration)}</span></span>
          </div>
          <div className="mvx-group-right">
            {dub&&<DubMenu {...dub} onPick={dub.pick}/>}
            {musicIdentity&&<button type="button" ref={musicButton} className={musicOpen?'is-active':''} aria-label="Музыка из аниме" aria-expanded={musicOpen} onClick={()=>{setDownloadOpen(false);openPanel(musicOpen?'watch':'music');}}><Music2 size={19}/></button>}
            {canDownload&&<button type="button" ref={downloadButton} className="mvx-hide-phone" aria-label="Скачать видео" aria-expanded={downloadOpen} title="Сохранить серию на компьютер" onClick={()=>{setMusicOpen(false);setDownloadOpen(v=>!v);}}><Download size={19}/></button>}
            <button type="button" ref={settingsButton} className={settingsOpen?'is-active':''} aria-label="Настройки плеера" data-player-settings="" aria-expanded={settingsOpen} onClick={()=>settingsOpen?openPanel('watch'):openSettings('watch')}><SlidersHorizontal size={19}/></button>
            <button type="button" className="mvx-hide-phone" aria-label={isPip?'Закрыть мини-окно':'Мини-окно'} aria-pressed={isPip} title="Мини-окно" disabled={!document.pictureInPictureEnabled&&!('webkitSetPresentationMode' in HTMLVideoElement.prototype)} onClick={pip}><PictureInPicture2 size={19}/></button>
            <button type="button" aria-label={isFullscreen?'Выйти из полноэкранного режима':'На весь экран'} title="Полный экран, F" onClick={fullscreen}>{isFullscreen?<Minimize2 size={19}/>:<Maximize2 size={19}/>}</button>
          </div>
        </div>
      </div>
    </div>
    <PlayerExtensionSlot name="footer" extensions={extensions} onError={onError}/>
    <input ref={subtitleInput} type="file" accept=".srt,.vtt,text/vtt" hidden onChange={attachSubtitle}/>
    <input ref={lutInput} type="file" accept=".cube" hidden onChange={loadLut}/>
    <AnimatePresence>{musicOpen&&<PlayerPopover anchor={musicButton} label="Музыка серии" className="mvx-menu" onClose={()=>setMusicOpen(false)}>
      <header className="mvx-menu-head"><h2>Музыка серии</h2>{episodeMusic.tracks.length>0&&<small>{episodeMusic.tracks.length} {plural(episodeMusic.tracks.length,'песня','песни','песен')}</small>}</header>
      {episodeMusic.tracks.length?<ul className="mvx-songs mvx-scroll">{episodeMusic.tracks.slice(0,8).map(t=>{const live=currentSong?.id===t.id,on=nowPlaying?.track?.id===t.id;return <li key={t.id}><button type="button" className={'mvx-song-row'+(live||on?' is-live':'')} onClick={()=>{playMusic(t,episodeMusic.tracks);setMusicOpen(false);}} aria-label={'Слушать '+t.title}>
        <span className="mvx-song-art">{t.cover?<img src={t.cover} alt="" loading="lazy" referrerPolicy="no-referrer"/>:<Music2 size={18}/>}<Play size={14} fill="currentColor" strokeWidth={0}/></span>
        <span className="mvx-song-text"><small>{t.type==='OP'?'Опенинг':t.type==='ED'?'Эндинг':'Музыка серии'}{live?', звучит сейчас':on?', играет':''}</small><strong>{t.title}</strong><span>{(t.artists||[]).join(', ')||'Исполнитель не указан'}</span></span>
      </button></li>;})}</ul>:<p className="mvx-menu-empty">{episodeMusic.timingState==='loading'?'Ищем песни серии.':'Песни для этой серии не найдены.'}</p>}
      {episodeOst.tracks.some(t=>!t.uncertain)&&<section className="mvx-ost"><header className="mvx-menu-head"><h2>Фоновая музыка</h2><small>WTAS.moe · ≈ время</small></header><ul className="mvx-songs mvx-scroll">{episodeOst.tracks.filter(t=>!t.uncertain).map(t=>{const live=time>=t.start&&time<t.end;return <li key={t.title+t.start}><button type="button" className={'mvx-song-row'+(live?' is-live':'')} onClick={()=>{seek(Math.max(0,t.start-1));setMusicOpen(false);}} aria-label={'Перейти к '+t.title+' на '+clockOf(t.start)}><span className="mvx-song-art"><Music2 size={18}/></span><span className="mvx-song-text"><small>{clockOf(t.start)}–{clockOf(t.end)}{live?', звучит сейчас':''}</small><strong>{t.title}</strong><span>{t.album||'Саундтрек'}</span></span></button><button type="button" className="mvx-ost-play" aria-label={'Слушать отдельно '+t.title} onClick={()=>{playMusic(ostTrack(t),episodeOst.tracks.filter(x=>!x.uncertain).map(ostTrack));setMusicOpen(false);}}><Play size={14} fill="currentColor" strokeWidth={0}/></button></li>;})}</ul></section>}
    </PlayerPopover>}</AnimatePresence>
    <AnimatePresence>{downloadOpen&&<PlayerPopover anchor={downloadButton} label="Скачать серию" className="mvx-menu" onClose={()=>setDownloadOpen(false)}>
      <header className="mvx-menu-head"><h2>Скачать серию</h2><small>MP4 без перекодирования</small></header>
      {downloadHeights.length>0&&<div className="mvx-segmented" role="radiogroup" aria-label="Качество файла">{downloadHeights.map(h=><button type="button" key={h} role="radio" aria-checked={downloadHeight===h} onClick={()=>setDownloadHeight(h)}>{h>=2160?'4K':h+'p'}</button>)}</div>}
      <label className="mvx-input"><span>Имя файла</span><input value={downloadName} maxLength={120} onChange={e=>setDownloadName(e.target.value)}/></label>
      <Note>Сервер собирает файл из потока постепенно. У некоторых источников скорость равна скорости просмотра.</Note>
      <div className="mvx-button-row"><button type="button" onClick={()=>setDownloadOpen(false)}>Отмена</button><button type="button" className="is-primary" onClick={()=>{download(downloadHeight,downloadName);setDownloadOpen(false);}}><Download size={15}/>Скачать</button></div>
    </PlayerPopover>}</AnimatePresence>
    {gpuWarning&&<p className="mvx-warning" role="status">{gpuWarning}</p>}
    {downloadStatus&&<p className="mvx-warning" role="status">{downloadStatus}</p>}
  </div>{room.info&&(chatSlot?createPortal(<aside className="player-room-conversation is-sidebar"><RoomConversation conversation={room.conversation}/></aside>,chatSlot):<aside className="player-room-conversation"><RoomConversation conversation={room.conversation}/></aside>)}</div></PlayerContext.Provider>;
}
