import {useEffect,useState} from 'react';
export function inEpisodes(values,episode){
 if(!values?.length)return true;
 return values.some(v=>String(v).split(/[, ]+/).some(part=>{const m=part.match(/^(\d+)(?:-(\d+))?$/);return m&&episode>=Number(m[1])&&episode<=Number(m[2]||m[1]);}));
}
export default function useEpisodeMusic(identity,episode,duration){
 const [data,setData]=useState({tracks:[],intervals:[]});
 useEffect(()=>{setData({tracks:[],intervals:[]});const server=window.MEDIA_VAULT_CONFIG?.importServerUrl;if(!identity||!episode||!duration||!server)return;const a=new AbortController();
  Promise.all([fetch(server+'/music/anime/'+identity,{signal:a.signal}).then(r=>r.ok?r.json():{}),fetch(server+'/music/timings/'+identity+'/'+episode+'?duration='+Math.round(duration),{signal:a.signal}).then(r=>r.ok?r.json():{})]).then(([songs,timing])=>{if(!a.signal.aborted)setData({tracks:(songs.tracks||[]).filter(t=>inEpisodes(t.episodes,Number(episode))),intervals:timing.intervals||[]});}).catch(()=>{});return()=>a.abort();
 },[identity,episode,Math.round(duration)]);return data;
}
