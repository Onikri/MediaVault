import {useEffect,useState} from 'react';
import {jikan,youtubeTrailer} from '../media-metadata.js';
import type {Anime} from './types/anime';
export function useAnimeSupplement(anime:Anime,enabled:boolean,kind='anime'){
 const [extra,setExtra]=useState<any>(null),id=String(anime.mal_id||'');
 useEffect(()=>{setExtra(null);},[id,kind]);
 useEffect(()=>{if(!enabled||!/^\d{1,12}$/.test(id)||!['anime','video','manga','ranobe'].includes(kind))return;const abort=new AbortController();jikan((['manga','ranobe'].includes(kind)?'manga':'anime')+'/'+id+'/full',{signal:abort.signal}).then(r=>{if(!abort.signal.aborted&&String(r.data?.mal_id)===id)setExtra(r.data);}).catch(()=>{});return()=>abort.abort();},[id,kind,enabled]);
 return {extra,trailer:youtubeTrailer(anime.trailer)||youtubeTrailer(extra?.trailer),cover:extra?.images?.webp?.large_image_url||extra?.images?.jpg?.large_image_url||''};
}
