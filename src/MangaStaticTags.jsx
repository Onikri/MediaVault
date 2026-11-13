import {useEffect,useMemo,useState} from 'react';
import {Search,Tags} from 'lucide-react';

/** Public build-time vocabulary, independent of MediaVault server login. */
// Lazy import keeps the large taxonomy in a separate Vite chunk.
const statuses = {
  complete:'Полный публичный справочник',
  partial:'Частичный список',
  stale:'Сохранённый список (сайт недоступен)',
  unavailable:'Теги не получены',
  pending:'Ожидает первой синхронизации',
  closed:'Сайт закрыт',
};

export default function MangaStaticTags(){
  const [snapshot,setSnapshot]=useState(null);
  const [error,setError]=useState('');
  const [filter,setFilter]=useState('');
  const [domain,setDomain]=useState('all');
  const [limit,setLimit]=useState(60);
  useEffect(()=>{
    let mounted=true;
    import('../public/data/manga-tags.json').then(({default:value})=>{
      if(!mounted)return;
      if(value.schemaVersion!==1||!Array.isArray(value.tags)||!Array.isArray(value.sources))
        throw Error('Недопустимый формат справочника тегов.');
      setSnapshot(value);
    }).catch(e=>{if(mounted)setError(e.message);});
    return ()=>{mounted=false;};
  },[]);
  const rows=useMemo(()=>{
    if(!snapshot)return [];
    const search=filter.toLocaleLowerCase('ru').trim();
    return snapshot.tags.filter(tag=>(domain==='all'||tag.sources.includes(domain)) &&
      (!search||[tag.label,tag.key,...(tag.originalLabels||[])].some(value=>value.toLocaleLowerCase('ru').includes(search))));
  },[snapshot,domain,filter]);
  if(error)return <p className="fine" role="status">Статический справочник тегов пока недоступен: {error}</p>;
  if(!snapshot)return <p className="fine" role="status">Загружаем теги из статического каталога…</p>;
  const active=snapshot.sources.filter(s=>['complete','partial','stale'].includes(s.status)).length;
  return <details className="manga-static-taxonomy">
    <summary><Tags size={15}/> Справочник тегов · {snapshot.tags.length} · {active}/{snapshot.sources.length} источников</summary>
    <div className="manga-source-manager-body">
      <p className="fine">Теги встроены в статический сайт и доступны без backend. Это данные публичных справочников, не гарантия охвата каждой манги.</p>
      <div className="manga-source-filters">
        <label><span className="sr-only">Источник тегов</span>
          <select value={domain} onChange={e=>{setDomain(e.target.value);setLimit(60);}} aria-label="Источник тегов">
            <option value="all">Все {snapshot.sources.length} источников</option>
            {snapshot.sources.map(source=><option key={source.domain} value={source.domain}>{source.name} — {statuses[source.status]||source.status}</option>)}
          </select>
        </label>
        <label><Search size={15}/><input value={filter} onChange={e=>{setFilter(e.target.value);setLimit(60);}} placeholder="Название тега или жанра" aria-label="Поиск по тегам"/></label>
      </div>
      {domain!=='all'&&<p className="fine">{statuses[snapshot.sources.find(s=>s.domain===domain)?.status]||'Неизвестный статус'}</p>}
      <p className="fine">Найдено {rows.length} · последняя синхронизация: {snapshot.generatedAt?new Date(snapshot.generatedAt).toLocaleString('ru-RU'):'ещё не запускалась'}</p>
      <div className="manga-extension-list">
        {rows.slice(0,limit).map(tag=><div key={tag.category+':'+tag.key}>
          <span><strong>{tag.label}</strong><small>{tag.category==='genre'?'Жанр':'Тег'} · {tag.sources.length} источников{tag.originalLabels?.length>1?' · '+tag.originalLabels.join(' / '):''}</small></span>
        </div>)}
      </div>
      {!rows.length&&<p className="fine">Нет подтверждённых тегов по этому фильтру. Синхронизация не должна придумывать отсутствующие данные.</p>}
      {rows.length>limit&&<button type="button" className="text-link" onClick={()=>setLimit(v=>v+60)}>Показать ещё {Math.min(60,rows.length-limit)}</button>}
    </div>
  </details>;
}
