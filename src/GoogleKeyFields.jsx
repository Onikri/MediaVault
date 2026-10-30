import {useEffect,useRef,useState} from 'react';
import {directKey,setDirectKey,keySlotScope,restoreDirectKeys,rememberDirectKey,forgetRememberedDirectKey,remembersDeviceKey} from './manga-direct-key.js';
export default function GoogleKeySettings({scope,onApply,onSaveServer,service,server=false}){
 const dirty=useRef(false);
 const [keys,setKeys]=useState(()=>[0,1,2].map(i=>server?'':directKey(keySlotScope(scope,i))));
 const [projects,setProjects]=useState(['','','']),[removed,setRemoved]=useState([]),[status,setStatus]=useState(null);
 const [remember,setRemember]=useState(()=>remembersDeviceKey(scope)),[busy,setBusy]=useState(false),[message,setMessage]=useState('');
 useEffect(()=>{let closed=false;
  if(server)service?.request('/reader/google/keys').then(value=>{if(!closed){setStatus(value);setProjects([0,1,2].map(i=>value.slots?.find(s=>s.slot===i)?.project||''));}}).catch(()=>{if(!closed)setMessage('Не удалось загрузить настройки ключей с Oracle.');});
  else restoreDirectKeys(scope).then(()=>{if(!closed&&!dirty.current){setKeys([0,1,2].map(i=>directKey(keySlotScope(scope,i))));setRemember([0,1,2].some(i=>remembersDeviceKey(keySlotScope(scope,i))));}});
  return()=>{closed=true;};
 },[scope,server,service?.server]);
 async function save(){setBusy(true);setMessage('');try{
  if(server){
   const rows=keys.map((key,slot)=>({slot,...(removed.includes(slot)?{key:''}:key.trim()?{key:key.trim()}:status?.slots?.some(s=>s.slot===slot)?{}:{key:''}),project:projects[slot]}));
   const value=await onSaveServer(rows);setStatus(value);setKeys(['','','']);setRemoved([]);setMessage('Ключи проверены и зашифрованы на Oracle.');
  }else{
   for(let i=0;i<3;i++){const id=keySlotScope(scope,i),value=keys[i].trim();if(remember&&value&&scope!=='anonymous')await rememberDirectKey(id,value);else{await forgetRememberedDirectKey(id);setDirectKey(id,value);}}
   setMessage(remember?'Ключи зашифрованы на устройстве.':'Ключи применены для этой вкладки.');onApply?.();
  }
 }catch(error){setMessage(error.message);}finally{setBusy(false);}}
 return <details className="reader-google-keys" open={!server}>
  <summary>{server?'Ключи Google на Oracle':'Личные ключи Google AI Studio'}{server&&status?' · '+status.keyCount+' подключено':''}</summary>
  <fieldset className="reader-google-key"><legend>До трёх ключей</legend>
   <p className="reader-hint">По две или три страницы в запросе, до трёх запросов одновременно. Буфер — до девяти страниц. Ключи одного проекта разделяют квоты. При ограничении Google очередь ожидает.</p>
   {keys.map((key,i)=><div className="reader-key-slot" key={i}>
    <label>{server?'Серверный ключ':'Личный ключ'} {i+1}
     <input aria-label={server?i?'Ключ Google AI Studio '+(i+1):'Ключ Google AI Studio':i?'Личный ключ быстрого перевода '+(i+1):'Личный ключ быстрого перевода'} type="password" autoComplete="new-password" spellCheck={false} value={key} placeholder={removed.includes(i)?'Будет удалён после сохранения':status?.slots?.some(s=>s.slot===i)?'Сохранён на Oracle · пустое поле сохраняет его':'Не добавлен'} onChange={e=>{dirty.current=true;setRemoved(old=>old.filter(n=>n!==i));setKeys(old=>old.map((v,n)=>n===i?e.target.value:v));}}/>
    </label>
    {server&&status?.slots?.some(s=>s.slot===i)&&<button className="text-link" type="button" onClick={()=>setRemoved(old=>old.includes(i)?old.filter(n=>n!==i):[...old,i])}>{removed.includes(i)?'Отменить удаление':'Удалить ключ '+(i+1)}</button>}
   </div>)}
   {server&&<details><summary>Проекты и общие лимиты</summary>{projects.map((value,i)=><label className="reader-project-label" key={i}>Проект ключа {i+1}<input aria-label={'Проект ключа '+(i+1)} value={value} maxLength={100} onChange={e=>setProjects(old=>old.map((v,n)=>n===i?e.target.value:v))} placeholder="Без названия — общий лимит"/></label>)}<p className="reader-hint">Ключи одного проекта укажи с одинаковым именем проекта AI Studio. Подписка Google AI Pro не определяет квоту API.</p></details>}
   {!server&&<label className="reader-checkbox"><input type="checkbox" checked={remember} onChange={e=>setRemember(e.target.checked)}/>Запомнить на этом устройстве</label>}
   <button type="button" disabled={busy||(server&&!status)} onClick={save}>{busy?'Сохраняем…':server?'Сохранить ключи на ВМ':'Применить личный ключ'}</button>
   <small role="status">{message||(server?'Ключи хранятся зашифрованными и не возвращаются браузеру.':'Ключи привязаны к профилю и передаются Oracle для выбранного запроса.')}</small>
   <a href="https://aistudio.google.com/api-keys" target="_blank" rel="noopener noreferrer">Создать ключ в Google AI Studio</a>
  </fieldset>
 </details>;
}
