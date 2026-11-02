import {musicIdentity,rankLyricRecord} from './music-identity.js';
import {parseLrc} from './lyrics.js';
export async function searchLrcLyrics(track,duration,{signal,fetcher=fetch}={}){
 const identity=musicIdentity(track),bounded=AbortSignal.any([...(signal?[signal]:[]),AbortSignal.timeout(12000)]),rows=[];let providerFailed=false,retries=2;
 const pause=ms=>new Promise((resolve,reject)=>{const done=()=>{bounded.removeEventListener('abort',stop);resolve();},timer=setTimeout(done,ms),stop=()=>{clearTimeout(timer);reject(bounded.reason);};if(bounded.aborted)stop();else bounded.addEventListener('abort',stop,{once:true});});
 async function get(path,params){let r;for(let attempt=0;attempt<2;attempt++){bounded.throwIfAborted();r=await fetcher('https://lrclib.net/api/'+path+'?'+new URLSearchParams(params),{credentials:'omit',priority:'low',signal:bounded});if([429,503].includes(r.status)&&attempt===0&&retries>0){retries--;await pause(Math.min(2000,Math.max(250,Number(r.headers.get('Retry-After')||1)*1000)));continue;}break;}if(!r.ok){if(r.status===404)return [];throw Error('Каталог текстов временно недоступен.');}const value=await r.json();return Array.isArray(value)?value.slice(0,200):[value];}

 const exact=await get('get',{track_name:identity.title,artist_name:identity.artist||identity.artists[0]||'',duration:String(Math.round(duration))}).catch(error=>{if(bounded.aborted)throw error;providerFailed=true;return [];});rows.push(...exact);
 let best=rows.sort((a,b)=>rankLyricRecord(b,identity,duration)-rankLyricRecord(a,identity,duration))[0];
 if(!best?.syncedLyrics||rankLyricRecord(best,identity,duration)<0){
  // Search ranked structured records, not the unparsed video caption. Parallel
  // native/Latin artist forms tolerate database aliases without accepting covers.
  const queries=[{q:[identity.title,identity.artist].filter(Boolean).join(' ')},{q:identity.title},...identity.titles.slice(0,2).flatMap(title=>identity.artists.slice(0,3).map(artist=>({track_name:title,artist_name:artist})))];
  let cursor=0;const worker=async()=>{while(cursor<queries.length&&!bounded.aborted){if(rows.some(r=>r.syncedLyrics&&rankLyricRecord(r,identity,duration)>=0))return;const query=queries[cursor++];try{rows.push(...await get('search',query));}catch(error){if(bounded.aborted)throw error;providerFailed=true;}}};
  await Promise.allSettled([worker(),worker()]);
  best=[...new Map(rows.map(r=>[r.id,r])).values()].filter(r=>rankLyricRecord(r,identity,duration)>=0).sort((a,b)=>rankLyricRecord(b,identity,duration)-rankLyricRecord(a,identity,duration))[0];
 }
 bounded.throwIfAborted();let timingMismatch=false;
 if(!best||rankLyricRecord(best,identity,duration)<0){best=rows.filter(r=>rankLyricRecord(r,identity,duration,{allowVideoPadding:true})>=0).sort((a,b)=>rankLyricRecord(b,identity,duration,{allowVideoPadding:true})-rankLyricRecord(a,identity,duration,{allowVideoPadding:true}))[0];timingMismatch=!!best;}
 if(!best){if(providerFailed&&!rows.length)throw Error('Каталог текстов временно недоступен.');return null;}
 const parsed=best.syncedLyrics&&!timingMismatch?parseLrc(best.syncedLyrics):{lines:[],precision:'plain'};const plain=best.plainLyrics||(timingMismatch?parseLrc(best.syncedLyrics||'').lines.map(l=>l.text).join('\n'):'');
 return {...parsed,plainText:!parsed.lines.length?String(plain||'').slice(0,100000):'',timingMismatch,source:'LRCLIB',url:'https://lrclib.net/api/get/'+encodeURIComponent(best.id),identity:{title:best.trackName,artist:best.artistName,album:best.albumName,duration:best.duration},recordId:best.id};
}
