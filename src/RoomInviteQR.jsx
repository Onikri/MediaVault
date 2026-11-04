import {useEffect,useState} from 'react';
import {roomLink} from './watch-room.js';
export default function RoomInviteQR({id,password}){
 const [image,setImage]=useState(''),[open,setOpen]=useState(false),[error,setError]=useState('');
 useEffect(()=>{let closed=false;if(!open)return;import('qrcode').then(module=>(module.default||module).toDataURL(roomLink(id)+'&key='+encodeURIComponent(password),{width:240,margin:2,errorCorrectionLevel:'M'})).then(value=>{if(!closed)setImage(value);}).catch(()=>{if(!closed)setError('Не удалось сформировать QR-код. Используй ссылку комнаты.');});return()=>{closed=true;};},[id,password,open]);
 return <details className="room-invite-qr" onToggle={e=>setOpen(e.currentTarget.open)}><summary>QR-код · вход без ввода пароля</summary>{open&&image&&<img src={image} alt="QR-код приглашения в комнату"/>}{error&&<small role="status">{error}</small>}<small>QR содержит пароль этой комнаты. Передавай его только участникам.</small></details>;
}
