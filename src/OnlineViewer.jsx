import {useEffect,useRef,useState,useMemo,useCallback} from 'react';
import {createPortal} from 'react-dom';
import {ArrowLeft,Maximize,Minimize,X} from 'lucide-react';
import MediaVaultPlayer from './MediaVaultPlayer.jsx';
import MangaReader from './MangaReader.jsx';
import {stopLmt} from './lmt-client.js';
import {onlineClientId,keepOnlineLease} from './online-lease.js';
import {reportOnlinePlayback} from './online-playback.js';
import {prepareOnline,releaseOnline} from './collaps-direct.js';
import {saveCollapsLocally} from './collaps-save.js';
import {exportLocally} from './local-export.js';
import './online.css';
import {minimumEpisodeDuration,onlineEpisodeId} from './watch-session.js';
export default function OnlineViewer({entries,initial,kind,title,service,userId,onClose,onEntryChange,language='ru',dub='',metadata,quality='best',inline=false,sourceUrl,identity,voiceId,controls,onPreview,previews,onUnavailable,onPrepared,errorActions,readerPreset}){
 useEffect(()=>()=>stopLmt(),[]);
 const [playbackQuality,setPlaybackQuality]=useState(quality);
 useEffect(()=>setPlaybackQuality(quality),[quality]);
 const unavailable=useRef(onUnavailable);unavailable.current=onUnavailable;const prepared=useRef(onPrepared);prepared.current=onPrepared;
 const [current,setCurrent]=useState(initial),[media,setMedia]=useState(null),[busy,setBusy]=useState(true),[error,setError]=useState('');
 const [initialURL,setInitialURL]=useState(initial?.url);
 if(initialURL!==initial?.url){setInitialURL(initial?.url);setCurrent(initial);}
 const [retry,setRetry]=useState(0),[elapsed,setElapsed]=useState(0),[full,setFull]=useState(false),[fullscreenError,setFullscreenError]=useState('');
 const playerApi=useRef(null),currentMedia=useRef(media),recovering=useRef(''),resumePending=useRef(false),reconnect=useRef(null);currentMedia.current=media;
 reconnect.current=()=>{
  const previous=currentMedia.current;
  if(previous?.sessionRecovery??previous?.playbackTelemetry){if(recovering.current===previous.id)return;recovering.current=previous.id;resumePending.current=true;}
  setRetry(v=>v+1);
 };
 const playbackExtensions=useMemo(()=>media?.playbackTelemetry?[{id:'online-playback-state',setup:api=>reportOnlinePlayback({request:(...args)=>live.current.request(...args)},media.id,api,()=>reconnect.current())}]:[],[media?.id,media?.playbackTelemetry]);
 const host=useRef(null),clientId=useRef(null),activeLease=useRef(null);if(!clientId.current)clientId.current=onlineClientId('viewer');
 useEffect(()=>{if(inline){const frame=requestAnimationFrame(()=>{if(!document.fullscreenElement)host.current?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});});return()=>cancelAnimationFrame(frame);}},[initial?.url,inline]);
 useEffect(()=>{const change=()=>setFull(document.fullscreenElement===host.current);document.addEventListener('fullscreenchange',change);return()=>document.removeEventListener('fullscreenchange',change);},[]);
 async function fullscreen(){setFullscreenError('');try{if(document.fullscreenElement)await document.exitFullscreen();else if(host.current?.requestFullscreen)await host.current.requestFullscreen();else setFullscreenError('Полный экран недоступен в этом браузере.');}catch{setFullscreenError('Браузер не разрешил полный экран.');}}
 useEffect(()=>{if(!busy)return;const start=performance.now();setElapsed(0);const timer=setInterval(()=>setElapsed(Math.floor((performance.now()-start)/1000)),1000);return()=>clearInterval(timer);},[busy,current.url,retry]);
 const items=useMemo(()=>entries.map(e=>({id:identity?onlineEpisodeId(identity,e.season||1,e.number):'online:'+e.url,name:title+' · '+(e.title||'Серия '+e.number),category:kind==='manga'?'manga':'video',section:kind==='manga'?'manga':'anime',episode:e.number,season:e.season||1,collectionId:identity?'online-title:'+identity:'online-title',metadata:{ids:metadata?.ids,format:metadata?.format},readingMode:metadata?.readingMode,metadataId:metadata?.ids?.mal,dub,voiceId,preview:previews?.[e.number]||metadata?.cover,sourceURL:e.url,translationInfo:{language},episodeTitle:e.title})),[entries,identity,title,kind,metadata,dub,voiceId,previews,language]);
 const selected=media?.item||items.find(e=>e.sourceURL===current.url)||items[0],generation=useRef(0),live=useRef(service);live.current=service;
 useEffect(()=>{const version=++generation.current,abort=new AbortController();let token;if(kind!=='video')setMedia(null);setBusy(true);setError('');
  prepareOnline(service,{url:current.url,kind,clientId:clientId.current,...(retry>0&&Number(service.session?.serverVersion)>=44?{refresh:true}:{}),...(kind==='video'?{quality:playbackQuality,...(sourceUrl?{referer:sourceUrl}:{})}:{})},{signal:AbortSignal.any([abort.signal,AbortSignal.timeout(45000)])}).then(data=>{token=data.id;if(version!==generation.current||abort.signal.aborted){releaseOnline(live.current,data);return;}const previous=activeLease.current;
   let resume;const old=currentMedia.current;
   if(resumePending.current&&old?.entry?.url===current.url){
    resume=playerApi.current?.getSnapshot();
    if(resume&&Number.isFinite(resume.time)){
     try{sessionStorage.setItem('mediavault_pending_time_'+old.item.id,String(resume.time));}catch{}
    }
   }
   resumePending.current=false;
   activeLease.current=data.direct?()=>releaseOnline(live.current,data):keepOnlineLease(live.current,token,()=>reconnect.current());
   setMedia({...data,resume,item:items.find(e=>e.sourceURL===current.url)||items[0],entry:current,entries,catalog});
   previous?.();prepared.current?.(data);}).catch(e=>{if(!abort.signal.aborted){recovering.current='';if(!unavailable.current?.(e))setError(e.name==='TimeoutError'?'Источник не ответил за 45 секунд. Повтори подключение или выбери другой источник.':e.message);}}).finally(()=>{if(!abort.signal.aborted)setBusy(false);});return()=>{generation.current++;abort.abort();};
 },[current.url,kind,service.server,playbackQuality,retry,sourceUrl]);
 useEffect(()=>()=>{activeLease.current?.();activeLease.current=null;},[]);
 useEffect(()=>{const close=()=>onClose();addEventListener('mediavault-locked',close);const old=document.body.style.overflow;if(!inline)document.body.style.overflow='hidden';return()=>{if(!inline)document.body.style.overflow=old;removeEventListener('mediavault-locked',close);};},[onClose,inline]);
 const catalog=useMemo(()=>({items,storage:{collections:[{id:identity?'online-title:'+identity:'online-title',name:title,section:kind==='manga'?'manga':'anime',metadata}]}}),[items,identity,title,kind,metadata]);
 function choose(item){const e=entries.find(e=>e.url===item.sourceURL)||media?.entries?.find(e=>e.url===item.sourceURL);if(e){setCurrent(e);onEntryChange?.(e);}}
 const server=service.server.replace(/\/$/,'');
 const content=<section ref={host} className={'online-viewer'+(busy&&media?' is-switching':'')+(inline?' online-viewer-inline'+(kind==='video'?' online-video-frameless':' online-reader-frameless'):'')} role={inline?'region':'dialog'} aria-modal={inline?undefined:'true'} aria-label={inline?(kind==='manga'?'Читалка на странице':'Плеер на странице'):'Онлайн без сохранения'}>{(kind!=='manga'||!media)&&<header>{!inline&&<button className="icon-button" onClick={onClose} aria-label="Закрыть онлайн-просмотр"><ArrowLeft size={20}/></button>}<div><strong>{title}</strong><small>{current.title||'Онлайн'}{dub?' · '+dub:''}</small></div>{inline&&<div className="online-viewer-actions"><button type="button" className="icon-button" onClick={fullscreen} aria-label={full?'Вернуть на страницу':'Развернуть просмотр на весь экран'}>{full?<Minimize size={18}/>:<Maximize size={18}/>}</button><button type="button" className="icon-button" onClick={onClose} aria-label="Закрыть встроенный просмотр"><X size={18}/></button></div>}</header>}{fullscreenError&&<p className="fine" role="status">{fullscreenError}</p>}{busy&&<p className="online-loading" role="status"><span className="loading-ring"/>Подключаем источник{elapsed?' · '+elapsed+' с':'…'}</p>}{error&&<div className="inline-error" role="alert"><p>{error}</p><button className="icon-button" aria-label="Скрыть ошибку источника" onClick={()=>setError('')}><X size={16}/></button><button className="btn btn-secondary" onClick={()=>setRetry(v=>v+1)}>Повторить подключение</button>{typeof errorActions==='function'?errorActions(current):errorActions}</div>}{media&&selected&&(kind==='manga'?<MangaReader key={selected.id} item={{...selected,sharedTranslation:readerPreset,onlinePages:media.pages.map(p=>server+p)}} catalog={catalog} userId={userId} libraryId="online" onClose={onClose} onSelectItem={choose} readerService={service} retainLmt inline embedded={inline} errorActions={typeof errorActions==='function'?errorActions(media.entry):errorActions}/>:<MediaVaultPlayer apiRef={playerApi} extensions={playbackExtensions} characterService={service} autoPlay={media.resume?media.resume.playing:true} item={{...selected,onlineType:media.type}} source={media.direct?media.url:server+media.url} onDownload={media.direct&&kind==='video'&&!['guest','share'].includes(service.session?.role)?(height,name,progress)=>saveCollapsLocally({service:live.current,entries:[{url:current.url}],quality:height?String(height):'best',name,onProgress:progress}):media.allohaMode&&!['guest','share'].includes(service.session?.role)?(height,name,progress)=>exportLocally({service:live.current,kind:'video',entries:[media.entry||current],referer:sourceUrl,quality:height?String(height):'best',name,onProgress:progress}):undefined} catalog={media.catalog||catalog} userId={userId} libraryId="online" onClose={onClose} onSelectItem={choose} minimumDuration={minimumEpisodeDuration(metadata)} onError={e=>{if((media.sessionRecovery??media.playbackTelemetry)&&[404,409,410].includes(e.status)){reconnect.current();return;}if(!unavailable.current?.(e))setError(e.message);}} onRejectedSource={e=>{activeLease.current?.();activeLease.current=null;setMedia(null);if(!unavailable.current?.(e))setError(e.message);}} onPlaybackRecovered={()=>setError('')} onPreview={onPreview} onlineControls={{...controls,alloha:!!media.allohaMode,sourceIntervals:media.sourceIntervals||[],server:service.server,externalEpisodeList:!!controls?.voices,sessionRecovery:!!(media.sessionRecovery??media.playbackTelemetry),retryStream:()=>reconnect.current(),quality:playbackQuality,qualities:media.qualities||[],onQuality:setPlaybackQuality,externalCaptions:[...(controls?.externalCaptions||[]),...(media.subtitles||[]).map(t=>({...t,url:server+t.url}))]}}/>)}</section>;
 return inline?content:createPortal(content,document.body);
}
