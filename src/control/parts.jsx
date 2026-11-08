import {useEffect,useState} from 'react';
import {timecode} from './use-control-data.js';

export const JOB_NAMES={queued:'В очереди',running:'Выполняется',completed:'Готово',failed:'Прервано',waiting_auth:'Ждёт Google',cancelling:'Останавливается',cancelled:'Остановлено',merged:'Объединено'};
export const JOB_TONES={running:'is-live',cancelling:'is-live',queued:'',completed:'is-ok',failed:'is-bad',waiting_auth:'is-warn',cancelled:'',merged:''};

// Shikimori posters for rooms that know their MAL id; one request per id set.
const posterCache=new Map();
export function usePosters(service,ids){
 const key=[...new Set(ids.filter(id=>/^\d+$/.test(id||'')))].sort().join(',');
 const [posters,setPosters]=useState(()=>posterCache.get(key)||{});
 useEffect(()=>{
  if(!key||!service?.request)return;
  if(posterCache.has(key)){setPosters(posterCache.get(key));return;}
  let closed=false;
  service.request('/metadata/posters?'+new URLSearchParams({ids:key,kind:'anime'}),{auth:false}).then(value=>{posterCache.set(key,value||{});if(!closed)setPosters(value||{});}).catch(()=>{});
  return()=>{closed=true;};
 },[key,service?.request]);
 return posters;
}

// Where a room is in its video, advanced locally between polls so the bar keeps moving.
export function livePosition(room,fetchedAt,now){
 const elapsed=room.playing?Math.max(0,(now-fetchedAt)/1000)*(room.rate||1):0;
 return room.duration?Math.min(room.duration,room.position+elapsed):room.position+elapsed;
}

export function Timeline({room,fetchedAt,now,compact=false}){
 const position=livePosition(room,fetchedAt,now),share=room.duration?Math.min(1,position/room.duration):0;
 const state=room.held?'Ждём, пока все загрузят видео':room.playing?'Идёт':'Пауза';
 return <div className={'cc-timeline'+(room.playing?' is-playing':'')+(compact?' is-compact':'')}>
  <div className="cc-timeline-track" role="progressbar" aria-label={'Позиция просмотра: '+room.title} aria-valuemin={0} aria-valuemax={Math.round(room.duration||0)} aria-valuenow={Math.round(position)} aria-valuetext={timecode(position)+(room.duration?' из '+timecode(room.duration):'')}>
   <i style={{transform:'scaleX('+share+')'}}/>
  </div>
  <div className="cc-timeline-meta"><span className={'cc-play-state'+(room.held?' is-warn':room.playing?' is-live':'')}>{state}</span><span className="cc-num">{timecode(position)}{room.duration?<small> / {timecode(room.duration)}</small>:null}</span></div>
 </div>;
}

export function Poster({src,title}){
 const [failed,setFailed]=useState(false);
 if(!src||failed)return null;
 return <img className="cc-poster" src={src} alt="" title={title} referrerPolicy="no-referrer" loading="lazy" onError={()=>setFailed(true)}/>;
}
