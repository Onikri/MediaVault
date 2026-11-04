import {useEffect,useRef,useState} from 'react';
// Room-scoped signalling only. Audio goes peer to peer, never into playback.
export function useRoomConversation(socket,memberId,room,connected){
 const [messages,setMessages]=useState([]),[voice,setVoice]=useState(false),[error,setError]=useState(''),[peers,setPeers]=useState(0),stream=useRef(null),links=useRef(new Map()),live=useRef({}),mounted=useRef(true),starting=useRef(false);live.current={memberId,room,connected};
 const send=value=>{if(socket.current?.readyState===1)socket.current.send(JSON.stringify(value));};
 function drop(id){const value=links.current.get(id);if(!value)return;value.pc.close();value.audio.pause();value.audio.srcObject=null;clearTimeout(value.timer);links.current.delete(id);if(mounted.current)setPeers(links.current.size);}
 function stop(){send({type:'voice',enabled:false});for(const id of [...links.current.keys()])drop(id);stream.current?.getTracks().forEach(t=>t.stop());stream.current=null;if(mounted.current)setVoice(false);}
 function link(id){
  if(links.current.has(id))return links.current.get(id);if(!stream.current)return null;
  const configured=window.MEDIA_VAULT_CONFIG?.roomIceServers;
  const pc=new RTCPeerConnection({iceServers:Array.isArray(configured)&&configured.length?configured:[{urls:'stun:stun.l.google.com:19302'}]}),audio=new Audio();audio.autoplay=true;
  const value={pc,audio,pending:[],timer:setTimeout(()=>{if(!['connected','completed'].includes(pc.iceConnectionState)&&mounted.current)setError('Не удалось соединить микрофоны напрямую. Для этой сети нужен TURN-релей.');},15000)};links.current.set(id,value);setPeers(links.current.size);
  stream.current.getTracks().forEach(track=>pc.addTrack(track,stream.current));
  pc.onicecandidate=event=>{if(event.candidate)send({type:'signal',to:id,payload:{candidate:event.candidate.toJSON()}});};
  pc.ontrack=event=>{audio.srcObject=event.streams[0];audio.play().catch(()=>setError('Нажми «Включить звук беседы», чтобы браузер разрешил голос.'));};
  pc.onconnectionstatechange=()=>{if(pc.connectionState==='connected')clearTimeout(value.timer);if(pc.connectionState==='failed')setError('Голосовой канал прерван. Переподключи микрофон.');};return value;
 }
 async function start(){if(starting.current||stream.current)return;starting.current=true;setError('');try{if(!navigator.mediaDevices?.getUserMedia||!window.RTCPeerConnection)throw Error('Голосовой чат недоступен в этом браузере.');const value=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});if(!mounted.current||!live.current.connected){value.getTracks().forEach(t=>t.stop());return;}stream.current=value;setVoice(true);send({type:'voice',enabled:true});}catch(e){setError(e.name==='NotAllowedError'?'Разреши доступ к микрофону.':e.message);}finally{starting.current=false;}}
 async function receive(data){
  if(data.type==='chat'&&typeof data.text==='string'&&typeof data.name==='string'){setMessages(old=>[...old.filter(x=>x.id!==data.id),data].slice(-80));return;}
  if(data.type!=='signal'||!stream.current||!live.current.room?.members.some(m=>m.id===data.from&&m.online&&m.voice))return;
  try{const value=link(data.from);if(!value)return;const payload=data.payload;if(payload.description){await value.pc.setRemoteDescription(payload.description);for(const candidate of value.pending.splice(0))await value.pc.addIceCandidate(candidate);if(payload.description.type==='offer'){await value.pc.setLocalDescription(await value.pc.createAnswer());send({type:'signal',to:data.from,payload:{description:value.pc.localDescription.toJSON()}});}}else if(payload.candidate){if(value.pc.remoteDescription)await value.pc.addIceCandidate(payload.candidate);else value.pending.push(payload.candidate);}}catch{setError('Не удалось согласовать голосовой канал. Переподключи микрофон.');}
 }
 useEffect(()=>{if(!voice||!connected)return;const members=room?.members||[];for(const [id] of links.current)if(!members.some(m=>m.id===id&&m.online&&m.voice))drop(id);for(const member of members){if(member.id===memberId||!member.online||!member.voice||memberId>member.id||links.current.has(member.id))continue;const value=link(member.id);if(value)value.pc.createOffer().then(offer=>value.pc.setLocalDescription(offer)).then(()=>send({type:'signal',to:member.id,payload:{description:value.pc.localDescription.toJSON()}})).catch(()=>setError('Не удалось создать голосовой канал.'));}},[room?.members,memberId,voice,connected]);
 useEffect(()=>{if(!connected)stop();},[connected]);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;stop();};},[]);
 useEffect(()=>{setMessages([]);},[memberId]);
 return {messages,voice,peers,error,start,stop,receive,post:text=>{const value=text.trim().slice(0,500);if(value&&connected)send({type:'chat',text:value});},unlock:()=>{for(const value of links.current.values())value.audio.play().catch(()=>{});},connected};
}
