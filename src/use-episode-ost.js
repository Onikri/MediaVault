import {useEffect,useState} from 'react';
// Background music of one episode, recognised by WTAS.moe and cached by our server.
const cache=new Map();
export const ostTrack=t=>({id:'ost:'+t.title,title:t.title,artists:t.album?[t.album]:[],album:t.album,spotify:t.spotify,source:'ost'});
export const spotifyTrackUrl=id=>/^[A-Za-z0-9]{22}$/.test(id||'')?'https://open.spotify.com/track/'+id:'';
export async function loadEpisodeOst(server,identity,episode,signal){
 const key=server+'|'+identity+'|'+episode,hit=cache.get(key);if(hit&&hit.until>Date.now())return hit.value;
 const response=await fetch(server+'/music/ost/'+encodeURIComponent(identity)+'/'+encodeURIComponent(episode),{signal});
 const value=await response.json().catch(()=>({}));if(!response.ok)throw Error(typeof value.detail==='string'?value.detail:'Саундтрек серии недоступен.');
 if(!value.pending){cache.set(key,{value,until:Date.now()+3600000});while(cache.size>64)cache.delete(cache.keys().next().value);}
 return value;
}
export default function useEpisodeOst(identity,episode,server=window.MEDIA_VAULT_CONFIG?.importServerUrl){
 const [state,setState]=useState({tracks:[],available:false,loading:false});
 useEffect(()=>{
  setState({tracks:[],available:false,loading:!!(identity&&episode&&server)});
  if(!/^\d+$/.test(String(identity||''))||!episode||!server)return;
  const abort=new AbortController();let timer,tries=0;
  // The server builds its WTAS index once (about a minute); poll gently meanwhile.
  const run=()=>loadEpisodeOst(server,identity,episode,AbortSignal.any([abort.signal,AbortSignal.timeout(20000)])).then(value=>{
   if(abort.signal.aborted)return;
   if(value.pending&&tries++<6){timer=setTimeout(run,20000);return;}
   setState({...value,tracks:value.tracks||[],loading:false});
  }).catch(()=>{if(!abort.signal.aborted)setState({tracks:[],available:false,loading:false});});
  run();return()=>{abort.abort();clearTimeout(timer);};
 },[identity,episode,server]);
 return state;
}
