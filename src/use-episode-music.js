import {useEffect,useState} from 'react';
export function inEpisodes(values,episode){
 if(!values?.length)return true;
 return values.some(v=>String(v).split(/[, ]+/).some(part=>{const m=part.match(/^(\d+)(?:-(\d+))?$/);return m&&episode>=Number(m[1])&&episode<=Number(m[2]||m[1]);}));
}
export default function useEpisodeMusic(identity,episode,duration){
 const [data,setData]=useState({tracks:[],intervals:[]});
 useEffect(()=>{setData({tracks:[],intervals:[]});const server=window.MEDIA_VAULT_CONFIG?.importServerUrl;if(!identity||!episode||!duration||!server)return;const a=new AbortController();
  const load=url=>fetch(url,{signal:a.signal}).then(r=>r.ok?r.json():{}).catch(()=>({}));
  load(server+'/music/anime/'+identity).then(songs=>{if(!a.signal.aborted)setData(old=>({...old,tracks:(songs.tracks||[]).filter(t=>inEpisodes(t.episodes,Number(episode)))}));});
  load(server+'/music/timings/'+identity+'/'+episode+'?duration='+Math.round(duration)).then(timing=>{if(!a.signal.aborted)setData(old=>({...old,intervals:timing.intervals||[]}));});return()=>a.abort();
 },[identity,episode,Math.round(duration)]);return data;
}
