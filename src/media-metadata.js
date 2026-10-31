// Shared public metadata cache. Never stores Drive data, keys, or decrypted media.
const cache=new Map(),pending=new Map(),cooldown=new Map();let nextRequest=0;
export async function jikan(path,{server=globalThis.window?.MEDIA_VAULT_CONFIG?.importServerUrl||'',signal,params={}}={}){
 if(!/^(?:anime|manga)(?:\/\d+(?:\/(?:full|pictures|videos|characters|staff|relations|episodes))?)?$|^top\/(?:anime|manga)$|^seasons\/(?:now|upcoming|\d{4}\/(?:winter|spring|summer|fall))$/.test(path))throw Error('Неизвестный раздел каталога.');
 const key=server+':'+path+':'+JSON.stringify(params),hit=cache.get(key);signal?.throwIfAborted();
 if(hit&&hit.until>Date.now())return hit.data;
 if(!pending.has(key)){
  const query=new URLSearchParams(params),targets=[...(server?[server+'/metadata/jikan-data?'+new URLSearchParams({path,...params})]:[]),'https://api.jikan.moe/v4/'+path+(query.size?'?'+query:''),'https://api.tenrai.org/v1/'+path+(query.size?'?'+query:'')];
  const work=(async()=>{for(const target of targets){const host=new URL(target).origin;if((cooldown.get(host)||0)>Date.now())continue;
    try{if(!server||host!==new URL(server).origin){const start=Math.max(Date.now(),nextRequest);nextRequest=start+1050;if(start>Date.now())await new Promise(r=>setTimeout(r,start-Date.now()));}
     const response=await fetch(target,{signal:AbortSignal.timeout(6500),credentials:'omit',referrerPolicy:'no-referrer'});if(!response.ok)throw Error();const data=await response.json();if(!('data'in data))throw Error();cache.set(key,{data,until:Date.now()+21600000});while(cache.size>200)cache.delete(cache.keys().next().value);return data;
    }catch{cooldown.set(host,Date.now()+30000);}
   }if(hit)return hit.data;throw Error('Каталог MyAnimeList временно недоступен.');})();pending.set(key,work);work.finally(()=>pending.delete(key)).catch(()=>{});
 }
 const data=await pending.get(key);signal?.throwIfAborted();return data;
}
export async function animeHome({server,signal}={}){
 if(server)try{const r=await fetch(server+'/metadata/anime-home',{signal:AbortSignal.any([...(signal?[signal]:[]),AbortSignal.timeout(18000)])});if(r.ok){const d=await r.json();if(Array.isArray(d.current)&&Array.isArray(d.popular))return d;}}catch{signal?.throwIfAborted();}
 const now=new Date(),season=['winter','spring','summer','fall'][Math.floor(now.getMonth()/3)],year=now.getFullYear();
 const results=await Promise.allSettled([jikan(`seasons/${year}/${season}`,{server,signal,params:{limit:24,sfw:'true'}}),jikan('top/anime',{server,signal,params:{limit:24,filter:'bypopularity',sfw:'true'}})]);
 return {season:{year,name:season,label:({winter:'Зима',spring:'Весна',summer:'Лето',fall:'Осень'})[season]+' '+year},current:(results[0].value?.data||[]).filter(r=>(!r.season||r.season===season)&&(!r.year||r.year===year)),popular:results[1].value?.data||[]};
}
export function youtubeTrailer(value){const id=value?.youtube_id;if(/^[\w-]{11}$/.test(id||''))return 'https://www.youtube-nocookie.com/embed/'+id;const url=value?.embed_url;try{const u=new URL(url);return /(^|\.)youtube(?:-nocookie)?\.com$/.test(u.hostname)&&/^\/embed\/[\w-]{11}$/.test(u.pathname)?u.href:null;}catch{return null;}}
export function artworkIdentity(asset){return asset?.id||asset?.fileId||'';}
