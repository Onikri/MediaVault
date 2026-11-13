import {useEffect,useRef,useState} from 'react';
import {BookOpen,Plus,Check,Search} from 'lucide-react';
import {uiLocale} from './i18n/index.js';

export default function MangaSourceManager({service,onInstalled}){
 const [adultOnly,setAdultOnly]=useState(false),[open,setOpen]=useState(false),[status,setStatus]=useState(null),[language,setLanguage]=useState('ru'),[query,setQuery]=useState(''),[rows,setRows]=useState([]),[loading,setLoading]=useState(false),[busy,setBusy]=useState(''),[error,setError]=useState(''),[revision,setRevision]=useState(0),[pack,setPack]=useState(null);
 const [health,setHealth]=useState(null),[healthShown,setHealthShown]=useState(30),[coverage,setCoverage]=useState(null),[catalogStats,setCatalogStats]=useState(null),[catalogTags,setCatalogTags]=useState(null);
 const notified=useRef(''),packs=Number(service.session?.serverVersion)>=15;
 useEffect(()=>{setHealthShown(30);},[language,query]);
 useEffect(()=>{if(!open)return;const abort=new AbortController();service.request('/manga/source-coverage',{signal:abort.signal}).then(value=>{if(!abort.signal.aborted)setCoverage(value);}).catch(()=>{});Promise.all([service.request('/manga/catalog/stats',{signal:abort.signal}),service.request('/manga/catalog/tags?limit=30',{signal:abort.signal})]).then(([stats,facets])=>{if(!abort.signal.aborted){setCatalogStats(stats);setCatalogTags(facets);}}).catch(()=>{});return()=>abort.abort();},[open,revision,service.server]);
 useEffect(()=>{if(!open||Number(service.session?.serverVersion)<47)return;const abort=new AbortController();service.request('/discovery/manga/health',{signal:abort.signal}).then(setHealth).catch(()=>{});return()=>abort.abort();},[open,revision,service.server]);
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
   {coverage&&<details className="manga-source-coverage"><summary>Твои 18 сайтов · нативных {coverage.nativeRegistered} · расширений {coverage.extensionInstalled}</summary>
    <p className="fine">Этот список отражает интеграцию, а не доступность каждой главы. Перед чтением MediaVault проверяет реальную страницу.</p>
    {catalogStats&&<p className="fine">Постоянный индекс: {catalogStats.totalTitles} тайтлов · с тегами {catalogStats.titlesWithTags}. Источники без извлечённых тегов сохраняются отдельно.</p>}
    {catalogTags?.tags?.length>0&&<details><summary>Теги и жанры каталога · {catalogTags.tags.length} самых частых</summary>
      <div className="manga-extension-list">{catalogTags.tags.map(tag=><div key={tag.type+':'+tag.key}><span><strong>{tag.original}</strong><small>{tag.type==='genres'?'Жанр':'Тег'} · {tag.works} тайтлов · {tag.key}</small></span></div>)}</div>
    </details>}
    <div className="manga-extension-list">{coverage.sources.map(row=><div key={row.domain}><span><strong>{row.name}</strong><small>{row.domain} · {{native_registered:'Нативный адаптер',partial_mirror:'Только подтверждённое зеркало',extension_installed:'Suwayomi подключён',extension_not_installed:'Требуется расширение Suwayomi',unverified:'Адаптер не подтверждён',closed:'Сайт закрыт',not_registered:'Адаптер отсутствует'}[row.status]||row.status}</small></span></div>)}</div>
   </details>}
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
   <button type="button" className="source-adult-toggle" aria-pressed={adultOnly} onClick={()=>setAdultOnly(v=>!v)}>18+ источники</button>{loading?<p className="fine" role="status">Загружаем каталог…</p>:<div className="manga-extension-list">{rows.filter(row=>!adultOnly||row.adult).map(row=><div key={row.package}><span><strong>{row.name.replace(/^Tachiyomi:\s*/,'')}</strong><small>{row.language==='all'?'Мультиязычный':row.language.toUpperCase()}{row.adult?' · 18+':''}</small></span><button type="button" className="btn btn-secondary btn-small" disabled={!!busy||running||row.installed&&!row.hasUpdate||row.obsolete} aria-label={(row.hasUpdate?'Обновить: ':row.installed?'Подключён: ':'Подключить: ')+row.name} onClick={()=>install(row)}>{row.installed?<Check size={15}/>:<Plus size={15}/>} {busy===row.package?'Подключаем…':row.hasUpdate?'Обновить':row.installed?'Подключён':row.obsolete?'Недоступен':'Подключить'}</button></div>)}{!rows.some(row=>!adultOnly||row.adult)&&!error&&<p className="fine">По этому запросу источников нет.</p>}</div>}
   {health&&<details><summary>Проверка чтения · {health.working} / {health.checked}</summary><p className="fine">Проверены поиск, главы и загрузка тестовой страницы. Недоступные исключены из обычного поиска. Проверка отдельного тайтла выполняется перед чтением.</p>{health.sources.filter(s=>(language==='all'||s.language===language)&&s.name.toLocaleLowerCase().includes(query.toLocaleLowerCase())).slice(0,healthShown).map(s=><p className="fine" key={s.id}><strong>{s.name}</strong> · {s.language.toUpperCase()} · {s.status==='working'?'Страница загружается':s.message}<br/>{new Date(s.checked*1000).toLocaleString(uiLocale())}</p>)}{healthShown<health.sources.length&&<button type="button" className="text-link" onClick={()=>setHealthShown(n=>n+30)}>Ещё источники</button>}</details>}
   {error&&<p className="inline-error" role="alert">{error}</p>}
   <p className="fine">Установка расширения не подтверждает работу сайта. Поиск проверяет подключённые источники порциями; можно продолжить проверку остальных. Закрытые главы требуют доступа у издателя.</p>
   <a className="text-link" href="https://github.com/Suwayomi/Suwayomi-Server" target="_blank" rel="noopener noreferrer">Suwayomi · открытый исходный код</a>
  </div>}
 </details>;
}
