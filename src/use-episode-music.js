import {useEffect,useState} from 'react';
export function inEpisodes(values,episode){
 if(!values?.length)return true;
 return values.some(v=>String(v).split(/[, ]+/).some(part=>{const m=part.match(/^(\d+)(?:-(\d+))?$/);return m&&episode>=Number(m[1])&&episode<=Number(m[2]||m[1]);}));
}
const cache=new Map();
async function load(url,signal,fresh=false){
 const hit=cache.get(url);if(!fresh&&hit&&hit.until>Date.now())return hit.value;
 const response=await fetch(url,{signal});if(!response.ok)throw Error('База разметки временно недоступна.');const value=await response.json();
 if(!value.unavailable){cache.set(url,{value,until:Date.now()+(value.intervals?.length?3600000:120000)});while(cache.size>128)cache.delete(cache.keys().next().value);}
 return value;
}
export default function useEpisodeMusic(identity,episode,duration,server=window.MEDIA_VAULT_CONFIG?.importServerUrl){
 const [data,setData]=useState({tracks:[],intervals:[],timingState:'idle'}),[revision,setRevision]=useState(0);
 useEffect(()=>{setData({tracks:[],intervals:[],timingState:'loading'});if(!identity||!episode||!duration||!server)return;const a=new AbortController(),signal=AbortSignal.any([a.signal,AbortSignal.timeout(12000)]);
  load(server+'/music/anime/'+identity,signal).then(songs=>{if(!a.signal.aborted)setData(old=>({...old,tracks:(songs.tracks||[]).filter(t=>inEpisodes(t.episodes,Number(episode)))}));}).catch(()=>{});
  load(server+'/music/timings/'+identity+'/'+episode+'?duration='+Number(duration.toFixed(3)),signal,revision>0).then(timing=>{if(!a.signal.aborted)setData(old=>({...old,intervals:timing.intervals||[],timingState:timing.unavailable?'error':timing.intervals?.length?'ready':'empty',timingMessage:timing.message||''}));}).catch(()=>{if(!a.signal.aborted)setData(old=>({...old,timingState:'error',timingMessage:'База разметки временно недоступна. Повтори поиск или отметь опенинг вручную.'}));});return()=>a.abort();
 },[identity,episode,Math.round(duration),server,revision]);return {...data,retry:()=>setRevision(n=>n+1)};
}
