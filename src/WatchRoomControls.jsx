import RoomConversation from './RoomConversation.jsx';
import RoomInviteQR from './RoomInviteQR.jsx';
import {Users,Copy,X} from 'lucide-react';
import {roomLink} from './watch-room.js';
import UiSelect from './UiSelect.jsx';
import UiSwitch from './UiSwitch.jsx';
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
