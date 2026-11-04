import {Users,Copy,X} from 'lucide-react';
import {roomLink} from './watch-room.js';
export function roomControlRows(room){
 const rows=room.info?[
  <label key="invite">Ссылка комнаты<div className="room-invite"><input readOnly aria-label="Ссылка комнаты" value={roomLink(room.info.id)}/><button aria-label="Скопировать ссылку комнаты" onClick={room.copy}><Copy size={16}/></button></div></label>,
  <label key="leader">Кто управляет<select value={room.state?.leader||room.info.memberId} onChange={e=>room.settings({leader:e.target.value})}>{(room.state?.members||[{id:room.info.memberId,name:'Ведущий'}]).map(m=><option key={m.id} value={m.id}>{m.name}{m.host?' · создатель':''}</option>)}</select></label>,
  <label key="everyone" className="mv-player-check"><input type="checkbox" checked={room.state?.everyone||false} onChange={e=>room.settings({everyone:e.target.checked})}/>Разрешить управление всем</label>,
  <label key="buffer" className="mv-player-check"><input type="checkbox" checked={room.state?.waitAll!==false} onChange={e=>room.settings({waitAll:e.target.checked})}/>Ждать буферизацию всех участников</label>,
  <p key="members" className="player-setting-help">{room.connected?'Комната подключена':'Соединение прервано'} · {room.state?.members.filter(m=>m.online).length||1} участн. {room.state?.held?'Ждём загрузку видео…':''}</p>,
  <button key="close" className="mv-player-settings-action" onClick={room.close}><X size={16}/>Закрыть комнату</button>
 ]:[
  <p key="help" className="player-setting-help">Друг откроет только витрину и это видео. Вход — по ссылке и паролю комнаты.</p>,
  <label key="password">Пароль комнаты<input aria-label="Пароль новой комнаты" type="password" minLength={6} maxLength={128} value={room.password} onChange={e=>room.setPassword(e.target.value)} placeholder="От 6 символов" autoComplete="new-password"/></label>,
  <button key="create" className="mv-player-settings-action" disabled={room.busy||room.password.length<6} onClick={room.create}><Users size={17}/>{room.busy?'Создаём…':'Создать комнату'}</button>
 ];
 if(room.error)rows.push(<p className="inline-error" role="alert" key="error">{room.error}</p>);return rows;
}
