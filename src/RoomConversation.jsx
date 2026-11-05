import {useEffect,useMemo,useRef,useState} from 'react';
import {Crown,Headphones,HeadphoneOff,MessageCircle,Mic,MicOff,PhoneOff,Send,Settings2,ShieldCheck,Volume2} from 'lucide-react';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {VOICE_PROFILES} from './room-conversation.js';
import './room-conversation.css';
// Stable, readable avatar colour per member id: hue only, fixed lightness.
function hue(id){let h=0;for(const c of String(id))h=(h*31+c.charCodeAt(0))%360;return h;}
function initials(name){const parts=String(name||'?').trim().split(/\s+/);return (parts[0]?.[0]||'?')+(parts[1]?.[0]||'');}
function Avatar({member,speaking,size=40}){
 const reduce=useReducedMotion();
 return <span className="rc-avatar" style={{'--avatar-hue':hue(member.id),width:size,height:size}} data-speaking={speaking||undefined}>
  <motion.span className="rc-avatar-ring" aria-hidden="true" animate={speaking&&!reduce?{scale:[1,1.08,1],opacity:1}:{scale:1,opacity:speaking?1:0}} transition={speaking&&!reduce?{duration:.9,repeat:Infinity,ease:'easeInOut'}:{duration:.15}}/>
  <span className="rc-avatar-face">{initials(member.name).toUpperCase()}</span>
 </span>;
}
function ToggleIcon({on,onIcon,offIcon}){
 const reduce=useReducedMotion();
 return <AnimatePresence mode="popLayout" initial={false}><motion.span key={on?'on':'off'} className="rc-icon" initial={reduce?false:{opacity:0,scale:.6,rotate:on?-25:25}} animate={{opacity:1,scale:1,rotate:0}} exit={reduce?undefined:{opacity:0,scale:.6}} transition={{type:'spring',stiffness:520,damping:28}}>{on?onIcon:offIcon}</motion.span></AnimatePresence>;
}
function Participant({member,conversation,self}){
 const [open,setOpen]=useState(false),speaking=!!conversation.speaking[member.id],link=conversation.links[member.id];
 const state=!member.voice?'Не в голосе':member.muted?'Микрофон выключен':self?'Это ты':link?.state==='connected'?(link.relay?'Через ретранслятор':'На связи'):conversation.voice?'Соединяемся…':'В голосе';
 const volume=conversation.settings.volumes?.[member.id]??1;
 return <li className="rc-member" data-voice={member.voice||undefined} data-speaking={speaking||undefined}>
  <button type="button" className="rc-member-main" disabled={self||!member.voice} aria-expanded={open} onClick={()=>setOpen(v=>!v)} title={self?undefined:'Громкость участника'}>
   <Avatar member={member} speaking={speaking}/>
   <span className="rc-member-text"><strong>{member.name}{member.host&&<Crown size={12} aria-label="Создатель комнаты"/>}</strong><small>{state}</small></span>
   {member.voice&&member.muted&&<MicOff className="rc-member-flag" size={14} aria-hidden="true"/>}
  </button>
  <AnimatePresence initial={false}>{open&&!self&&<motion.label className="rc-member-volume" initial={{height:0,opacity:0}} animate={{height:'auto',opacity:1}} exit={{height:0,opacity:0}}>
   <Volume2 size={13}/><input type="range" min="0" max="1" step=".05" value={volume} aria-label={'Громкость: '+member.name} onChange={e=>conversation.setVolume(member.id,Number(e.target.value))}/><output>{Math.round(volume*100)}%</output>
  </motion.label>}</AnimatePresence>
 </li>;
}
function VoiceSettings({conversation}){
 const s=conversation.settings,sink=typeof HTMLMediaElement!=='undefined'&&'setSinkId' in HTMLMediaElement.prototype;
 return <motion.div className="rc-settings" initial={{height:0,opacity:0}} animate={{height:'auto',opacity:1}} exit={{height:0,opacity:0}}>
  <label>Микрофон<select value={s.inputId} onChange={e=>conversation.applyInput({inputId:e.target.value})}><option value="">Системный по умолчанию</option>{conversation.devices.inputs.filter(d=>d.deviceId&&d.deviceId!=='default').map((d,i)=><option key={d.deviceId} value={d.deviceId}>{d.label||'Микрофон '+(i+1)}</option>)}</select></label>
  {sink&&conversation.devices.outputs.length>0&&<label>Звук собеседников<select value={s.outputId} onChange={e=>conversation.setOutput(e.target.value)}><option value="">Системный по умолчанию</option>{conversation.devices.outputs.filter(d=>d.deviceId&&d.deviceId!=='default').map((d,i)=><option key={d.deviceId} value={d.deviceId}>{d.label||'Устройство '+(i+1)}</option>)}</select></label>}
  <label>Громкость микрофона · {Math.round(s.inputGain*100)}%<input type="range" min="0" max="2" step=".05" value={s.inputGain} onChange={e=>conversation.applyInput({inputGain:Number(e.target.value)})}/></label>
  <div className="rc-level" aria-label="Уровень микрофона" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(conversation.inputLevel*100)}><span style={{transform:`scaleX(${conversation.voice?conversation.inputLevel:0})`}}/></div>
  <fieldset className="rc-profile"><legend>Качество звука</legend>{Object.entries(VOICE_PROFILES).map(([id,p])=><button type="button" key={id} aria-pressed={s.profile===id} onClick={()=>conversation.applyInput(id==='music'?{profile:id,echoCancellation:false,noiseSuppression:false,autoGainControl:false}:{profile:id,echoCancellation:true,noiseSuppression:true,autoGainControl:true})}><strong>{p.label}</strong><small>{p.hint}</small></button>)}</fieldset>
  {[['noiseSuppression','Шумоподавление'],['echoCancellation','Эхоподавление'],['autoGainControl','Автоуровень громкости']].map(([key,label])=><label key={key} className="rc-switch"><input type="checkbox" checked={!!s[key]} onChange={e=>conversation.applyInput({[key]:e.target.checked})}/><span aria-hidden="true"/>{label}</label>)}
 </motion.div>;
}
export default function RoomConversation({conversation}){
 const [text,setText]=useState(''),[settings,setSettings]=useState(false),list=useRef(null),reduce=useReducedMotion();
 useEffect(()=>{if(list.current)list.current.scrollTop=list.current.scrollHeight;},[conversation.messages]);
 const online=useMemo(()=>(conversation.members||[]).filter(m=>m.online).sort((a,b)=>Number(b.voice)-Number(a.voice)||Number(b.host)-Number(a.host)),[conversation.members]);
 const names=useMemo(()=>Object.fromEntries((conversation.members||[]).map(m=>[m.id,m])),[conversation.members]);
 const tap=reduce?undefined:{scale:.88};
 return <section className="rc" aria-label="Беседа комнаты">
  <header className="rc-head"><span><Headphones size={15}/>Голосовой канал</span>{conversation.relay&&<span className="rc-relay" title="Если прямое соединение невозможно, голос идёт через наш сервер"><ShieldCheck size={12}/>ретранслятор</span>}<small>{online.filter(m=>m.voice).length} в голосе · {online.length} в комнате</small></header>
  <ul className="rc-members">{online.map(m=><Participant key={m.id} member={m} self={m.id===conversation.memberId} conversation={conversation}/>)}</ul>
  <div className="rc-voicebar" role="toolbar" aria-label="Управление голосом">
   {!conversation.voice?<motion.button whileTap={tap} type="button" className="rc-join" disabled={!conversation.connected||conversation.starting} onClick={conversation.start}><Headphones size={16}/>{conversation.starting?'Подключаем…':'Войти в голосовой канал'}</motion.button>:<>
    <motion.button whileTap={tap} type="button" className="rc-tool" aria-pressed={conversation.muted} aria-label={conversation.muted?'Включить микрофон':'Выключить микрофон'} title={conversation.muted?'Включить микрофон':'Выключить микрофон'} onClick={()=>conversation.setMuted(!conversation.muted)}><ToggleIcon on={conversation.muted} onIcon={<MicOff size={18}/>} offIcon={<Mic size={18}/>}/></motion.button>
    <motion.button whileTap={tap} type="button" className="rc-tool" aria-pressed={conversation.deafened} aria-label={conversation.deafened?'Включить звук собеседников':'Выключить звук собеседников'} title={conversation.deafened?'Включить звук':'Не слышать собеседников'} onClick={()=>conversation.deafen(!conversation.deafened)}><ToggleIcon on={conversation.deafened} onIcon={<HeadphoneOff size={18}/>} offIcon={<Headphones size={18}/>}/></motion.button>
    <motion.button whileTap={tap} type="button" className="rc-tool" aria-expanded={settings} aria-label="Настройки голоса" title="Настройки голоса" onClick={()=>setSettings(v=>!v)}><motion.span className="rc-icon" animate={{rotate:settings&&!reduce?90:0}} transition={{type:'spring',stiffness:300,damping:20}}><Settings2 size={18}/></motion.span></motion.button>
    <motion.button whileTap={tap} type="button" className="rc-tool rc-leave" aria-label="Выйти из голосового канала" title="Выйти из голоса" onClick={conversation.stop}><PhoneOff size={18}/></motion.button>
   </>}
   {!conversation.voice&&<motion.button whileTap={tap} type="button" className="rc-tool" aria-expanded={settings} aria-label="Настройки голоса" title="Настройки голоса" onClick={()=>setSettings(v=>!v)}><motion.span className="rc-icon" animate={{rotate:settings&&!reduce?90:0}}><Settings2 size={18}/></motion.span></motion.button>}
  </div>
  <AnimatePresence initial={false}>{settings&&<VoiceSettings conversation={conversation}/>}</AnimatePresence>
  {conversation.error&&<p className="rc-error" role="status">{conversation.error}<button type="button" onClick={conversation.unlock}><Volume2 size={13}/>Включить звук беседы</button></p>}
  <div className="rc-chat-head"><MessageCircle size={14}/>Чат</div>
  <ol ref={list} className="rc-chat" aria-live="polite" aria-relevant="additions">{!conversation.messages.length&&<li className="rc-chat-empty">Обсуждайте серию здесь</li>}<AnimatePresence initial={false}>{conversation.messages.map(m=>{const member=names[m.from]||{id:m.from||m.name,name:m.name};return <motion.li key={m.id} initial={reduce?false:{opacity:0,y:6}} animate={{opacity:1,y:0}} exit={{opacity:0}} transition={{duration:.18}}><Avatar member={member} size={28}/><div><p><strong style={{'--avatar-hue':hue(member.id)}}>{m.name}</strong>{Number.isFinite(m.at)&&<time dateTime={new Date(m.at*1000).toISOString()}>{new Date(m.at*1000).toLocaleTimeString('ru',{hour:'2-digit',minute:'2-digit'})}</time>}</p><span>{m.text}</span></div></motion.li>;})}</AnimatePresence></ol>
  <form className="rc-compose" onSubmit={e=>{e.preventDefault();if(conversation.connected&&text.trim()){conversation.post(text);setText('');}}}><input aria-label="Сообщение в комнате" value={text} maxLength={500} onChange={e=>setText(e.target.value)} placeholder={conversation.connected?'Сообщение…':'Нет соединения'} disabled={!conversation.connected}/><motion.button whileTap={tap} aria-label="Отправить сообщение" disabled={!conversation.connected||!text.trim()}><Send size={15}/></motion.button></form>
 </section>;
}
