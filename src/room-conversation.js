import {useEffect,useRef,useState} from 'react';
// Room-scoped signalling only. Audio goes peer to peer (or through our own
// TURN relay on Oracle when a network blocks direct connections), never into
// playback. Microphone choice and processing stay in this browser.
const SETTINGS_KEY='mv_room_voice_v1';
export const VOICE_PROFILES={
 voice:{label:'Голос',hint:'Моно, шумоподавление, экономит сеть',bitrate:48000,stereo:false},
 music:{label:'Музыка',hint:'Стерео, без обработки, 128 кбит/с',bitrate:128000,stereo:true}
};
const DEFAULTS={inputId:'',outputId:'',echoCancellation:true,noiseSuppression:true,autoGainControl:true,profile:'voice',inputGain:1,volumes:{}};
function readSettings(){try{return {...DEFAULTS,...JSON.parse(localStorage.getItem(SETTINGS_KEY)||'{}')};}catch{return {...DEFAULTS};}}
function writeSettings(value){try{localStorage.setItem(SETTINGS_KEY,JSON.stringify(value));}catch{}}
let audioContext;
function context(){if(!audioContext){const Context=window.AudioContext||window.webkitAudioContext;if(!Context)return null;audioContext=new Context();}if(audioContext.state==='suspended')audioContext.resume().catch(()=>{});return audioContext;}
// RMS of the time-domain signal: a small, cheap speaking indicator.
function meter(stream){
 const ctx=context();if(!ctx||!stream?.getAudioTracks().length)return null;
 const source=ctx.createMediaStreamSource(stream),analyser=ctx.createAnalyser();analyser.fftSize=512;source.connect(analyser);
 const data=new Uint8Array(analyser.fftSize);
 return {level(){analyser.getByteTimeDomainData(data);let sum=0;for(const v of data){const x=(v-128)/128;sum+=x*x;}return Math.min(1,Math.sqrt(sum/data.length)*3.2);},close(){try{source.disconnect();}catch{}}};
}
async function iceConfiguration(access){
 const configured=window.MEDIA_VAULT_CONFIG?.roomIceServers;
 if(Array.isArray(configured)&&configured.length)return {iceServers:configured,relay:true};
 try{
  const response=await fetch(access.server.replace(/\/$/,'')+'/rooms/'+encodeURIComponent(access.id)+'/ice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:access.token}),signal:AbortSignal.timeout(8000)});
  const data=await response.json();if(response.ok&&Array.isArray(data.iceServers))return data;
 }catch{}
 return {iceServers:[{urls:'stun:stun.l.google.com:19302'}],relay:false};
}
export function useRoomConversation(socket,memberId,room,connected,access){
 const [messages,setMessages]=useState([]),[voice,setVoice]=useState(false),[error,setError]=useState(''),[startingVoice,setStartingVoice]=useState(false);
 const [muted,setMutedState]=useState(false),[deafened,setDeafened]=useState(false),[settings,setSettingsState]=useState(readSettings),[devices,setDevices]=useState({inputs:[],outputs:[]});
 const [links,setLinks]=useState({}),[speaking,setSpeaking]=useState({}),[inputLevel,setInputLevel]=useState(0),[relay,setRelay]=useState(null);
 const stream=useRef(null),raw=useRef(null),gain=useRef(null),peers=useRef(new Map()),meters=useRef(new Map()),live=useRef({}),mounted=useRef(true),starting=useRef(false),ice=useRef(null);
 live.current={memberId,room,connected,access,settings,muted,deafened};
 const send=value=>{if(socket.current?.readyState===1)socket.current.send(JSON.stringify(value));};
 const publish=()=>{if(!mounted.current)return;const value={};for(const [id,p] of peers.current)value[id]={state:p.pc.connectionState,relay:p.relay};setLinks(value);};
 function setSettings(change){setSettingsState(old=>{const next={...old,...change};writeSettings(next);return next;});}
 async function listDevices(){try{const all=await navigator.mediaDevices.enumerateDevices();if(mounted.current)setDevices({inputs:all.filter(d=>d.kind==='audioinput'),outputs:all.filter(d=>d.kind==='audiooutput')});}catch{}}
 function drop(id){const value=peers.current.get(id);if(!value)return;value.pc.close();value.audio.pause();value.audio.srcObject=null;clearTimeout(value.timer);meters.current.get(id)?.close();meters.current.delete(id);peers.current.delete(id);publish();}
 function releaseInput(){raw.current?.getTracks().forEach(t=>t.stop());raw.current=null;meters.current.get('self')?.close();meters.current.delete('self');try{gain.current?.source.disconnect();gain.current?.node.disconnect();}catch{}gain.current=null;}
 function stop(){send({type:'voice',enabled:false});for(const id of [...peers.current.keys()])drop(id);releaseInput();stream.current=null;if(mounted.current){setVoice(false);setInputLevel(0);setSpeaking({});}}
 // The sent track goes through a gain node so input volume works on every
 // browser; constraints (device, echo/noise processing) come from settings.
 async function openInput(current){
  const value=await navigator.mediaDevices.getUserMedia({audio:{...(current.inputId?{deviceId:{exact:current.inputId}}:{}),echoCancellation:current.echoCancellation,noiseSuppression:current.noiseSuppression,autoGainControl:current.autoGainControl,channelCount:VOICE_PROFILES[current.profile]?.stereo?2:1},video:false});
  const ctx=context();let out=value;
  if(ctx){const source=ctx.createMediaStreamSource(value),node=ctx.createGain(),destination=ctx.createMediaStreamDestination();node.gain.value=current.inputGain;source.connect(node).connect(destination);gain.current={source,node};out=destination.stream;}
  raw.current=value;out.getAudioTracks().forEach(t=>{t.enabled=!live.current.muted;});
  meters.current.get('self')?.close();meters.current.set('self',meter(out));
  return out;
 }
 async function tune(sender){const profile=VOICE_PROFILES[live.current.settings.profile]||VOICE_PROFILES.voice;try{const parameters=sender.getParameters();parameters.encodings=parameters.encodings?.length?parameters.encodings:[{}];parameters.encodings[0].maxBitrate=profile.bitrate;await sender.setParameters(parameters);}catch{}}
 function link(id){
  if(peers.current.has(id))return peers.current.get(id);if(!stream.current||!ice.current)return null;
  const pc=new RTCPeerConnection({iceServers:ice.current.iceServers}),audio=new Audio();audio.autoplay=true;
  audio.volume=Math.min(1,live.current.settings.volumes?.[id]??1);audio.muted=live.current.deafened;
  if(live.current.settings.outputId&&audio.setSinkId)audio.setSinkId(live.current.settings.outputId).catch(()=>{});
  const value={pc,audio,pending:[],relay:false,restarted:false,timer:setTimeout(()=>{if(!['connected','completed'].includes(pc.iceConnectionState)&&mounted.current)setError(ice.current?.relay?'Не удалось соединить голос даже через ретранслятор. Проверь сеть участника.':'Прямое соединение не удалось, а голосовой ретранслятор (TURN) на сервере ещё не включён.');},20000)};
  peers.current.set(id,value);publish();
  stream.current.getTracks().forEach(track=>tune(pc.addTrack(track,stream.current)));
  pc.onicecandidate=event=>{if(event.candidate)send({type:'signal',to:id,payload:{candidate:event.candidate.toJSON()}});};
  pc.ontrack=event=>{audio.srcObject=event.streams[0];meters.current.get(id)?.close();meters.current.set(id,meter(event.streams[0]));audio.play().catch(()=>setError('Нажми «Включить звук беседы», чтобы браузер разрешил голос.'));};
  pc.onconnectionstatechange=async()=>{
   if(pc.connectionState==='connected'){clearTimeout(value.timer);setError('');try{const stats=await pc.getStats();stats.forEach(s=>{if(s.type==='candidate-pair'&&s.state==='succeeded'&&s.nominated){const local=stats.get(s.localCandidateId);value.relay=local?.candidateType==='relay';}});}catch{}}
   // One ICE restart: networks change (Wi-Fi to mobile) mid-episode.
   if(pc.connectionState==='failed'&&!value.restarted&&memberId<id){value.restarted=true;try{const offer=await pc.createOffer({iceRestart:true});await pc.setLocalDescription(offer);send({type:'signal',to:id,payload:{description:pc.localDescription.toJSON()}});}catch{}}
   else if(pc.connectionState==='failed')setError('Голосовой канал прерван. Переподключи микрофон.');
   publish();
  };
  return value;
 }
 async function start(){
  if(starting.current||stream.current)return;starting.current=true;setStartingVoice(true);setError('');
  try{
   if(!navigator.mediaDevices?.getUserMedia||!window.RTCPeerConnection)throw Error('Голосовой чат недоступен в этом браузере.');
   const access=live.current.access;ice.current=access?.server&&access?.id&&access?.token?await iceConfiguration(access):{iceServers:[{urls:'stun:stun.l.google.com:19302'}],relay:false};
   if(mounted.current)setRelay(ice.current.relay);
   const value=await openInput(live.current.settings);
   if(!mounted.current||!live.current.connected){value.getTracks().forEach(t=>t.stop());releaseInput();return;}
   stream.current=value;setVoice(true);send({type:'voice',enabled:true,muted:live.current.muted});listDevices();
  }catch(e){releaseInput();setError(e.name==='NotAllowedError'?'Разреши доступ к микрофону.':e.name==='NotFoundError'||e.name==='OverconstrainedError'?'Выбранный микрофон не найден. Выбери другой в настройках голоса.':e.message);}
  finally{starting.current=false;if(mounted.current)setStartingVoice(false);}
 }
 // Device or processing change: replace the outgoing track without renegotiation.
 async function applyInput(change){
  const next={...live.current.settings,...change};setSettings(change);if(!stream.current)return;
  if(Object.keys(change).every(k=>k==='inputGain')){if(gain.current)gain.current.node.gain.value=next.inputGain;return;}
  try{releaseInput();const value=await openInput(next);stream.current=value;const track=value.getAudioTracks()[0];
   for(const p of peers.current.values())for(const sender of p.pc.getSenders())if(sender.track?.kind==='audio'||!sender.track){await sender.replaceTrack(track);tune(sender);}
  }catch(e){setError(e.name==='NotAllowedError'?'Разреши доступ к микрофону.':'Не удалось переключить микрофон.');}
 }
 function setMuted(value){setMutedState(value);stream.current?.getAudioTracks().forEach(t=>{t.enabled=!value;});if(stream.current)send({type:'voice',enabled:true,muted:value});}
 function deafen(value){setDeafened(value);for(const p of peers.current.values())p.audio.muted=value;if(value&&!live.current.muted)setMuted(true);}
 function setVolume(id,value){const volumes={...live.current.settings.volumes,[id]:value};setSettings({volumes});const p=peers.current.get(id);if(p)p.audio.volume=Math.min(1,value);}
 function setOutput(id){setSettings({outputId:id});for(const p of peers.current.values())p.audio.setSinkId?.(id).catch(()=>{});}
 async function receive(data){
  if(data.type==='chat'&&typeof data.text==='string'&&typeof data.name==='string'){setMessages(old=>[...old.filter(x=>x.id!==data.id),data].slice(-80));return;}
  if(data.type!=='signal'||!stream.current||!live.current.room?.members.some(m=>m.id===data.from&&m.online&&m.voice))return;
  try{const value=link(data.from);if(!value)return;const payload=data.payload;if(payload.description){await value.pc.setRemoteDescription(payload.description);for(const candidate of value.pending.splice(0))await value.pc.addIceCandidate(candidate);if(payload.description.type==='offer'){await value.pc.setLocalDescription(await value.pc.createAnswer());send({type:'signal',to:data.from,payload:{description:value.pc.localDescription.toJSON()}});}}else if(payload.candidate){if(value.pc.remoteDescription)await value.pc.addIceCandidate(payload.candidate);else value.pending.push(payload.candidate);}}catch{setError('Не удалось согласовать голосовой канал. Переподключи микрофон.');}
 }
 useEffect(()=>{if(!voice||!connected)return;const members=room?.members||[];for(const [id] of peers.current)if(!members.some(m=>m.id===id&&m.online&&m.voice))drop(id);for(const member of members){if(member.id===memberId||!member.online||!member.voice||memberId>member.id||peers.current.has(member.id))continue;const value=link(member.id);if(value)value.pc.createOffer().then(offer=>value.pc.setLocalDescription(offer)).then(()=>send({type:'signal',to:member.id,payload:{description:value.pc.localDescription.toJSON()}})).catch(()=>setError('Не удалось создать голосовой канал.'));}},[room?.members,memberId,voice,connected]);
 // ~12 Hz speaking indicators; state changes only when someone starts/stops.
 useEffect(()=>{if(!voice)return;let frame=0;const timer=setInterval(()=>{const next={};for(const [id,m] of meters.current){const level=m?.level()||0;if(id==='self'){if(++frame%2===0)setInputLevel(live.current.muted?0:level);next[memberId]=!live.current.muted&&level>.08;}else next[id]=!live.current.deafened&&level>.06;}setSpeaking(old=>Object.keys(next).length===Object.keys(old).length&&Object.entries(next).every(([k,v])=>old[k]===v)?old:next);},80);return()=>clearInterval(timer);},[voice,memberId]);
 useEffect(()=>{if(!navigator.mediaDevices?.addEventListener)return;navigator.mediaDevices.addEventListener('devicechange',listDevices);listDevices();return()=>navigator.mediaDevices.removeEventListener('devicechange',listDevices);},[]);
 useEffect(()=>{if(!connected)stop();},[connected]);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;stop();};},[]);
 useEffect(()=>{setMessages([]);},[memberId]);
 const peerCount=Object.values(links).filter(v=>v.state==='connected').length;
 return {members:room?.members||[],messages,voice,peers:peerCount,links,speaking,inputLevel,relay,muted,deafened,settings,devices,error,starting:startingVoice,start,stop,receive,setMuted,deafen,setVolume,setOutput,applyInput,memberId,
  post:text=>{const value=text.trim().slice(0,500);if(value&&connected)send({type:'chat',text:value});},
  unlock:async()=>{const results=await Promise.allSettled([...peers.current.values()].map(value=>value.audio.play()));context();if(mounted.current&&results.every(value=>value.status==='fulfilled'))setError('');},connected};
}
