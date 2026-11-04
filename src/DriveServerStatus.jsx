import {useEffect,useState} from 'react';
import {Cloud,RefreshCw} from 'lucide-react';
export default function DriveServerStatus({service,enabled}){
 const [value,setValue]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
 async function check(){setBusy(true);setError('');try{const result=await service.request('/google/connection/check',{method:'POST'});setValue(result);if(result.checkError)setError(result.checkError);await service.refresh();}catch(e){if(e.status!==404)setError(e.message);}finally{setBusy(false);}}
 useEffect(()=>{if(!enabled||service.status!=='connected')return;let closed=false;service.request('/google/connection').then(data=>{if(!closed)setValue(data);}).catch(()=>{});return()=>{closed=true;};},[enabled,service.status,service.server,service.session?.driveNeedsConsent]);
 if(!enabled)return null;
 const state=value?.needsConsent?'Google отклонил фоновое разрешение':value?.state==='ready'?'Разрешение проверено':value?.configured?'Разрешение сохранено · требуется проверка':'Фоновый доступ не подключён';
 return <section className="music-connections" aria-label="Google Drive на ВМ"><div className="music-connection-heading"><h2><Cloud size={18}/>Google Drive на ВМ</h2><span>{state}</span></div><p className="fine">Это разрешение для фонового импорта. Вход в профиль и доступ браузера к файлам подключаются отдельно.</p><div className="music-connection-actions"><button disabled={busy||service.status!=='connected'} onClick={async()=>{setError('');try{await service.connect();await check();}catch(e){setError(e.message);}}}>Обновить фоновый доступ Drive на ВМ</button><button disabled={busy||service.status!=='connected'} onClick={check}><RefreshCw size={14}/>{busy?'Проверяем…':'Проверить разрешение'}</button></div>{value?.checkedAt&&<small>Проверено: {new Date(value.checkedAt*1000).toLocaleString('ru-RU')}</small>}{error&&<p role="status">{error}</p>}</section>;
}
