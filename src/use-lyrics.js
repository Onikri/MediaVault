import {useEffect,useState} from 'react';
import {parseLrc,parseTtml,matchLyricRecord,normalizeLyrics} from './lyrics.js';
import {searchLrcLyrics} from './lyric-search.js';
const BASE='https://raw.githubusercontent.com/amll-dev/amll-ttml-db/main/',INDEX=BASE+'metadata/raw-lyrics-index.jsonl';let indexPromise;
const cache=new Map();
async function readBounded(response,max){if(!response.ok)throw Error();if(Number(response.headers.get('Content-Length'))>max)throw Error();const text=await response.text();if(text.length>max)throw Error();return text;}
async function index(){
 if(!indexPromise)indexPromise=(async()=>{let store;try{store=await caches.open('mediavault-lyrics-metadata-v1');const hit=await store.match(INDEX);if(hit&&Date.now()-Number(hit.headers.get('x-mv-at'))<7*86400000)return (await readBounded(hit,6000000)).split('\n').filter(Boolean).map(l=>JSON.parse(l));}catch{}
  const text=await readBounded(await fetch(INDEX,{credentials:'omit',priority:'low',signal:AbortSignal.timeout(10000)}),6000000);try{await store?.put(INDEX,new Response(text,{headers:{'x-mv-at':String(Date.now())}}));}catch{}return text.split('\n').filter(Boolean).map(l=>JSON.parse(l));})();
 try{return await indexPromise;}catch(e){indexPromise=null;throw e;}
}
export default function useLyrics(track,duration,enabled=true){
 const [data,setData]=useState({phase:'idle',lines:[]}),[retry,setRetry]=useState(0),key=[track?.id,track?.title,track?.aliases?.join('|'),track?.artists?.join('|'),Math.round(duration/2)*2].join(':');
 useEffect(()=>{
  if(!enabled||!track){setData({phase:'idle',lines:[]});return;}
  const raw=track.syncedLyrics||track.lyrics,supplied=typeof raw==='string'?parseLrc(raw):Array.isArray(raw)?normalizeLyrics(raw):null;
  if(supplied?.lines.length){setData({...supplied,phase:'ready',source:'Встроенный текст'});return;}
  if(!duration||!track.title||!track.artists?.length){setData({phase:duration?'empty':'loading',lines:[]});return;}
  const hit=cache.get(key);if(hit&&!retry){setData(hit);return;}
  const abort=new AbortController(),signal=abort.signal;let found=false,quality=0;
  setData({phase:'loading',lines:[]});
  const accept=value=>{if(!value||signal.aborted||(!value.lines.length&&!value.plainText))return;const rank=value.precision==='word'?3:value.lines.length?2:1;if(rank<=quality||value.lines.at(-1)?.start>duration+2)return;value.lines=value.lines.map(l=>({...l,end:Math.min(l.end,duration)}));quality=rank;found=true;const result={...value,phase:'ready'};cache.set(key,result);while(cache.size>32)cache.delete(cache.keys().next().value);setData(result);};
  const lrclib=searchLrcLyrics(track,duration,{signal}).then(accept);
  const amll=(async()=>{const records=matchLyricRecord(await index(),track);for(const record of records){signal.throwIfAborted();const url=BASE+'raw-lyrics/'+record.rawLyricFile,text=await readBounded(await fetch(url,{credentials:'omit',priority:'low',signal:AbortSignal.any([signal,AbortSignal.timeout(7000)])}),1000000),parsed=parseTtml(text),end=parsed.lines.at(-1)?.end||0;if(parsed.precision==='word'&&end<=duration+2&&duration-end<30){accept({...parsed,source:'AMLL TTML DB',url:'https://github.com/amll-dev/amll-ttml-db/blob/main/raw-lyrics/'+record.rawLyricFile});break;}}})();
  Promise.allSettled([lrclib,amll]).then(results=>{if(!signal.aborted&&!found)setData({phase:results.every(r=>r.status==='rejected')?'error':'empty',lines:[]});});
  return()=>abort.abort();
 },[track?.id,track?.title,track?.artists?.join('|'),track?.aliases?.join('|'),key,!!duration,enabled,retry]);
 return {...data,retry:()=>setRetry(n=>n+1)};
}
