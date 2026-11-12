import {useEffect,useRef,useState} from 'react';
import {streamBufferPolicy,initialStreamLevel,bitrateBufferPolicy} from './watch-quality.js';
export default function useVideoStream(ref,source,type,onError,{preview=false,audioOnly=false,quality='best',startPosition=0,sessionRecovery=false,alloha=false}={}){
 const engine=useRef(null),report=useRef(onError),requested=useRef(quality);report.current=onError;requested.current=quality;
 const [levels,setLevels]=useState([]),[level,setLevelState]=useState(-1),[audio,setAudio]=useState([]),[subtitles,setSubtitles]=useState([]);
 const hls=type==='hls'||/\.m3u8(?:\?|$)/i.test(source||'');
 useEffect(()=>{let closed=false,instance;setLevels([]);setAudio([]);setSubtitles([]);setLevelState(-1);const v=ref.current;if(!v||!source||!hls)return;
  import('hls.js').then(({default:Hls})=>{if(closed)return;
   if(!Hls.isSupported()){if(v.canPlayType('application/vnd.apple.mpegurl')){v.src=source;return;}throw Error('Этот браузер не поддерживает HLS.');}
   const connection=navigator.connection;
   const buffer=streamBufferPolicy({preview,audioOnly,saveData:!!connection?.saveData,memory:navigator.deviceMemory||8,alloha});
   instance=new Hls({autoStartLoad:false,testBandwidth:false,...buffer,renderTextTracksNatively:true});engine.current=instance;let recovery=0;
   instance.on(Hls.Events.LEVEL_SWITCHING,(_,data)=>{const limits=bitrateBufferPolicy(buffer,instance.levels[data.level]?.bitrate);instance.config.maxBufferLength=limits.maxBufferLength;instance.config.maxMaxBufferLength=limits.maxMaxBufferLength;});
   instance.on(Hls.Events.MANIFEST_PARSED,()=>{const rows=instance.levels.map((l,i)=>({index:i,height:Number.parseInt(l.attrs?.NAME||l.name)||l.height,bitrate:l.bitrate}));setLevels(rows);instance.startLevel=initialStreamLevel(rows,{preview,audioOnly,saveData:!!connection?.saveData,downlink:connection?.downlink,memory:navigator.deviceMemory||8});if(preview||audioOnly)instance.autoLevelCapping=0;if(requested.current!=='best'){const selected=rows.find(l=>l.height===Number(requested.current));if(selected){instance.startLevel=selected.index;instance.loadLevel=selected.index;setLevelState(selected.index);}}instance.startLoad(Math.max(0,Number(startPosition)||0));});
   instance.on(Hls.Events.FRAG_BUFFERED,()=>{recovery=0;});
   instance.on(Hls.Events.AUDIO_TRACKS_UPDATED,()=>setAudio(instance.audioTracks.map((a,i)=>({index:i,name:a.name||a.lang||'Дорожка '+(i+1)}))));
   instance.on(Hls.Events.SUBTITLE_TRACKS_UPDATED,()=>setSubtitles(instance.subtitleTracks.map((a,i)=>({index:i,name:a.name||a.lang||'Субтитры '+(i+1)}))));
   let sessionFailed=false;
   instance.on(Hls.Events.ERROR,(_,data)=>{if(closed||sessionFailed)return;const status=Number(data.response?.code);if(sessionRecovery&&[404,409,410].includes(status)){sessionFailed=true;instance.stopLoad();report.current?.(Object.assign(Error('Сессия потока завершена. Переподключаем…'),{status}));return;}if(!data.fatal)return;if(recovery++<2){if(data.type===Hls.ErrorTypes.NETWORK_ERROR){instance.startLoad();return;}if(data.type===Hls.ErrorTypes.MEDIA_ERROR){instance.recoverMediaError();return;}}report.current?.(Error('Поток не ответил. Попробуй другой источник той же озвучки.'));});
   instance.loadSource(source);instance.attachMedia(v);
  }).catch(e=>!closed&&report.current?.(e));
  return()=>{closed=true;instance?.destroy();if(engine.current===instance)engine.current=null;};
 },[ref,source,hls,preview,audioOnly,sessionRecovery,alloha]);
 useEffect(()=>{const instance=engine.current;if(!instance?.levels?.length)return;const index=quality==='best'?-1:instance.levels.findIndex(l=>Number.parseInt(l.attrs?.NAME||l.name||l.height)===Number(quality));instance.nextLevel=index;setLevelState(index);},[quality]);
 return {hls,levels,level,setLevel:n=>{if(engine.current){engine.current.nextLevel=n;setLevelState(n);}},audio,setAudio:n=>{if(engine.current)engine.current.audioTrack=n;},audioTrack:()=>engine.current?.audioTrack??-1,subtitles,subtitleUrl:n=>engine.current?.subtitleTracks?.[n]?.url||'',setSubtitle:n=>{const e=engine.current;if(!e)return;
  // Every switch makes hls.js disable all labelled text tracks, the page's own
  // <track> files included: touch it only when its subtitles really change.
  if(e.subtitleDisplay)e.subtitleDisplay=false;if(e.subtitleTrack!==n)e.subtitleTrack=n;}};
}
