import {musicIdentity,rankLyricRecord} from './music-identity.js';
import {parseLrc} from './lyrics.js';
export async function searchLrcLyrics(track,duration,{signal,fetcher=fetch}={}){
 const identity=musicIdentity(track),bounded=AbortSignal.any([...(signal?[signal]:[]),AbortSignal.timeout(12000)]),rows=[];
 async function get(path,params){const r=await fetcher('https://lrclib.net/api/'+path+'?'+new URLSearchParams(params),{credentials:'omit',priority:'low',signal:bounded});if(!r.ok){if(r.status===404)return [];throw Error('Каталог текстов временно недоступен.');}const value=await r.json();return Array.isArray(value)?value.slice(0,200):[value];}
 const exact=await get('get',{track_name:identity.title,artist_name:identity.artist||identity.artists[0]||'',duration:String(Math.round(duration))}).catch(error=>{if(bounded.aborted)throw error;return [];});rows.push(...exact);
 let best=rows.sort((a,b)=>rankLyricRecord(b,identity,duration)-rankLyricRecord(a,identity,duration))[0];
 if(!best?.syncedLyrics||rankLyricRecord(best,identity,duration)<0){
  // Search ranked structured records, not the unparsed video caption. Parallel
  // native/Latin artist forms tolerate database aliases without accepting covers.
  const queries=identity.titles.slice(0,2).flatMap(title=>identity.artists.slice(0,3).map(artist=>({track_name:title,artist_name:artist})));
  if(!queries.length)queries.push({track_name:identity.title});
  const found=await Promise.allSettled(queries.map(q=>get('search',q)));for(const r of found)if(r.status==='fulfilled')rows.push(...r.value);
  best=[...new Map(rows.map(r=>[r.id,r])).values()].filter(r=>rankLyricRecord(r,identity,duration)>=0).sort((a,b)=>rankLyricRecord(b,identity,duration)-rankLyricRecord(a,identity,duration))[0];
 }
 bounded.throwIfAborted();if(!best||rankLyricRecord(best,identity,duration)<0)return null;
 const parsed=best.syncedLyrics?parseLrc(best.syncedLyrics):{lines:[],precision:'plain'};
 return {...parsed,plainText:!parsed.lines.length?String(best.plainLyrics||'').slice(0,100000):'',source:'LRCLIB',url:'https://lrclib.net/api/get/'+encodeURIComponent(best.id),identity:{title:best.trackName,artist:best.artistName,album:best.albumName,duration:best.duration},recordId:best.id};
}
