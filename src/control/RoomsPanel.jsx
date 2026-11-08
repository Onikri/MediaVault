import {useState} from 'react';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {Check,Copy,DoorClosed,ExternalLink,Mic,MicOff,MessageSquare} from 'lucide-react';
import {roomLink} from '../watch-room.js';
import {useNow,left,plural} from './use-control-data.js';
import {Poster,Timeline,usePosters} from './parts.jsx';

function CloseRoom({room,service,onClosed}){
 const [asking,setAsking]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 async function close(){setBusy(true);setError('');try{await service.request('/rooms/'+encodeURIComponent(room.id),{method:'DELETE'});onClosed(room.id);}catch(e){setError(e.message);setBusy(false);}}
 return <div className="cc-close">
  <AnimatePresence mode="wait" initial={false}>{asking?<motion.div key="ask" className="cc-confirm" initial={{opacity:0,x:8}} animate={{opacity:1,x:0}} exit={{opacity:0,x:8}} transition={{duration:.16}}>
   <span>Все участники выйдут из комнаты.</span>
   <button type="button" className="cc-button is-danger" disabled={busy} onClick={close}>{busy?'Закрываем…':'Закрыть'}</button>
   <button type="button" className="cc-button" disabled={busy} onClick={()=>setAsking(false)}>Отмена</button>
  </motion.div>:<motion.button key="close" type="button" className="cc-button" onClick={()=>setAsking(true)} initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} transition={{duration:.12}}><DoorClosed size={15}/>Закрыть комнату</motion.button>}</AnimatePresence>
  {error&&<p className="cc-error" role="alert">{error}</p>}
 </div>;
}

function CopyRoom({id}){
 const [copied,setCopied]=useState(false);
 return <button type="button" className="cc-button" onClick={()=>navigator.clipboard?.writeText(roomLink(id)).then(()=>{setCopied(true);setTimeout(()=>setCopied(false),1600);})}>{copied?<Check size={15}/>:<Copy size={15}/>}{copied?'Ссылка скопирована':'Скопировать ссылку'}</button>;
}

export default function RoomsPanel({data,service,onOpenRoom,onRules}){
 const reduce=useReducedMotion(),now=useNow(1000);
 const rooms=data.rooms,rules=data.roomRules,guests=data.guests||[];
 const posters=usePosters(service,(rooms||[]).map(r=>r.malId));
 const closed=id=>data.patch(old=>({rooms:(old.rooms||[]).filter(r=>r.id!==id)}));
 if(data.errors.rooms&&!rooms)return <p className="cc-error" role="alert">{data.errors.rooms}</p>;
 if(!rooms)return <p className="cc-hint">Загружаем комнаты…</p>;
 const people=rooms.reduce((t,r)=>t+r.members.filter(m=>m.online).length,0);
 return <div className="cc-rooms">
  <dl className="cc-facts">
   <div><dt>Открыто</dt><dd className="cc-num">{rooms.length}{rules?<small> из {rules.limit}</small>:null}</dd></div>
   <div><dt>Внутри сейчас</dt><dd className="cc-num">{people}</dd></div>
   {rules&&<div><dt>Ссылка живёт</dt><dd className="cc-num">{rules.hours} ч</dd></div>}
   {rules&&<div><dt>Мест в комнате</dt><dd className="cc-num">{rules.members}</dd></div>}
   <div className="cc-facts-action"><button type="button" className="cc-text-button" onClick={onRules}>Изменить правила комнат</button></div>
  </dl>
  {!rooms.length&&<div className="cc-quiet"><p>Открытых комнат нет.</p><p className="cc-hint">Комнату открывает ведущий в плеере кнопкой «Смотреть вместе». Здесь появятся все комнаты на сервере — и твои, и гостевые.</p></div>}
  <ul className="cc-room-list"><AnimatePresence initial={false}>{rooms.map(room=>{
   const host=room.guest?guests.find(g=>g.id===room.guest)?.name||'гость':'ты';
   return <motion.li key={room.id} className="cc-room" layout={!reduce} initial={reduce?false:{opacity:0,y:12}} animate={{opacity:1,y:0}} exit={reduce?{opacity:0}:{opacity:0,scale:.98,transition:{duration:.18}}} transition={{duration:.3,ease:[.22,1,.36,1]}}>
    <Poster src={posters[room.malId]?.cover} title={room.title}/>
    <div className="cc-room-main">
     <header className="cc-room-head">
      <h3>{room.title}</h3>
      <p>Ведущий: {host}{room.hostOnline?'':', сейчас не в комнате'}. Закроется через {left(room.expiresAt,now)}.</p>
     </header>
     <Timeline room={room} fetchedAt={data.updatedAt} now={now}/>
     <ul className="cc-members" aria-label="Участники">{room.members.map(m=><li key={m.id} className={m.online?'is-online':''}>
      {m.avatar&&<img src={service.server+m.avatar} alt="" referrerPolicy="no-referrer"/>}
      <span>{m.name}</span>
      {m.host&&<small>ведущий</small>}
      {m.buffering&&m.online&&<small className="is-warn">загружает</small>}
      {m.voice&&(m.muted?<MicOff size={13} aria-label="Микрофон выключен"/>:<Mic size={13} aria-label="Говорит в голосовом чате"/>)}
      {!m.online&&<small>не в сети</small>}
     </li>)}</ul>
     <footer className="cc-room-foot">
      <span className="cc-hint"><MessageSquare size={14}/>{room.messages} {plural(room.messages,'сообщение','сообщения','сообщений')}, {room.everyone?'управляют все':'управляет ведущий'}{room.waitAll?', ждём отстающих':''}</span>
      <div className="cc-room-actions">
       {onOpenRoom&&<button type="button" className="cc-button" onClick={()=>onOpenRoom(room.id)}><ExternalLink size={15}/>Открыть лобби</button>}
       <CopyRoom id={room.id}/>
       <CloseRoom room={room} service={service} onClosed={closed}/>
      </div>
     </footer>
    </div>
   </motion.li>;})}</AnimatePresence></ul>
 </div>;
}
