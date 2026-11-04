import {useRoomConversation} from './room-conversation.js';
import {useEffect,useRef,useState} from 'react';

export function roomMedia(item,source,server,configuration={},audioOffset=0){
 const address=new URL(source,location.href),api=new URL(server),tracks=[];
 const add=(url,track)=>{if(!url)return;const target=new URL(url,location.href);if(target.origin!==api.origin||!/^\/online\/[\w-]+\/[\w-]+$/.test(target.pathname))throw Error('Отдельную дорожку нужно открыть через сервер перед созданием комнаты.');tracks.push({...track,path:target.pathname});};
 if(configuration.audio)add(configuration.audio.url,{kind:'audio',type:configuration.audio.type||'mp4',name:'Выбранная озвучка'});
 for(const t of (configuration.externalCaptions||[]).slice(0,5))add(t.url,{kind:'caption',type:'vtt',name:t.name||'Субтитры',language:t.language||'ru'});
 const extra={tracks,audioOffset};
 if(address.origin===api.origin&&/^\/online\/[\w-]+\/[\w-]+$/.test(address.pathname))return {...extra,path:address.pathname,type:item.onlineType==='hls'?'hls':'mp4'};
 if(address.protocol!=='blob:'&&address.origin!==location.origin)throw Error('Этот поток нельзя передать в комнату. Открой его через наш онлайн-плеер.');
 if(!(item.size>0))throw Error('Неизвестен размер файла. Дождись подготовки видео.');
 return {...extra,size:item.size,mime:/webm/i.test(item.mime||item.name||'')?'video/webm':'video/mp4',type:/webm/i.test(item.mime||item.name||'')?'webm':'mp4'};
}
export const roomLink=id=>location.origin+location.pathname+'#room='+encodeURIComponent(id);
export function roomSocket(server,identity,token,onMessage,onStatus){
 const url=new URL(server);url.protocol=url.protocol==='https:'?'wss:':'ws:';url.pathname=url.pathname.replace(/\/$/,'')+'/rooms/'+identity+'/socket';url.search='';
 const socket=new WebSocket(url);let timer;
 socket.onopen=()=>{socket.send(JSON.stringify({token}));onStatus?.('connected');timer=setInterval(()=>{if(socket.readyState===1)socket.send(JSON.stringify({type:'ping'}));},15000);};
 socket.onmessage=e=>{try{onMessage(JSON.parse(e.data));}catch{}};
 socket.onclose=()=>{clearInterval(timer);onStatus?.('disconnected');};socket.onerror=()=>onStatus?.('disconnected');return socket;
}
function bytesBase64(bytes){let text='';for(let p=0;p<bytes.length;p+=8192)text+=String.fromCharCode(...bytes.subarray(p,p+8192));return btoa(text);}
export function useHostRoom(api,service,item,source,context,enabled=true,configuration){
 const [password,setPassword]=useState(''),[info,setInfo]=useState(null),[state,setState]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[connected,setConnected]=useState(false);
 const live=useRef(),socket=useRef(null),session=useRef(null),applying=useRef(new Map()),lastMedia=useRef(''),stateRef=useRef(null),reads=useRef(new Set());
 live.current={api,service,item,source,context,configuration};stateRef.current=state;
 const conversation=useRoomConversation(socket,info?.memberId,state,connected);
 function send(value){if(socket.current?.readyState===1)socket.current.send(JSON.stringify(value));}
 async function read(data){
  const current=live.current,version=lastMedia.current,abort=new AbortController();reads.current.add(abort);
  try{
   if(socket.current.bufferedAmount>8*1024*1024||!Number.isSafeInteger(data.start)||!Number.isSafeInteger(data.end)||data.start<0||data.end-data.start>=1024*1024)throw Error();
   const response=await fetch(current.source,{headers:{Range:`bytes=${data.start}-${data.end}`},signal:abort.signal,credentials:'same-origin'});
   if(response.status!==206&&!(response.status===200&&data.start===0&&current.item.size<=1024*1024))throw Error();
   const reader=response.body.getReader(),parts=[];let size=0;
   try{for(;;){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>1024*1024)throw Error();parts.push(value);}}finally{await reader.cancel().catch(()=>{});}
   if(lastMedia.current!==version||size!==data.end-data.start+1)throw Error();
   const bytes=new Uint8Array(size);let offset=0;for(const part of parts){bytes.set(part,offset);offset+=part.length;}
   send({type:'data',id:data.id,data:bytesBase64(bytes)});
  }catch{send({type:'data',id:data.id,error:true});}finally{reads.current.delete(abort);}
 }
 async function create(){
  if(!enabled||busy)return;setBusy(true);setError('');
  try{
   const current=live.current;if(!current.service?.request||!current.service?.server)throw Error('Подключи сервер в профиле для создания комнаты.');
   const media=roomMedia(current.item,current.source,current.service.server,current.configuration,current.api.getSnapshot().preferences.audioOffset||0);
   const mal=String(current.context?.malId||current.context?.animeId||'');
   const value=await current.service.request('/rooms',{method:'POST',body:{password,title:current.context?.title||current.item.collectionName||current.item.name,malId:/^\d{1,10}$/.test(mal)?mal:'',media}});
   session.current=value;setInfo(value);lastMedia.current=JSON.stringify(media);
   socket.current=roomSocket(current.service.server,value.id,value.token,data=>{
    conversation.receive(data);
    if(data.type==='state'){
     setState(data.room);const video=live.current.api.media;
     if(video&&data.room.held!==stateRef.current?.held){if(data.room.held&&!video.paused){applying.current.set('pause',{until:performance.now()+1500});video.pause();}else if(!data.room.held&&data.room.playing&&video.paused){applying.current.set('play',{until:performance.now()+1500});video.play().catch(()=>applying.current.delete('play'));}}
    }else if(data.type==='command'){
     const media=live.current.api.media;
     if(data.action==='seek'){applying.current.set('seeked',{until:performance.now()+2000,position:data.position});live.current.api.seek(data.position);}else if(data.action==='play'&&media?.paused){applying.current.set('play',{until:performance.now()+1500});live.current.api.play()?.catch(()=>applying.current.delete('play'));}else if(data.action==='pause'&&media&&!media.paused){applying.current.set('pause',{until:performance.now()+1500});live.current.api.pause();}
    }else if(data.type==='read')read(data);
    else if(data.type==='error')setError(data.message);
   },status=>{setConnected(status==='connected');if(status==='connected')setTimeout(()=>publish(true),100);});
  }catch(e){setError(e.message);}finally{setBusy(false);}
 }
 function publish(intent=false){const value=live.current.api.getSnapshot();send({type:'state',position:value.time,duration:value.duration,rate:live.current.api.media?.playbackRate||1,playing:intent?value.playing:(stateRef.current?.playing??value.playing),intent});}
 useEffect(()=>{
  if(!info)return;const media=api.media;if(!media)return;
  const update=e=>{const expected=applying.current.get(e.type);applying.current.delete(e.type);if(expected&&expected.until>performance.now()&&(e.type!=='seeked'||Math.abs(media.currentTime-expected.position)<.5))return;publish(['play','pause','seeked','ratechange'].includes(e.type));};
  const waiting=()=>send({type:'buffer',value:true}),ready=()=>send({type:'buffer',value:false});
  for(const type of ['play','pause','seeked','ratechange'])media.addEventListener(type,update);
  media.addEventListener('waiting',waiting);media.addEventListener('canplay',ready);media.addEventListener('playing',ready);const timer=setInterval(()=>publish(false),1000);
  return()=>{clearInterval(timer);for(const type of ['play','pause','seeked','ratechange'])media.removeEventListener(type,update);media.removeEventListener('waiting',waiting);media.removeEventListener('canplay',ready);media.removeEventListener('playing',ready);};
 },[api,info]);
 useEffect(()=>{
  if(!info||!connected)return;
  try{const media=roomMedia(item,source,service.server,configuration,api.getSnapshot().preferences.audioOffset||0),key=JSON.stringify(media);if(lastMedia.current===key)return;lastMedia.current=key;for(const c of reads.current)c.abort();send({type:'media',media,title:context?.title||item.name});}catch(e){setError(e.message);}
 });
 function close(){send({type:'close'});socket.current?.close();socket.current=null;session.current=null;setInfo(null);setState(null);setConnected(false);for(const c of reads.current)c.abort();}
 useEffect(()=>()=>{if(socket.current?.readyState===1)socket.current.send(JSON.stringify({type:'close'}));socket.current?.close();for(const c of reads.current)c.abort();},[]);
 return {password,setPassword,info,state,error,busy,connected,create,close,conversation,settings:value=>send({type:'settings',...value}),copy:async()=>{try{await navigator.clipboard.writeText(roomLink(info.id));}catch{setError('Скопируй ссылку из поля комнаты.');}}};
}

export {applyRoomState} from './room-playback.js';
