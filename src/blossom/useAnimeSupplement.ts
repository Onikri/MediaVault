import {useEffect,useState} from 'react';
import {jikan,youtubeTrailer} from '../media-metadata.js';
import {normalizeProfile} from '../title-metadata.js';
import {fillProfile,jikanProfile} from '../title-supplement.js';
import type {Anime} from './types/anime';
// Public exact-ID metadata only. Shared across cards; never reads private artwork.
const details=new Map<string,Promise<any>>();
function russianProfile(id:string,kind:string,server:string){
 const key=server+':'+kind+':'+id;
 if(!details.has(key)){
  const url=server?server+'/metadata/shikimori?'+new URLSearchParams({identity:id,kind}):'https://shikimori.io/api/'+(kind==='anime'?'animes/':'mangas/')+id;
  const work=fetch(url,{signal:AbortSignal.timeout(7000),credentials:'omit',referrerPolicy:'no-referrer'}).then(async response=>{if(!response.ok)throw Error();const data=await response.json();if(String(data.id)!==id)throw Error();return normalizeProfile(data);});
  details.set(key,work);work.catch(()=>details.delete(key));while(details.size>128)details.delete(details.keys().next().value);
 }
 return details.get(key)!;
}
export function useAnimeSupplement(anime:Anime,enabled:boolean,kind='anime'){
 const [extra,setExtra]=useState<any>(null),[detail,setDetail]=useState<any>(null),[busy,setBusy]=useState(false),id=String(anime.mal_id||'');
 useEffect(()=>{setExtra(null);setDetail(null);},[id,kind]);
 useEffect(()=>{
  if(!enabled||!/^\d{1,12}$/.test(id)||!['anime','video','manga','ranobe'].includes(kind)){setBusy(false);return;}
  const abort=new AbortController(),resource=['manga','ranobe'].includes(kind)?'manga':'anime',server=window.MEDIA_VAULT_CONFIG?.importServerUrl||'';let remaining=2;
  setBusy(true);const done=()=>{if(!abort.signal.aborted&&!--remaining)setBusy(false);};
  jikan(resource+'/'+id+'/full',{signal:abort.signal}).then(r=>{if(!abort.signal.aborted&&String(r.data?.mal_id)===id)setExtra(r.data);}).catch(()=>{}).finally(done);
  russianProfile(id,resource,server).then(value=>{if(!abort.signal.aborted)setDetail(value);}).catch(()=>{}).finally(done);
  return()=>abort.abort();
 },[id,kind,enabled]);
 return {extra,busy,profile:fillProfile(detail||{},jikanProfile(extra,['manga','ranobe'].includes(kind)?'manga':'anime')),trailer:youtubeTrailer(anime.trailer)||youtubeTrailer(extra?.trailer),cover:extra?.images?.webp?.large_image_url||extra?.images?.jpg?.large_image_url||''};
}
