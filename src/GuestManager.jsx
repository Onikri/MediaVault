import {useCallback,useEffect,useState} from 'react';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {Ban,Check,Clock,Copy,Link2,RotateCcw,Trash2,UserPlus} from 'lucide-react';
import UiSelect from './UiSelect.jsx';
import {inviteLink} from './guest-session.js';
import GuestAccessEditor,{accessSummary} from './GuestAccessEditor.jsx';

const TERMS=[['1','1 день'],['7','7 дней'],['30','30 дней'],['90','3 месяца'],['365','Год'],['','Без срока']];
const date=value=>new Date(value*1000).toLocaleDateString('ru',{day:'numeric',month:'short',year:'numeric'});
function status(guest){
 if(guest.disabled)return ['Заблокирован','is-off'];
 if(guest.expired)return ['Срок истёк','is-off'];
 if(!guest.enrolled)return ['Ждёт регистрации','is-wait'];
 return ['Активен','is-on'];
}
function CopyLink({url}){
 const [copied,setCopied]=useState(false);
 return <div className="guest-link"><span>{url}</span><button type="button" onClick={()=>navigator.clipboard?.writeText(url).then(()=>{setCopied(true);setTimeout(()=>setCopied(false),1600);})}>{copied?<Check size={15}/>:<Copy size={15}/>}{copied?'Скопировано':'Копировать'}</button></div>;
}
export default function GuestManager({service}){
 const reduce=useReducedMotion();
 const [guests,setGuests]=useState(null),[error,setError]=useState(''),[name,setName]=useState(''),[term,setTerm]=useState('30'),[busy,setBusy]=useState(''),[links,setLinks]=useState({}),[editing,setEditing]=useState('');
 const connected=service?.status==='connected'&&service.session?.role!=='guest';
 const load=useCallback(()=>service.request('/guests').then(d=>{setGuests(d.guests||[]);setError('');}).catch(e=>setError(e.message)),[service.request]);
 useEffect(()=>{if(connected)load();},[connected,load]);
 async function run(key,work){setBusy(key);setError('');try{await work();await load();}catch(e){setError(e.message);}finally{setBusy('');}}
 const create=event=>{event.preventDefault();if(!name.trim())return;run('create',async()=>{const d=await service.request('/guests',{method:'POST',body:{name:name.trim(),...(term?{days:Number(term)}:{})}});setLinks(v=>({...v,[d.guest.id]:inviteLink(d.invite)}));setName('');});};
 const change=(guest,body)=>run(guest.id,()=>service.request('/guests/'+guest.id,{method:'POST',body}));
 const reinvite=guest=>run(guest.id,async()=>{const d=await service.request('/guests/'+guest.id+'/invite',{method:'POST'});setLinks(v=>({...v,[guest.id]:inviteLink(d.invite)}));});
 const remove=guest=>{if(confirm('Удалить профиль «'+guest.name+'»? Гость сразу потеряет доступ.'))run(guest.id,()=>service.request('/guests/'+guest.id,{method:'DELETE'}));};
 if(!connected)return <section className="settings-card guest-manager"><h2>Гостевые профили</h2><p className="fine">{service?.error||'Подключаем сервер MediaVault…'}</p></section>;
 return <section className="settings-card guest-manager">
  <div className="guest-manager-head"><h2>Гостевые профили</h2><p className="fine">Создай профиль, отправь ссылку — гость сам задаст логин и пароль. По умолчанию гостю открыта вся библиотека; в «Доступе» можно оставить только выбранные тайтлы и отдельно разрешить смотреть или читать. Коллекцию на Google Диске и загрузки гости не видят.</p></div>
  <form className="guest-create" onSubmit={create}>
   <label><span>Имя гостя</span><input className="field-input" value={name} onChange={e=>setName(e.target.value)} maxLength={40} placeholder="Например, Аня" required/></label>
   <label><span>Доступ</span><UiSelect aria-label="Срок доступа" value={term} onChange={e=>setTerm(e.target.value)}>{TERMS.map(([v,l])=><option key={v} value={v}>{l}</option>)}</UiSelect></label>
   <button className="btn btn-primary" disabled={busy==='create'||!name.trim()}><UserPlus size={17}/>Создать и получить ссылку</button>
  </form>
  {error&&<p className="guest-manager-error" role="alert">{error}</p>}
  {guests&&!guests.length&&<p className="fine">Гостей пока нет.</p>}
  <ul className="guest-list"><AnimatePresence initial={false}>{(guests||[]).map(guest=>{const [label,tone]=status(guest);return <motion.li key={guest.id} layout={!reduce} initial={reduce?false:{opacity:0,y:8}} animate={{opacity:1,y:0}} exit={{opacity:0}}>
   <div className="guest-row">
    <div className="guest-who"><strong>{guest.name}</strong><small>{guest.login?'@'+guest.login:'логин ещё не выбран'}{guest.lastSeen?' · был '+date(guest.lastSeen):''}</small></div>
    <span className={'guest-status '+tone}>{label}</span>
    <span className="guest-term-cell"><Clock size={14}/>{guest.expiresAt?(guest.expired?'истёк ':'до ')+date(guest.expiresAt):'без срока'}</span>
   </div>
   <div className="guest-actions">
    <UiSelect aria-label={'Продлить доступ: '+guest.name} value="" onChange={e=>{const v=e.target.value;if(v==='unlimited')change(guest,{unlimited:true});else if(v)change(guest,{days:Number(v)});}}><option value="">Продлить…</option><option value="7">На 7 дней</option><option value="30">На 30 дней</option><option value="90">На 3 месяца</option><option value="365">На год</option><option value="unlimited">Без срока</option></UiSelect>
    <button type="button" disabled={busy===guest.id} onClick={()=>reinvite(guest)}><Link2 size={15}/>{guest.enrolled?'Ссылка для сброса пароля':'Новая ссылка'}</button>
    <button type="button" disabled={busy===guest.id} onClick={()=>change(guest,{disabled:!guest.disabled})}>{guest.disabled?<RotateCcw size={15}/>:<Ban size={15}/>}{guest.disabled?'Разблокировать':'Заблокировать'}</button>
    <button type="button" className="is-danger" disabled={busy===guest.id} onClick={()=>remove(guest)} aria-label={'Удалить '+guest.name}><Trash2 size={15}/></button>
   </div>
   <button type="button" className="guest-access-toggle" aria-expanded={editing===guest.id} onClick={()=>setEditing(v=>v===guest.id?'':guest.id)}><span>Доступ</span><strong>{accessSummary(guest.access)}</strong></button>
   {editing===guest.id&&<GuestAccessEditor guest={guest} busy={busy===guest.id} onSave={access=>change(guest,{access})}/>}
   {links[guest.id]&&<CopyLink url={links[guest.id]}/>}
  </motion.li>;})}</AnimatePresence></ul>
 </section>;
}
