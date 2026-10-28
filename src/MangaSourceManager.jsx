import {useEffect,useRef,useState} from 'react';
import {BookOpen,Plus,Check,Search} from 'lucide-react';

export default function MangaSourceManager({service,onInstalled}){
 const [open,setOpen]=useState(false),[status,setStatus]=useState(null),[language,setLanguage]=useState('ru'),[query,setQuery]=useState(''),[rows,setRows]=useState([]),[loading,setLoading]=useState(false),[busy,setBusy]=useState(''),[error,setError]=useState(''),[revision,setRevision]=useState(0),[pack,setPack]=useState(null);
 const notified=useRef(''),packs=Number(service.session?.serverVersion)>=15;
 useEffect(()=>{if(!open)return;const abort=new AbortController();setLoading(true);setError('');
  const timer=setTimeout(()=>Promise.all([service.request('/manga/bridge/status',{signal:abort.signal}),service.request('/manga/bridge/extensions?'+new URLSearchParams({language,q:query}),{signal:abort.signal})]).then(([state,catalog])=>{if(!abort.signal.aborted){setStatus(state);setRows(catalog.extensions||[]);}}).catch(e=>{if(!abort.signal.aborted)setError(e.message);}).finally(()=>{if(!abort.signal.aborted)setLoading(false);}),180);
  return()=>{clearTimeout(timer);abort.abort();};
 },[open,language,query,revision]);
 useEffect(()=>{
  if(!open||!packs)return;const abort=new AbortController();let timer;
  async function update(){
   try{const value=await service.request('/manga/bridge/install-pack',{signal:abort.signal});if(abort.signal.aborted)return;setPack(value);
    if(value.state==='running')timer=setTimeout(update,1500);
    else if(value.id&&notified.current!==value.id){notified.current=value.id;setRevision(n=>n+1);onInstalled?.();}
   }catch(e){if(!abort.signal.aborted)setError(e.message);}
  }update();return()=>{clearTimeout(timer);abort.abort();};
 },[open,packs,pack?.id]);
 async function install(row){setBusy(row.package);setError('');try{await service.request('/manga/bridge/install',{method:'POST',body:{package:row.package}});setRevision(n=>n+1);onInstalled?.();}catch(e){setError(e.message);}finally{setBusy('');}}
 async function installPack(languages){setBusy('pack');setError('');try{const value=await service.request('/manga/bridge/install-pack',{method:'POST',body:{languages}});setPack(value);}catch(e){setError(e.message);}finally{setBusy('');}}
 const running=pack?.state==='running';
 return <details className="manga-source-manager" onToggle={e=>setOpen(e.currentTarget.open)}>
  <summary><BookOpen size={16}/>Больше источников <span>Suwayomi</span></summary>
  {open&&<div className="manga-source-manager-body">
   <p className="fine">{status?.ready?`${status.availableExtensions} расширений в каталоге · подключено источников: ${status.sources?.length||0}`:status?.message||'Подключи нужные читалки — они появятся в общем поиске переводов.'}</p>
   {packs&&<div className="manga-language-pack">
    <button type="button" className="btn btn-secondary btn-small" disabled={!status?.ready||!!busy||running} onClick={()=>installPack(['ru','en','ja','ko'])}>Подключить все RU · EN · JA · KO</button>
    {language!=='all'&&<button type="button" className="text-link" disabled={!status?.ready||!!busy||running} onClick={()=>installPack([language])}>Все расширения {language.toUpperCase()}</button>}
    {pack&&pack.state!=='idle'&&<p className="fine" role="status">{running?`Подключаем: ${pack.completed} / ${pack.total||'…'} · ${pack.current||''}`:pack.state==='done'?`Пакет готов: ${pack.completed} расширений проверено, новых ${pack.installed}.`:pack.state==='interrupted'?'Установка прервалась. Запусти пакет снова — установленные расширения сохранятся.':pack.state==='partial'?`Установка завершена с ошибками: ${pack.failed?.length||0}. Повтор пакета попробует их снова.`:pack.current||'Не удалось загрузить каталог.'}</p>}
    {!!pack?.failed?.length&&<details><summary>Не установились · {pack.failed.length}</summary>{pack.failed.map(row=><p className="fine" key={row.package}>{row.name}</p>)}</details>}
   </div>}
   <div className="manga-source-filters">
    <label><span className="sr-only">Язык дополнительных источников</span><select aria-label="Язык дополнительных источников" value={language} onChange={e=>setLanguage(e.target.value)}>{[['ru','Русский'],['en','Английский'],['ja','Японский · равки'],['ko','Корейский · оригиналы'],['all','RU · EN · JA · KO']].map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></label>
    <label><Search size={15}/><input aria-label="Поиск дополнительных источников" placeholder="Название читалки" value={query} onChange={e=>setQuery(e.target.value)}/></label>
   </div>
   {loading?<p className="fine" role="status">Загружаем каталог…</p>:<div className="manga-extension-list">{rows.map(row=><div key={row.package}><span><strong>{row.name.replace(/^Tachiyomi:\s*/,'')}</strong><small>{row.language.toUpperCase()}{row.adult?' · 18+':''}</small></span><button type="button" className="btn btn-secondary btn-small" disabled={!!busy||running||row.installed||row.obsolete} aria-label={(row.installed?'Подключён: ':'Подключить: ')+row.name} onClick={()=>install(row)}>{row.installed?<Check size={15}/>:<Plus size={15}/>} {busy===row.package?'Подключаем…':row.installed?'Подключён':row.obsolete?'Недоступен':'Подключить'}</button></div>)}{!rows.length&&!error&&<p className="fine">По этому запросу источников нет.</p>}</div>}
   {error&&<p className="inline-error" role="alert">{error}</p>}
   <p className="fine">Установка расширения не подтверждает работу сайта. Поиск проверяет подключённые источники порциями; можно продолжить проверку остальных. Закрытые главы требуют доступа у издателя.</p>
   <a className="text-link" href="https://github.com/Suwayomi/Suwayomi-Server" target="_blank" rel="noopener noreferrer">Suwayomi · открытый исходный код</a>
  </div>}
 </details>;
}
