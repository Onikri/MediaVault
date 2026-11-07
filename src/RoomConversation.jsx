import {useEffect,useMemo,useRef,useState} from 'react';
import {Crown,Headphones,HeadphoneOff,Mic,MicOff,PhoneOff,Settings2,Volume2,X} from 'lucide-react';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {VOICE_PROFILES} from './room-conversation.js';
import RoomChat from './RoomChat.jsx';
import './room-conversation.css';
import './room-chat-next.css';
import './room-rail.css';
import './room-panel.css';
// Stable, readable avatar colour per member id: hue only, fixed lightness.
function hue(id){let h=0;for(const c of String(id))h=(h*31+c.charCodeAt(0))%360;return h;}
function initials(name){const parts=String(name||'?').trim().split(/\s+/);return (parts[0]?.[0]||'?')+(parts[1]?.[0]||'');}
function Avatar({member,speaking,size=40}){
 const reduce=useReducedMotion();
 return <span className="rc-avatar" style={{'--avatar-hue':hue(member.id),width:size,height:size}} data-speaking={speaking||undefined}>
  <motion.span className="rc-avatar-ring" aria-hidden="true" animate={speaking&&!reduce?{scale:[1,1.08,1],opacity:1}:{scale:1,opacity:speaking?1:0}} transition={speaking&&!reduce?{duration:.9,repeat:Infinity,ease:'easeInOut'}:{duration:.15}}/>
  {member.avatar?<img className="rc-avatar-face rc-avatar-photo" src={member.avatar} alt="" draggable={false}/>:<span className="rc-avatar-face">{initials(member.name).toUpperCase()}</span>}
 </span>;
}
function ToggleIcon({on,onIcon,offIcon}){
 const reduce=useReducedMotion();
 return <AnimatePresence mode="popLayout" initial={false}><motion.span key={on?'on':'off'} className="rc-icon" initial={reduce?false:{opacity:0,scale:.6,rotate:on?-25:25}} animate={{opacity:1,scale:1,rotate:0}} exit={reduce?undefined:{opacity:0,scale:.6}} transition={{type:'spring',stiffness:520,damping:28}}>{on?onIcon:offIcon}</motion.span></AnimatePresence>;
}
// One circle per person in the rail; the card shows who it is, their voice
// state and a personal volume for that voice.
function RailMember({member,conversation,self,selected,onSelect}){
 const speaking=!!conversation.speaking[member.id];
 const label=member.name+(self?' (ты)':'')+(member.host?', создатель':'')+(!member.voice?', не в голосе':member.muted?', микрофон выключен':speaking?', говорит':', в голосе');
 return <li className="rc-rail-member" data-voice={member.voice||undefined} data-speaking={speaking||undefined} data-self={self||undefined}>
  <button type="button" aria-label={label} title={label} aria-pressed={selected} onClick={onSelect}>
   <Avatar member={member} speaking={speaking} size={40}/>
   {member.voice&&member.muted&&<span className="rc-rail-badge" aria-hidden="true"><MicOff size={10}/></span>}
   {member.host&&<span className="rc-rail-crown" aria-hidden="true"><Crown size={10}/></span>}
  </button>
 </li>;
}
function MemberCard({member,conversation,self,onClose}){
 const speaking=!!conversation.speaking[member.id],link=conversation.links[member.id];
 const state=!member.voice?'Не в голосе':member.muted?'Микрофон выключен':speaking?'Говорит':self?'В голосе':link?.state==='connected'?(link.relay?'Через ретранслятор':'На связи'):conversation.voice?'Соединяемся…':'В голосе';
 const volume=conversation.settings.volumes?.[member.id]??1;
 return <motion.div className="rc-card" initial={{opacity:0,y:-6}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-6}} transition={{duration:.16}}>
  <Avatar member={member} speaking={speaking} size={44}/>
  <div className="rc-card-text"><strong>{member.name}{self&&<small> ты</small>}</strong><span>{state}{member.host?', создатель':''}</span></div>
  <button type="button" className="rc-card-close" aria-label="Закрыть" onClick={onClose}><X size={15}/></button>
  {!self&&member.voice&&<label className="rc-card-volume"><Volume2 size={14}/><input type="range" min="0" max="1" step=".05" value={volume} aria-label={'Громкость: '+member.name} onChange={e=>conversation.setVolume(member.id,Number(e.target.value))}/><output>{Math.round(volume*100)}%</output></label>}
 </motion.div>;
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
 const [settings,setSettings]=useState(false),[selected,setSelected]=useState(null),reduce=useReducedMotion();
 const online=useMemo(()=>(conversation.members||[]).filter(m=>m.online).sort((a,b)=>Number(b.voice)-Number(a.voice)||Number(b.host)-Number(a.host)),[conversation.members]);
 const chosen=online.find(m=>m.id===selected);
 const tap=reduce?undefined:{scale:.88};
 return <section className="rc rc-stack" aria-label="Беседа комнаты">
  <header className="rc-head"><h2>Комната</h2><small>{online.length} в комнате{online.some(m=>m.voice)?', '+online.filter(m=>m.voice).length+' в голосе':''}</small>{conversation.relay&&<span className="rc-relay" title="Если прямое соединение невозможно, голос идёт через наш сервер">через ретранслятор</span>}</header>
  <nav className="rc-rail" aria-label="Участники и голос">
   <ul className="rc-rail-people">{online.map(m=><RailMember key={m.id} member={m} self={m.id===conversation.memberId} conversation={conversation} selected={selected===m.id} onSelect={()=>setSelected(v=>v===m.id?null:m.id)}/>)}</ul>
   <div className="rc-rail-voice" role="toolbar" aria-label="Управление голосом">
    {!conversation.voice?<motion.button whileTap={tap} type="button" className="rc-round is-join" disabled={!conversation.connected||conversation.starting} aria-label={conversation.starting?'Подключаем голос':'Войти в голос'} title={conversation.starting?'Подключаем голос':'Войти в голос'} onClick={conversation.start}><Headphones size={18}/></motion.button>:<>
     <motion.button whileTap={tap} type="button" className="rc-round" aria-pressed={conversation.muted} aria-label={conversation.muted?'Включить микрофон':'Выключить микрофон'} title={conversation.muted?'Включить микрофон':'Выключить микрофон'} onClick={()=>conversation.setMuted(!conversation.muted)}><ToggleIcon on={conversation.muted} onIcon={<MicOff size={18}/>} offIcon={<Mic size={18}/>}/></motion.button>
     <motion.button whileTap={tap} type="button" className="rc-round" aria-pressed={conversation.deafened} aria-label={conversation.deafened?'Включить звук собеседников':'Выключить звук собеседников'} title={conversation.deafened?'Включить звук':'Не слышать собеседников'} onClick={()=>conversation.deafen(!conversation.deafened)}><ToggleIcon on={conversation.deafened} onIcon={<HeadphoneOff size={18}/>} offIcon={<Headphones size={18}/>}/></motion.button>
     <motion.button whileTap={tap} type="button" className="rc-round is-leave" aria-label="Выйти из голосового канала" title="Выйти из голоса" onClick={conversation.stop}><PhoneOff size={18}/></motion.button>
    </>}
    <motion.button whileTap={tap} type="button" className="rc-round" aria-expanded={settings} aria-label="Настройки голоса" title="Настройки голоса" onClick={()=>setSettings(v=>!v)}><Settings2 size={18}/></motion.button>
   </div>
  </nav>
  <div className="rc-main">

   <AnimatePresence initial={false}>{chosen&&<MemberCard key={chosen.id} member={chosen} self={chosen.id===conversation.memberId} conversation={conversation} onClose={()=>setSelected(null)}/>}</AnimatePresence>
   {conversation.error&&<p className="rc-error" role="status">{conversation.error}<button type="button" onClick={conversation.unlock}><Volume2 size={13}/>Включить звук беседы</button></p>}
   <RoomChat conversation={conversation}/>
   <AnimatePresence initial={false}>{settings&&<motion.div key="settings" className="rc-settings-sheet" initial={{opacity:0,y:-8}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-8}} transition={{duration:.18}}><div className="rc-settings-head"><strong>Настройки голоса</strong><button type="button" aria-label="Закрыть настройки" onClick={()=>setSettings(false)}><X size={16}/></button></div><VoiceSettings conversation={conversation}/></motion.div>}</AnimatePresence>
  </div>
 </section>;
}
