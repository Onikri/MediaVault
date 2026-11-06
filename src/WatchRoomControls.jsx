import RoomConversation from './RoomConversation.jsx';
import RoomInviteQR from './RoomInviteQR.jsx';
import {Users,Copy,X,Check} from 'lucide-react';
import {useState} from 'react';
import {roomLink} from './watch-room.js';
import UiSelect from './UiSelect.jsx';
import UiSwitch from './UiSwitch.jsx';
import {Choices,Switch,Note,Group} from './player-sheet-controls.jsx';

function plural(n,one,few,many){const a=n%10,b=n%100;return a===1&&b!==11?one:a>=2&&a<=4&&(b<12||b>14)?few:many;}
export const roomMembers=room=>(room.state?.members||[{id:room.info?.memberId,name:'Ты',online:true,host:true}]);
export function roomSummary(room){
 if(!room.info)return '';
 const online=roomMembers(room).filter(m=>m.online).length||1;
 return online+' '+plural(online,'участник','участника','участников');
}

// "Watch together" page of the player settings sheet.
export function RoomPanel({room}){
 const [copied,setCopied]=useState(false);
 if(!room.info)return <div className="mvx-room">
  <p className="mvx-room-lead">Друг увидит это видео синхронно с тобой. Вход по ссылке и паролю комнаты.</p>
  <label className="mvx-input"><span>Пароль комнаты</span><input aria-label="Пароль новой комнаты" type="password" minLength={6} maxLength={128} value={room.password} onChange={e=>room.setPassword(e.target.value)} placeholder="Не короче 6 символов" autoComplete="new-password"/></label>
  <button type="button" className="mvx-wide-primary" disabled={room.busy||room.password.length<6} onClick={room.create}><Users size={17}/>{room.busy?'Создаём комнату':'Создать комнату'}</button>
  {room.error&&<p className="mvx-error" role="alert">{room.error}</p>}
 </div>;
 const members=roomMembers(room),online=members.filter(m=>m.online),leader=room.state?.leader||room.info.memberId;
 async function copy(){await room.copy();setCopied(true);setTimeout(()=>setCopied(false),1600);}
 return <div className="mvx-room">
  <p className="mvx-room-status" role="status">{!room.connected?'Соединение прервано, переподключаемся':room.state?.held?'Ждём, пока видео загрузится у всех':'Комната открыта'}</p>
  <div className="mvx-invite">
   <input readOnly aria-label="Ссылка комнаты" value={roomLink(room.info.id)} onFocus={e=>e.currentTarget.select()}/>
   <button type="button" aria-label="Скопировать ссылку комнаты" onClick={copy}>{copied?<Check size={16}/>:<Copy size={16}/>}<span>{copied?'Скопировано':'Копировать'}</span></button>
  </div>
  <RoomInviteQR id={room.info.id} password={room.password}/>
  <section className="mvx-members" aria-label="Участники">
   <h3>В комнате {online.length}</h3>
   <ul>{online.map(m=><li key={m.id}><strong>{m.name}</strong><span>{m.id===leader?'Управляет':m.host?'Создатель':m.voice?'В голосе':''}</span></li>)}</ul>
  </section>
  {online.length>1&&<><h3 className="mvx-subhead">Кто управляет</h3><Choices label="Ведущий комнаты" value={leader} options={members.filter(m=>m.online||m.id===leader).map(m=>({value:m.id,label:m.name,disabled:!m.online,hint:m.host?'Создатель комнаты':undefined}))} onPick={value=>room.settings({leader:value})}/></>}
  <Group>
   <Switch label="Управлять могут все" checked={room.state?.everyone||false} onChange={everyone=>room.settings({everyone})}/>
   <Switch label="Ждать, пока загрузится у всех" checked={room.state?.waitAll!==false} onChange={waitAll=>room.settings({waitAll})}/>
  </Group>
  {online.length<2&&<Note>Управление можно передать, когда друг войдёт в комнату.</Note>}
  {/* In fullscreen the side chat is hidden, so the conversation lives here. */}
  <details className="room-fullscreen-chat mvx-room-chat"><summary>Беседа и голос</summary><RoomConversation conversation={room.conversation}/></details>
  {room.error&&<p className="mvx-error" role="alert">{room.error}</p>}
  <button type="button" className="mvx-danger" onClick={room.close}><X size={16}/>Закрыть комнату</button>
 </div>;
}

// Kept for any caller still rendering the previous flat rows.
export function roomControlRows(room){
 const members=room.state?.members||[{id:room.info?.memberId,name:'Ведущий',online:true}],online=members.filter(m=>m.online);
 const rows=room.info?[
  <label key="invite">Ссылка комнаты<div className="room-invite"><input readOnly aria-label="Ссылка комнаты" value={roomLink(room.info.id)}/><button aria-label="Скопировать ссылку комнаты" onClick={room.copy}><Copy size={16}/></button></div></label>,
  <RoomInviteQR key="qr" id={room.info.id} password={room.password}/>,
  <details key="chat" className="room-fullscreen-chat"><summary>Беседа · микрофон и сообщения</summary><RoomConversation conversation={room.conversation}/></details>,
  online.length>1?<label key="leader">Кто управляет<UiSelect aria-label="Ведущий комнаты" value={room.state?.leader||room.info.memberId} onValueChange={leader=>room.settings({leader})}>{members.filter(m=>m.online||m.id===room.state?.leader).map(m=><option key={m.id} value={m.id} disabled={!m.online}>{m.name}{m.host?' · создатель':''}</option>)}</UiSelect></label>:<p key="leader" className="player-setting-help">Управляет {members.find(m=>m.id===(room.state?.leader||room.info.memberId))?.name||'ведущий'}. Передать управление можно после входа друга.</p>,
  <label key="everyone" className="mv-player-check"><UiSwitch aria-label="Разрешить управление всем" checked={room.state?.everyone||false} onCheckedChange={everyone=>room.settings({everyone})}/>Разрешить управление всем</label>,
  <label key="buffer" className="mv-player-check"><UiSwitch aria-label="Ждать буферизацию всех участников" checked={room.state?.waitAll!==false} onCheckedChange={waitAll=>room.settings({waitAll})}/>Ждать буферизацию всех участников</label>,
  <p key="members" className="player-setting-help">{room.connected?'Комната подключена':'Соединение прервано'} · {room.state?.members.filter(m=>m.online).length||1} участн. {room.state?.held?'Ждём загрузку видео…':''}</p>,
  <button key="close" className="mv-player-settings-action" onClick={room.close}><X size={16}/>Закрыть комнату</button>
 ]:[
  <p key="help" className="player-setting-help">Друг откроет только витрину и это видео. Вход — по ссылке и паролю комнаты.</p>,
  <label key="password">Пароль комнаты<input aria-label="Пароль новой комнаты" type="password" minLength={6} maxLength={128} value={room.password} onChange={e=>room.setPassword(e.target.value)} placeholder="От 6 символов" autoComplete="new-password"/></label>,
  <button key="create" className="mv-player-settings-action" disabled={room.busy||room.password.length<6} onClick={room.create}><Users size={17}/>{room.busy?'Создаём…':'Создать комнату'}</button>
 ];
 if(room.error)rows.push(<p className="inline-error" role="alert" key="error">{room.error}</p>);return rows;
}
