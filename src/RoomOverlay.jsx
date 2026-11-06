import {useEffect,useRef,useState} from 'react';
import {Headphones,HeadphoneOff,Mic,MicOff,PhoneOff,Send,Volume2,VolumeX,ChevronRight,ChevronLeft,Settings2} from 'lucide-react';

// Fullscreen room overlay, in the spirit of a game voice overlay: who is here and
// speaking, voice controls, the last messages. Semi-transparent, pinned to the right.
export default function RoomOverlay({conversation,onOpenRoom}){
 const [open,setOpen]=useState(true),[text,setText]=useState(''),list=useRef(null);
 const online=(conversation.members||[]).filter(m=>m.online).sort((a,b)=>Number(b.voice)-Number(a.voice));
 const recent=conversation.messages.slice(-5);
 useEffect(()=>{if(list.current)list.current.scrollTop=list.current.scrollHeight;},[conversation.messages,open]);
 if(!open)return <button type="button" className="mvx-overlay-tab" aria-label="Показать комнату" onClick={()=>setOpen(true)}><ChevronLeft size={16}/><span>{online.length}</span></button>;
 return <aside className="mvx-overlay" aria-label="Комната поверх видео">
  <header><strong>Комната</strong><small>{online.length} в комнате</small>
   <button type="button" aria-label="Настройки комнаты" onClick={onOpenRoom}><Settings2 size={15}/></button>
   <button type="button" aria-label="Свернуть комнату" onClick={()=>setOpen(false)}><ChevronRight size={16}/></button>
  </header>
  <ul className="mvx-overlay-members">{online.map(m=>{
   const self=m.id===conversation.memberId,speaking=!!conversation.speaking[m.id],volume=conversation.settings.volumes?.[m.id]??1;
   return <li key={m.id} data-speaking={speaking||undefined} data-voice={m.voice||undefined}>
    <span className="mvx-overlay-name">{m.name}{self?' (ты)':''}</span>
    {m.voice&&m.muted&&<MicOff size={13} aria-label="Микрофон выключен"/>}
    {!self&&m.voice&&<button type="button" aria-label={(volume===0?'Включить звук: ':'Заглушить: ')+m.name} aria-pressed={volume===0} onClick={()=>conversation.setVolume(m.id,volume===0?1:0)}>{volume===0?<VolumeX size={14}/>:<Volume2 size={14}/>}</button>}
   </li>;})}</ul>
  <div className="mvx-overlay-voice">
   {!conversation.voice?<button type="button" className="mvx-overlay-join" disabled={!conversation.connected||conversation.starting} onClick={conversation.start}><Headphones size={15}/>{conversation.starting?'Подключаем':'Войти в голос'}</button>:<>
    <button type="button" aria-pressed={conversation.muted} aria-label={conversation.muted?'Включить микрофон':'Выключить микрофон'} onClick={()=>conversation.setMuted(!conversation.muted)}>{conversation.muted?<MicOff size={16}/>:<Mic size={16}/>}</button>
    <button type="button" aria-pressed={conversation.deafened} aria-label={conversation.deafened?'Включить звук собеседников':'Не слышать собеседников'} onClick={()=>conversation.deafen(!conversation.deafened)}>{conversation.deafened?<HeadphoneOff size={16}/>:<Headphones size={16}/>}</button>
    <button type="button" className="is-leave" aria-label="Выйти из голоса" onClick={conversation.stop}><PhoneOff size={16}/></button>
   </>}
  </div>
  <ol ref={list} className="mvx-overlay-chat" aria-live="polite">{recent.length?recent.map(m=><li key={m.id}><strong>{m.name}</strong> {m.text}</li>):<li className="is-empty">Сообщений пока нет</li>}</ol>
  <form className="mvx-overlay-compose" onSubmit={e=>{e.preventDefault();if(conversation.connected&&text.trim()){conversation.post(text);setText('');}}}>
   <input aria-label="Сообщение в комнате" value={text} maxLength={500} placeholder="Написать в чат" onChange={e=>setText(e.target.value)} onKeyDown={e=>e.stopPropagation()} disabled={!conversation.connected}/>
   <button type="submit" aria-label="Отправить сообщение" disabled={!conversation.connected||!text.trim()}><Send size={14}/></button>
  </form>
 </aside>;
}
