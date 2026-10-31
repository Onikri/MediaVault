import {useEffect,useRef,useState} from 'react';
export default function useVideoStream(ref,source,type,onError,{preview=false}={}){
 const engine=useRef(null),report=useRef(onError);report.current=onError;
 const [levels,setLevels]=useState([]),[level,setLevelState]=useState(-1),[audio,setAudio]=useState([]),[subtitles,setSubtitles]=useState([]);
 const hls=type==='hls'||/\.m3u8(?:\?|$)/i.test(source||'');
 useEffect(()=>{let closed=false,instance;setLevels([]);setAudio([]);setSubtitles([]);setLevelState(-1);const v=ref.current;if(!v||!source||!hls)return;
  import('hls.js').then(({default:Hls})=>{if(closed)return;
   if(!Hls.isSupported()){if(v.canPlayType('application/vnd.apple.mpegurl')){v.src=source;return;}throw Error('Этот браузер не поддерживает HLS.');}
   instance=new Hls({autoStartLoad:false,maxBufferLength:preview?8:30,maxMaxBufferLength:preview?12:60,backBufferLength:preview?0:30,renderTextTracksNatively:true});engine.current=instance;let recovery=0;
   instance.on(Hls.Events.MANIFEST_PARSED,()=>{const rows=instance.levels.map((l,i)=>({index:i,height:Number.parseInt(l.attrs?.NAME||l.name)||l.height,bitrate:l.bitrate}));setLevels(rows);instance.startLevel=preview?0:rows.reduce((best,l)=>l.height>(rows[best]?.height||0)?l.index:best,0);if(preview)instance.autoLevelCapping=0;instance.startLoad();});
   instance.on(Hls.Events.AUDIO_TRACKS_UPDATED,()=>setAudio(instance.audioTracks.map((a,i)=>({index:i,name:a.name||a.lang||'Дорожка '+(i+1)}))));
   instance.on(Hls.Events.SUBTITLE_TRACKS_UPDATED,()=>setSubtitles(instance.subtitleTracks.map((a,i)=>({index:i,name:a.name||a.lang||'Субтитры '+(i+1)}))));
   instance.on(Hls.Events.ERROR,(_,data)=>{if(!data.fatal||closed)return;if(recovery++<2){if(data.type===Hls.ErrorTypes.NETWORK_ERROR){instance.startLoad();return;}if(data.type===Hls.ErrorTypes.MEDIA_ERROR){instance.recoverMediaError();return;}}report.current?.(Error('Поток не ответил. Попробуй другой источник той же озвучки.'));});
   instance.loadSource(source);instance.attachMedia(v);
  }).catch(e=>!closed&&report.current?.(e));
  return()=>{closed=true;instance?.destroy();if(engine.current===instance)engine.current=null;};
 },[ref,source,hls,preview]);
 return {hls,levels,level,setLevel:n=>{if(engine.current){engine.current.currentLevel=n;setLevelState(n);}},audio,setAudio:n=>{if(engine.current)engine.current.audioTrack=n;},subtitles,setSubtitle:n=>{if(engine.current){engine.current.subtitleTrack=n;engine.current.subtitleDisplay=n>=0;}}};
}
