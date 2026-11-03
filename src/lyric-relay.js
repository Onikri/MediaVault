import {musicIdentity} from './music-identity.js';
import {normalizeLyrics,parseLrc} from './lyrics.js';

export async function searchRelayLyrics(track,duration,service,{signal,refresh=false}={}){
 const identity=musicIdentity(track);
 const value=await service.request('/music/lyrics',{method:'POST',signal:AbortSignal.any([...(signal?[signal]:[]),AbortSignal.timeout(5000)]),
  body:{titles:identity.titles,artists:identity.artists,duration,rich:true,refresh}});
 if(!['ready','empty','instrumental','restricted','error','busy'].includes(value?.phase))throw Error('Некорректный ответ каталога текстов.');
 const parsed=value.lines?.length?normalizeLyrics(value.lines):value.lrc?parseLrc(value.lrc):{lines:[],precision:'plain'};
 const url=/^https:\/\/(?:www\.musixmatch\.com\/|lrclib\.net\/api\/get\/|lyrics\.ovh\/)/.test(value.url||'')?value.url:'';
 return {...parsed,phase:value.phase,plainText:String(value.plainText||'').slice(0,100000),source:value.source||'',url,
  timingMismatch:!!value.timingMismatch,cached:!!value.cached,elapsedMs:value.elapsedMs,identity:value.identity};
}
