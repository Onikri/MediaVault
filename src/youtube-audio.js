export function youtubeIdentity(value){
 try{const u=new URL(value);if(u.protocol!=='https:'||u.username||u.password||u.port&&u.port!=='443')return null;let id;
  if(u.hostname==='youtu.be')id=u.pathname.slice(1);else if(['youtube.com','www.youtube.com','m.youtube.com','music.youtube.com'].includes(u.hostname)){if(u.pathname==='/watch'){const ids=u.searchParams.getAll('v');id=ids.length===1?ids[0]:null;}else id=u.pathname.match(/^\/(?:shorts|embed)\/([\w-]{11})\/?$/)?.[1];}
  return /^[\w-]{11}$/.test(id||'')?id:null;
 }catch{return null;}
}
export async function openYouTubeAudio(service,id,{signal,refresh=false}={}){
 if(!/^[\w-]{11}$/.test(id))throw Error('Некорректная запись YouTube.');
 return openMusicAudio(service,'https://www.youtube.com/watch?v='+id,{signal,refresh});
}
export async function openMusicAudio(service,url,{signal,refresh=false,remote=false}={}){
 const data=await service.request(remote?'/music/remote':'/music/play',{method:'POST',body:{url,refresh},signal});
 const close=()=>service.request('/online/'+encodeURIComponent(data.id),{method:'DELETE'}).catch(()=>{});
 const origin=new URL(service.server).origin,stream=new URL(data.streamUrl,origin);
 if(!/^[\w-]{30,80}$/.test(data.id||'')||stream.origin!==origin||!new RegExp('^/online/'+data.id+'/[\\w-]{12,40}$').test(stream.pathname)||stream.search||stream.hash||!(remote?['audio/mpeg','audio/mp4','audio/webm','audio/ogg','audio/flac','audio/wav','audio/aac']:['audio/mp4','audio/webm']).includes(data.mime)){
  if(/^[\w-]{30,80}$/.test(data.id||''))await close();throw Error('Сервер вернул некорректный аудиопоток.');
 }
 if(signal?.aborted){await close();signal.throwIfAborted();}
 return {...data,streamUrl:stream.href,close};
}
