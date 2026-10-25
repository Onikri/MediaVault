import {useEffect,useRef,useState} from 'react';
export default function useVideoStream(ref,source,type,onError){
 const engine=useRef(null),report=useRef(onError);report.current=onError;
 const [levels,setLevels]=useState([]),[level,setLevelState]=useState(-1),[audio,setAudio]=useState([]);
 const hls=type==='hls'||/\.m3u8(?:\?|$)/i.test(source||'');
 useEffect(()=>{let closed=false,instance;setLevels([]);setAudio([]);setLevelState(-1);const v=ref.current;if(!v||!source||!hls)return;
  if(v.canPlayType('application/vnd.apple.mpegurl')){v.src=source;return;}
  import('hls.js').then(({default:Hls})=>{if(closed)return;if(!Hls.isSupported())throw Error('Этот браузер не поддерживает HLS. Попробуй другой браузер или импорт в Drive.');instance=new Hls({maxBufferLength:30,maxMaxBufferLength:60,backBufferLength:30,renderTextTracksNatively:true});engine.current=instance;
   instance.on(Hls.Events.MANIFEST_PARSED,()=>{setLevels(instance.levels.map((l,i)=>({index:i,height:l.height,bitrate:l.bitrate})));});instance.on(Hls.Events.AUDIO_TRACKS_UPDATED,()=>setAudio(instance.audioTracks.map((a,i)=>({index:i,name:a.name||a.lang||'Дорожка '+(i+1)}))));instance.on(Hls.Events.ERROR,(_,data)=>{if(data.fatal&&!closed)report.current?.(Error('Не удалось воспроизвести поток источника. Открой серию повторно или выбери другой источник.'));});instance.loadSource(source);instance.attachMedia(v);
  }).catch(e=>!closed&&report.current?.(e));return()=>{closed=true;instance?.destroy();if(engine.current===instance)engine.current=null;};
 },[ref,source,hls]);
 return {hls,levels,level,setLevel:n=>{if(engine.current){engine.current.currentLevel=n;setLevelState(n);}},audio,setAudio:n=>{if(engine.current)engine.current.audioTrack=n;}};
}
