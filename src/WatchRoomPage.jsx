import RoomConversation from './RoomConversation.jsx';
import {useRoomConversation} from './room-conversation.js';
import {useEffect,useRef,useState,useMemo} from 'react';
import {Users,LogOut,Clock3,Crown,Play,Radio} from 'lucide-react';
import {clock} from './player-runtime.js';
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
 const [preview,setPreview]=useState(null),[previewProfile,setPreviewProfile]=useState(null);
 // Lobby showcase: public room summary (no media or member tokens) so the
 // gate shows what is about to be watched before the password is entered.
 useEffect(()=>{if(joined||!server)return;const abort=new AbortController();const load=()=>fetch(server+'/rooms/'+encodeURIComponent(identity)+'/preview',{signal:abort.signal}).then(r=>r.ok?r.json():null).then(v=>{if(!abort.signal.aborted)setPreview(v);}).catch(()=>{});load();const timer=setInterval(load,10000);return()=>{abort.abort();clearInterval(timer);};},[identity,server,joined]);
 useEffect(()=>{if(!preview?.malId)return;const abort=new AbortController();loadTitleProfile(preview.malId,'anime',{server,signal:abort.signal}).then(setPreviewProfile).catch(()=>{});return()=>abort.abort();},[preview?.malId,server]);
 const conversation=useRoomConversation(socket,joined?.memberId,state,online,{server,id:joined?.id||identity,token:joined?.token});
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
 if(!joined){
  const g=previewProfile||{},title=g.title||preview?.title,duration=preview?.duration||0,progress=duration?Math.min(100,(preview?.position||0)/duration*100):0;
  return <main className="watch-room-gate room-lobby" style={g.cover?{'--lobby-art':`url("${String(g.cover).replace(/["\\]/g,'')}")`}:undefined}>
   <div className="room-lobby-backdrop" aria-hidden="true"/>
   <section className="room-lobby-card">
    <div className="room-lobby-show">
     <div className="room-lobby-poster">{g.cover?<img src={g.cover} alt=""/>:<Artwork kind="anime"/>}{preview?.playing&&<span className="room-lobby-live"><Radio size={12}/>Идёт просмотр</span>}</div>
     <div className="room-lobby-copy">
      <p className="eyebrow">Совместный просмотр</p>
      <h1>{title||'Комната просмотра'}</h1>
      {g.description&&<p className="room-lobby-description">{g.description}</p>}
      <div className="room-lobby-facts">{duration>0&&<span><Clock3 size={14}/>{clock(duration)}</span>}{(g.genres||[]).slice(0,3).map(v=><span key={v}>{v}</span>)}</div>
      {duration>0&&<div className="room-lobby-progress" aria-label={'Позиция просмотра '+clock(preview.position||0)+' из '+clock(duration)}><span style={{width:progress+'%'}}/><small>{preview.playing?<Play size={11}/>:null}{clock(preview.position||0)} / {clock(duration)}</small></div>}
      {preview&&<div className="room-lobby-people"><div className="room-lobby-avatars">{preview.names.map((n,i)=><span key={i} title={n}>{String(n).trim().slice(0,1).toUpperCase()}</span>)}</div><small>{preview.host&&<><Crown size={12}/>{preview.host} · </>}{preview.online} в комнате</small></div>}
     </div>
    </div>
    <form className="room-lobby-form" onSubmit={join}>
     <label>Имя<input aria-label="Имя в комнате" maxLength={40} value={name} onChange={e=>setName(e.target.value)} autoComplete="nickname" placeholder="Как тебя называть"/></label>
     <label>Пароль комнаты<input type="password" aria-label="Пароль комнаты" maxLength={128} value={password} onChange={e=>setPassword(e.target.value)} autoComplete="current-password" required/></label>
     <button className="btn btn-primary" disabled={busy||!password||!server}><Users size={16}/>{busy?'Подключаемся…':'Войти в комнату'}</button>
     {error&&<p className="inline-error" role="alert">{error}</p>}
    </form>
   </section>
  </main>;
 }
 const canControl=state?.everyone||state?.leader===joined.memberId;
 const p=profile||{title:state?.title,description:'Совместный просмотр',cover:'',backgrounds:[]};
 const resource=state?.resource||'file',source=server+'/rooms/'+identity+'/media/'+joined.token+'/'+resource+'?epoch='+state?.epoch;
 const trackUrl=track=>server+'/rooms/'+identity+'/media/'+joined.token+'/'+track.alias+'?epoch='+state?.epoch;
 const audio=state?.tracks?.find(t=>t.kind==='audio'),captions=(state?.tracks||[]).filter(t=>t.kind==='caption');
 const hostOnline=state?.members.some(m=>m.host&&m.online);
 return <main className="watch-room-page title-page"><TitleShowcase background={sceneStyle=><TitleBackdrop inline sceneStyle={sceneStyle} server={server} identity={state?.malId} profile={p} trailer={p.trailer} actions={{}} onPalette={()=>{}}/>}><div className="title-poster">{p.cover?<img src={p.cover} alt=""/>:<Artwork kind="anime"/>}</div><div className="title-hero-copy"><p className="eyebrow">Совместный просмотр</p><h1>{p.title||state?.title}</h1><p className="title-hero-description">{p.description}</p><div className="title-genre-list">{(p.genres||[]).slice(0,5).map(g=><span key={g}>{g}</span>)}</div><p className="fine">{state?.members.filter(m=>m.online).length} участн. · {canControl?'Ты можешь управлять плеером':'Управляет ведущий'}</p></div><aside className="title-facts"><h2>Сейчас в комнате</h2><dl><div><dt>Ведущий</dt><dd>{state?.members.find(m=>m.id===state.leader)?.name||'Создатель'}</dd></div><div><dt>Участников</dt><dd>{state?.members.filter(m=>m.online).length}</dd></div><div><dt>Управление</dt><dd>{state?.everyone?'Все участники':'Ведущий'}</dd></div></dl></aside></TitleShowcase><section className="room-playback"><div className="room-status"><span role="status">{!online?'Соединение прервано':!hostOnline?'Ведущий отключён':state?.held?'Ждём буферизацию участников':'В комнате'}</span><button className="text-link" onClick={()=>{socket.current?.close();setJoined(null);}}><LogOut size={16}/>Выйти</button></div>{blocked&&<button className="btn btn-primary" onClick={()=>{setBlocked(false);applyRoomState(api?.media,state,{onBlocked:()=>setBlocked(true)});}}>Начать совместный просмотр</button>}<div className="room-playback-layout"><MediaVaultPlayer apiRef={setApi} item={roomItem} source={source} onlineControls={{audio:audio?{url:trackUrl(audio),type:audio.type}:undefined,externalCaptions:captions.map(t=>({...t,url:trackUrl(t)}))}} catalog={{items:[]}} libraryId={'room:'+identity} userId="guest" onPlaybackRecovered={()=>{setError('');setBlocked(false);}} onError={e=>{if(e.name!=='AbortError')setError(e.message);}} roomControl={{canControl,playing:!!state?.playing,command:(action,position)=>{send({type:'command',action,position});}}}/><RoomConversation conversation={conversation}/></div>{error&&<p className="inline-error" role="alert">{error}</p>}</section></main>;
}
