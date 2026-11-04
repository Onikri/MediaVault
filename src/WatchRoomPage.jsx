import RoomConversation from './RoomConversation.jsx';
import {useRoomConversation} from './room-conversation.js';
import {useEffect,useRef,useState,useMemo} from 'react';
import {Users,LogOut} from 'lucide-react';
import MediaVaultPlayer from './MediaVaultPlayer.jsx';
import TitleShowcase from './TitleShowcase.jsx';
import TitleBackdrop from './TitleBackdrop.jsx';
import Artwork from './Artwork.jsx';
import {loadTitleProfile} from './title-metadata.js';
import {roomSocket,applyRoomState} from './watch-room.js';
import {validateServer} from './import-service.js';
import './watch-room.css';
export default function WatchRoomPage({identity}){
 const [password,setPassword]=useState(''),[name,setName]=useState(''),[joined,setJoined]=useState(null),[state,setState]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[api,setApi]=useState(null),[profile,setProfile]=useState(null),[online,setOnline]=useState(false),[blocked,setBlocked]=useState(false);
 const socket=useRef(null),applying=useRef(0),latest=useRef();latest.current={api,state};
 let server='';try{server=validateServer(window.MEDIA_VAULT_CONFIG?.importServerUrl||'');}catch{}
 const conversation=useRoomConversation(socket,joined?.memberId,state,online);
 function send(data){if(socket.current?.readyState===1)socket.current.send(JSON.stringify(data));}
 async function join(event,secret=password){event?.preventDefault();setBusy(true);setError('');try{const response=await fetch(server+'/rooms/'+encodeURIComponent(identity)+'/join',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:secret,name:name.trim()||'Гость'})}),data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Не удалось войти в комнату.');setPassword('');setJoined(data);setState(data.room);}catch(e){setError(e.message);}finally{setBusy(false);}}
 useEffect(()=>{const params=new URLSearchParams(location.hash.slice(1)),secret=params.get('key');if(secret){params.delete('key');history.replaceState(null,'',location.pathname+location.search+'#'+params.toString());join(null,secret);}},[identity]);
 useEffect(()=>{
 if(!joined)return;
  const connection=roomSocket(server,identity,joined.token,data=>{
   conversation.receive(data);
   if(data.type==='state'){latest.current.state=data.room;lastState.current=performance.now();setState(data.room);applying.current=performance.now()+500;applyRoomState(latest.current.api?.media,data.room,{onBlocked:()=>setBlocked(true)});}
   else if(data.type==='closed'){setError('Создатель закрыл комнату.');setJoined(null);}
   else if(data.type==='error')setError(data.message);
  },status=>setOnline(status==='connected'));socket.current=connection;return()=>connection.close();
 },[joined?.token,server,identity]);
 useEffect(()=>{if(!state?.malId)return;const abort=new AbortController();loadTitleProfile(state.malId,'anime',{server,signal:abort.signal}).then(setProfile).catch(()=>{});return()=>abort.abort();},[state?.malId,server]);
 useEffect(()=>{
  if(!api||!joined)return;const media=api.media;
  const waiting=()=>{if(media.readyState<3)send({type:'buffer',value:true});},ready=()=>{if(media.readyState>=3)send({type:'buffer',value:false});applyRoomState(media,latest.current.state,{onBlocked:()=>setBlocked(true)});};
  media.addEventListener('waiting',waiting);media.addEventListener('canplay',ready);media.addEventListener('loadeddata',ready);media.addEventListener('seeked',ready);media.addEventListener('playing',ready);ready();
  const clock=setInterval(()=>{if(latest.current.state?.playing&&media.readyState>=2){const current=latest.current.state;applyRoomState(media,{...current,position:current.position+Math.max(0,(performance.now()-lastState.current)/1000)*current.rate});}},1500);
  return()=>{clearInterval(clock);media.removeEventListener('waiting',waiting);media.removeEventListener('canplay',ready);media.removeEventListener('loadeddata',ready);media.removeEventListener('seeked',ready);media.removeEventListener('playing',ready);};
 },[api,joined?.token,state?.epoch]);
 useEffect(()=>{if(api)api.preferences({audioOffset:state?.audioOffset||0});},[api,state?.audioOffset]);
 const lastState=useRef(performance.now());useEffect(()=>{lastState.current=performance.now();},[state]);
  const roomItem=useMemo(()=>({id:'room:'+identity+':'+state?.epoch,name:state?.title,category:'video',onlineType:state?.type}),[identity,state?.epoch,state?.title,state?.type]);
 if(!joined)return <main className="watch-room-gate"><div><Users size={30}/><h1>Совместный просмотр</h1><p>Введи пароль, который передал создатель комнаты.</p><form onSubmit={join}><label>Имя<input aria-label="Имя в комнате" maxLength={40} value={name} onChange={e=>setName(e.target.value)} autoComplete="nickname"/></label><label>Пароль комнаты<input type="password" aria-label="Пароль комнаты" maxLength={128} value={password} onChange={e=>setPassword(e.target.value)} autoComplete="current-password" required/></label><button className="btn btn-primary" disabled={busy||!password||!server}>{busy?'Подключаемся…':'Войти в комнату'}</button></form>{error&&<p className="inline-error" role="alert">{error}</p>}</div></main>;
 const canControl=state?.everyone||state?.leader===joined.memberId;
 const p=profile||{title:state?.title,description:'Совместный просмотр',cover:'',backgrounds:[]};
 const resource=state?.resource||'file',source=server+'/rooms/'+identity+'/media/'+joined.token+'/'+resource+'?epoch='+state?.epoch;
 const trackUrl=track=>server+'/rooms/'+identity+'/media/'+joined.token+'/'+track.alias+'?epoch='+state?.epoch;
 const audio=state?.tracks?.find(t=>t.kind==='audio'),captions=(state?.tracks||[]).filter(t=>t.kind==='caption');
 const hostOnline=state?.members.some(m=>m.host&&m.online);
 return <main className="watch-room-page title-page"><TitleShowcase background={sceneStyle=><TitleBackdrop inline sceneStyle={sceneStyle} server={server} identity={state?.malId} profile={p} trailer={p.trailer} actions={{}} onPalette={()=>{}}/>}><div className="title-poster">{p.cover?<img src={p.cover} alt=""/>:<Artwork kind="anime"/>}</div><div className="title-hero-copy"><p className="eyebrow">Совместный просмотр</p><h1>{p.title||state?.title}</h1><p className="title-hero-description">{p.description}</p><div className="title-genre-list">{(p.genres||[]).slice(0,5).map(g=><span key={g}>{g}</span>)}</div><p className="fine">{state?.members.filter(m=>m.online).length} участн. · {canControl?'Ты можешь управлять плеером':'Управляет ведущий'}</p></div><aside className="title-facts"><h2>Сейчас в комнате</h2><dl><div><dt>Ведущий</dt><dd>{state?.members.find(m=>m.id===state.leader)?.name||'Создатель'}</dd></div><div><dt>Участников</dt><dd>{state?.members.filter(m=>m.online).length}</dd></div><div><dt>Управление</dt><dd>{state?.everyone?'Все участники':'Ведущий'}</dd></div></dl></aside></TitleShowcase><section className="room-playback"><div className="room-status"><span role="status">{!online?'Соединение прервано':!hostOnline?'Ведущий отключён':state?.held?'Ждём буферизацию участников':'В комнате'}</span><button className="text-link" onClick={()=>{socket.current?.close();setJoined(null);}}><LogOut size={16}/>Выйти</button></div>{blocked&&<button className="btn btn-primary" onClick={()=>{setBlocked(false);applyRoomState(api?.media,state,{onBlocked:()=>setBlocked(true)});}}>Начать совместный просмотр</button>}<MediaVaultPlayer apiRef={setApi} item={roomItem} source={source} onlineControls={{audio:audio?{url:trackUrl(audio),type:audio.type}:undefined,externalCaptions:captions.map(t=>({...t,url:trackUrl(t)}))}} catalog={{items:[]}} libraryId={'room:'+identity} userId="guest" onError={e=>{if(e.name!=='AbortError')setError(e.message);}} roomControl={{canControl,playing:!!state?.playing,command:(action,position)=>{send({type:'command',action,position});}}}/><RoomConversation conversation={conversation}/>{error&&<p className="inline-error" role="alert">{error}</p>}</section></main>;
}
